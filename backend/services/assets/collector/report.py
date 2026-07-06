"""Collection run summary."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CollectionReport:
    topic: str
    desired_count: int
    providers: list[str]
    queries: list[str] = field(default_factory=list)
    downloaded: int = 0
    skipped: int = 0
    duplicates: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0
    downloaded_assets: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def format_summary(self) -> str:
        lines = [
            "",
            "Collection Report",
            "────────────────────────────────────────",
            f"  Topic:       {self.topic}",
            f"  Providers:   {', '.join(self.providers)}",
            f"  Queries:     {len(self.queries)}",
            f"  Downloaded:  {self.downloaded}",
            f"  Skipped:     {self.skipped}",
            f"  Duplicates:  {self.duplicates}",
            f"  Failed:      {self.failed}",
            f"  Time:        {self.elapsed_seconds:.1f}s",
            "────────────────────────────────────────",
        ]
        if self.downloaded_assets:
            lines.append("  New assets:")
            for asset_id in self.downloaded_assets:
                lines.append(f"    - {asset_id}")
        if self.errors:
            lines.append("  Errors:")
            for err in self.errors[:10]:
                lines.append(f"    - {err}")
        return "\n".join(lines)
