"""Single configuration point for the clip intelligence vision model."""

from __future__ import annotations

import os

# Default vision analyzer model.
# Florence-2 Base is smaller/faster than Large and is the default for CPU inference.
DEFAULT_VISION_MODEL = "microsoft/Florence-2-base"

# Environment variable used to override the vision model in one place.
VISION_MODEL_ENV = "VISION_MODEL"


def get_vision_model() -> str:
    """Return the configured vision model id.

    Override by setting the VISION_MODEL environment variable, e.g.:
        VISION_MODEL=microsoft/Florence-2-large
    """
    configured = os.environ.get(VISION_MODEL_ENV, "").strip()
    return configured or DEFAULT_VISION_MODEL


#: Resolved vision model id (evaluated at import time).
VISION_MODEL = get_vision_model()
