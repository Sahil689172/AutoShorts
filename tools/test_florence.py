"""Standalone Florence-2 smoke test — independent of AutoShorts.

Verifies the same model and inference path used by ClipAnalyzer's FlorenceProvider.

Usage (from project root):
    python tools/test_florence.py path/to/image.jpg
    python tools/test_florence.py path/to/frame.png --device cpu
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

# Kept standalone (no AutoShorts imports) but mirrors the VISION_MODEL config
# in backend/services/clip_intelligence/config.py so both resolve identically.
DEFAULT_VISION_MODEL = "microsoft/Florence-2-base"


def _configured_model() -> str:
    configured = os.environ.get("VISION_MODEL", "").strip()
    return configured or DEFAULT_VISION_MODEL


DEFAULT_MODEL_ID = _configured_model()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test Florence-2 caption + object detection on a single image.",
    )
    parser.add_argument(
        "image",
        type=Path,
        help="Path to an image file (jpg, png, webp, etc.)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_ID,
        help=f"Hugging Face model id (default: {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Force device (e.g. cpu, cuda:0). Default: cuda:0 if available else cpu.",
    )
    return parser.parse_args()


def _load_model(model_id: str, device_override: str | None) -> tuple[Any, Any, str, Any]:
    """Load Florence-2 model + processor (mirrors FlorenceProvider._load)."""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
    except ImportError as exc:
        raise RuntimeError(
            "Florence dependencies missing. Install: pip install torch transformers Pillow"
        ) from exc

    if device_override:
        device = device_override
    else:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"

    torch_dtype = torch.float16 if device.startswith("cuda") else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        trust_remote_code=True,
    ).to(device)
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    return model, processor, device, torch_dtype


def _generate(
    model: Any,
    processor: Any,
    device: str,
    torch_dtype: Any,
    prompt: str,
    image: Any,
    *,
    max_new_tokens: int = 1024,
) -> str:
    """Mirrors FlorenceProvider._generate."""
    inputs = processor(text=prompt, images=image, return_tensors="pt").to(
        device, torch_dtype
    )
    generated_ids = model.generate(
        input_ids=inputs["input_ids"],
        pixel_values=inputs["pixel_values"],
        max_new_tokens=max_new_tokens,
        num_beams=3,
        do_sample=False,
    )
    return processor.batch_decode(generated_ids, skip_special_tokens=False)[0]


def _caption(model: Any, processor: Any, device: str, torch_dtype: Any, image: Any) -> str:
    """Mirrors FlorenceProvider._caption."""
    raw = _generate(
        model, processor, device, torch_dtype, "<CAPTION>", image, max_new_tokens=128
    )
    try:
        parsed = processor.post_process_generation(
            raw, task="<CAPTION>", image_size=image.size
        )
        if isinstance(parsed, dict):
            cap = parsed.get("<CAPTION>")
            if isinstance(cap, str):
                return cap
        if isinstance(parsed, str):
            return parsed
    except Exception:
        pass
    return raw.replace("<CAPTION>", "").strip()


def _objects(model: Any, processor: Any, device: str, torch_dtype: Any, image: Any) -> list[str]:
    """Mirrors FlorenceProvider._objects."""
    raw = _generate(
        model, processor, device, torch_dtype, "<OD>", image, max_new_tokens=512
    )
    try:
        parsed = processor.post_process_generation(
            raw, task="<OD>", image_size=image.size
        )
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


def main() -> int:
    args = _parse_args()
    image_path = args.image.resolve()

    if not image_path.is_file():
        print(f"Error: image not found: {image_path}", file=sys.stderr)
        return 1

    try:
        from PIL import Image
    except ImportError as exc:
        print(f"Error: missing dependency: {exc}", file=sys.stderr)
        print("Run: pip install Pillow", file=sys.stderr)
        return 1

    print(f"Model:  {args.model}")
    print(f"Image:  {image_path}")
    print()

    load_started = time.perf_counter()
    try:
        model, processor, device, torch_dtype = _load_model(args.model, args.device)
    except Exception as exc:
        print(f"Error: failed to load model: {exc}", file=sys.stderr)
        return 1

    load_time = time.perf_counter() - load_started
    print(f"model loaded: yes")
    print(f"device:       {device}")
    print(f"load time:    {load_time:.2f} s")
    print()

    image = Image.open(image_path).convert("RGB")

    infer_started = time.perf_counter()
    try:
        caption = _caption(model, processor, device, torch_dtype, image)
        objects = _objects(model, processor, device, torch_dtype, image)
    except Exception as exc:
        print(f"Error: inference failed: {exc}", file=sys.stderr)
        return 1

    infer_time = time.perf_counter() - infer_started

    print(f"inference time: {infer_time:.2f} s")
    print(f"caption:        {caption or '(empty)'}")
    if objects:
        print(f"objects:        {', '.join(objects)}")
    else:
        print("objects:        (none detected)")

    print()
    print("Florence smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
