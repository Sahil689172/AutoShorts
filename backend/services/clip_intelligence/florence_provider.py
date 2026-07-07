"""Florence-2 inference wrapper (load once, analyze PIL images)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image

from backend.services.clip_intelligence.config import get_vision_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlorenceResult:
    description: str
    objects: list[str]
    confidence: float


class FlorenceProvider:
    """
    Loads Florence-2 once and provides per-image analysis.

    Returns:
    - description: caption-like summary
    - objects: list of detected object labels (if available)
    - confidence: heuristic confidence (Florence OD output doesn't always provide scores)
    """

    def __init__(
        self,
        model_id: str | None = None,
        *,
        device: str | None = None,
    ) -> None:
        # Single configuration point: defaults to VISION_MODEL config.
        self.model_id = model_id or get_vision_model()
        self._device_override = device
        self._loaded = False
        self._model: Any = None
        self._processor: Any = None
        self._device: Any = None
        self._torch_dtype: Any = None

    def _load(self) -> None:
        if self._loaded:
            return
        started = time.perf_counter()
        logger.info("Vision Model: %s", self.model_id)
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
        except Exception as exc:
            raise RuntimeError(
                "Florence dependencies missing. Install: torch, transformers."
            ) from exc

        if self._device_override:
            device = self._device_override
        else:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"

        torch_dtype = torch.float16 if device.startswith("cuda") else torch.float32
        model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
        ).to(device)
        processor = AutoProcessor.from_pretrained(self.model_id, trust_remote_code=True)

        self._device = device
        self._torch_dtype = torch_dtype
        self._model = model
        self._processor = processor
        self._loaded = True
        logger.info(
            "FlorenceProvider loaded %s on %s (%.2fs)",
            self.model_id,
            device,
            time.perf_counter() - started,
        )

    def analyze(self, image: Image.Image) -> FlorenceResult:
        self._load()
        img = image.convert("RGB")

        description = self._caption(img).strip() or "Unknown"
        objects = self._objects(img)

        # Florence OD/caption APIs may not expose calibrated scores; use deterministic heuristic.
        confidence = 0.95 if (description and description != "Unknown") else 0.60
        if objects:
            confidence = max(confidence, 0.85)

        return FlorenceResult(
            description=description,
            objects=objects,
            confidence=float(confidence),
        )

    def _generate(self, prompt: str, image: Image.Image, *, max_new_tokens: int = 1024) -> str:
        inputs = self._processor(text=prompt, images=image, return_tensors="pt").to(
            self._device, self._torch_dtype
        )
        generated_ids = self._model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=max_new_tokens,
            num_beams=3,
            do_sample=False,
        )
        return self._processor.batch_decode(generated_ids, skip_special_tokens=False)[0]

    def _caption(self, image: Image.Image) -> str:
        raw = self._generate("<CAPTION>", image, max_new_tokens=128)
        try:
            parsed = self._processor.post_process_generation(
                raw, task="<CAPTION>", image_size=image.size
            )
            # Some processors return {"<CAPTION>": "..."}; others may return string.
            if isinstance(parsed, dict):
                cap = parsed.get("<CAPTION>")
                if isinstance(cap, str):
                    return cap
            if isinstance(parsed, str):
                return parsed
        except Exception:
            pass
        # Fallback: best-effort strip special tokens.
        return raw.replace("<CAPTION>", "").strip()

    def _objects(self, image: Image.Image) -> list[str]:
        raw = self._generate("<OD>", image, max_new_tokens=512)
        try:
            parsed = self._processor.post_process_generation(
                raw, task="<OD>", image_size=image.size
            )
            # Expected structure often: {"<OD>": {"bboxes": [...], "labels": [...]}}
            if isinstance(parsed, dict) and "<OD>" in parsed:
                od = parsed.get("<OD>") or {}
                if isinstance(od, dict):
                    labels = od.get("labels") or []
                    if isinstance(labels, list):
                        uniq: list[str] = []
                        seen: set[str] = set()
                        for lbl in labels:
                            s = str(lbl).strip()
                            if not s or s in seen:
                                continue
                            seen.add(s)
                            uniq.append(s)
                        return uniq
        except Exception:
            return []
        return []

