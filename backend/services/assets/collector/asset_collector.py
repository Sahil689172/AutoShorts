"""Offline asset collection orchestrator."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from agents.query_agent import QueryAgent, QueryAgentError
from backend.services.assets.cache.dedup_store import DedupStore
from backend.services.assets.collector.report import CollectionReport
from backend.services.assets.library.master_index import MasterIndex
from backend.services.assets.library.storage import LibraryStorage
from backend.services.assets.metadata.models import AssetMetadata
from backend.services.assets.providers.asset_provider import AssetProvider, ProviderAsset
from backend.services.assets.providers.registry import resolve_providers
from backend.services.assets.utils.paths import subtopic_from_query, topic_dir_name

logger = logging.getLogger(__name__)

RESULTS_PER_QUERY = 15


class AssetCollectorError(Exception):
    """Base error for asset collection."""


class AssetCollector:
    """
    Grow the local asset library for a topic.

    Separate from video generation — does not touch the render pipeline.
    """

    def __init__(
        self,
        query_agent: QueryAgent | None = None,
        storage: LibraryStorage | None = None,
        master_index: MasterIndex | None = None,
    ) -> None:
        self.query_agent = query_agent or QueryAgent()
        self.storage = storage or LibraryStorage()
        self.master_index = master_index or MasterIndex()
        self.dedup = DedupStore()

    def collect(
        self,
        topic: str,
        desired_count: int,
        providers: list[str],
        *,
        query_count: int | None = None,
    ) -> CollectionReport:
        topic = topic.strip()
        if not topic:
            raise AssetCollectorError("Topic cannot be empty")
        if desired_count < 1:
            raise AssetCollectorError("Desired count must be at least 1")

        provider_instances = resolve_providers(providers)
        if not provider_instances:
            raise AssetCollectorError(
                "No configured providers. Set API keys (e.g. PEXELS_API_KEY) "
                f"and choose from: {', '.join(providers)}"
            )

        started = time.perf_counter()
        report = CollectionReport(
            topic=topic,
            desired_count=desired_count,
            providers=[p.name for p in provider_instances],
        )

        self._load_dedup_state()
        queries = self._generate_queries(topic, desired_count, query_count)
        report.queries = queries

        print(f"\nTopic: {topic_dir_name(topic)}")
        print(f"Generated {len(queries)} search queries:")
        for q in queries:
            print(f"  - {q}")

        session = requests.Session()
        session.headers["User-Agent"] = "AutoShorts-Collector/1.0"

        for query in queries:
            if report.downloaded >= desired_count:
                break
            for provider in provider_instances:
                if report.downloaded >= desired_count:
                    break
                self._collect_from_query(
                    topic=topic,
                    query=query,
                    provider=provider,
                    desired_count=desired_count,
                    report=report,
                    session=session,
                )

        self.master_index.save()
        report.elapsed_seconds = time.perf_counter() - started
        print(report.format_summary())
        return report

    def _load_dedup_state(self) -> None:
        self.master_index.load()
        clip_keys, urls = self.master_index.clip_keys_and_urls()
        self.dedup.load_from_records(self.master_index.asset_ids, clip_keys, urls)

    def _generate_queries(
        self,
        topic: str,
        desired_count: int,
        query_count: int | None,
    ) -> list[str]:
        count = query_count or max(10, desired_count)
        try:
            return self.query_agent.generate_topic_queries(topic, count=count)
        except QueryAgentError as exc:
            logger.warning("QueryAgent failed, using fallback queries: %s", exc)
            return self.query_agent._fallback_topic_queries(topic, count)

    def _collect_from_query(
        self,
        *,
        topic: str,
        query: str,
        provider: AssetProvider,
        desired_count: int,
        report: CollectionReport,
        session: requests.Session,
    ) -> None:
        try:
            remote_assets = provider.search(query, per_page=RESULTS_PER_QUERY)
        except Exception as exc:
            msg = f"{provider.name} search failed for {query!r}: {exc}"
            logger.error(msg)
            report.errors.append(msg)
            report.failed += 1
            return

        print(f"  {provider.name} | {query!r} → {len(remote_assets)} results")

        for remote in remote_assets:
            if report.downloaded >= desired_count:
                report.skipped += 1
                continue

            asset_id = self._make_asset_id(remote)
            if self.dedup.is_duplicate(
                asset_id,
                remote.provider,
                remote.clip_id,
                remote.download_url,
            ):
                report.duplicates += 1
                logger.debug("Duplicate skipped: %s", asset_id)
                continue

            if self._asset_file_exists(asset_id):
                report.duplicates += 1
                self.dedup.register(
                    asset_id, remote.provider, remote.clip_id, remote.download_url
                )
                continue

            subtopic = subtopic_from_query(topic, query)
            metadata = AssetMetadata(
                asset_id=asset_id,
                provider=remote.provider,
                download_url=remote.download_url,
                search_query=query,
                topic=topic_dir_name(topic),
                subtopic=subtopic,
                tags=list(remote.tags),
                width=remote.width,
                height=remote.height,
                duration=remote.duration,
                download_date=AssetMetadata.now_iso(),
                local_path="",
                media_type=remote.media_type,
                provider_clip_id=remote.clip_id,
                photographer=remote.photographer,
            )

            try:
                self.storage.store(
                    metadata,
                    remote.download_url,
                    extension=".mp4",
                    session=session,
                )
            except Exception as exc:
                msg = f"Download failed {asset_id}: {exc}"
                logger.error(msg)
                report.errors.append(msg)
                report.failed += 1
                continue

            self.dedup.register(
                asset_id, remote.provider, remote.clip_id, remote.download_url
            )
            self.master_index.add(metadata)
            report.downloaded += 1
            report.downloaded_assets.append(asset_id)
            logger.info("Downloaded %s for topic %r", asset_id, topic)

    @staticmethod
    def _make_asset_id(remote: ProviderAsset) -> str:
        if remote.clip_id:
            return f"{remote.provider}_{remote.clip_id}"
        import hashlib

        digest = hashlib.sha256(remote.download_url.encode()).hexdigest()[:12]
        return f"{remote.provider}_{digest}"

    def _asset_file_exists(self, asset_id: str) -> bool:
        index_path = Path("assets/library/index") / f"{asset_id}.json"
        return index_path.is_file()
