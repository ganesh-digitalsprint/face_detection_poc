from __future__ import annotations

import pytest

from app.core.config import FaceMaskConfig, load_face_mask_config


@pytest.fixture(scope="session")
def cfg() -> FaceMaskConfig:
    """The real default config/use_cases/face_mask.yaml (FM-10): tests exercise the shipped defaults."""
    return load_face_mask_config()
