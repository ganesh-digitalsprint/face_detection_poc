"""Hard rule: no YOLO of any kind, no ultralytics, no torch in face_mask (docs/face_mask/MODEL_LICENSES.md)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_MODULES = {"ultralytics", "yolov5", "yolov8", "yolox", "torch", "torchvision", "tensorflow"}
SKIP_PARTS = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "training"}   # training/ is the optional train group


def _python_files():
    return [p for p in ROOT.rglob("*.py") if not SKIP_PARTS & set(p.relative_to(ROOT).parts) and p.name != "test_no_yolo_guard.py"]


def test_no_forbidden_imports_in_face_mask_code() -> None:
    offenders = []
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                if name.split(".")[0].lower() in FORBIDDEN_MODULES:
                    offenders.append(f"{path.relative_to(ROOT)}: import {name}")
    assert offenders == []


def test_pyproject_default_dependencies_have_no_yolo_or_torch() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    default_block = text.split("[dependency-groups]")[0]
    assert not re.search(r"ultralytics|yolo|torch|tensorflow", default_block, re.IGNORECASE)
    assert "ultralytics" not in text.lower() and "yolo" not in text.lower()


def test_requirements_txt_has_no_yolo_or_torch() -> None:
    req = ROOT / "requirements.txt"
    if req.exists():
        assert not re.search(r"ultralytics|yolo|torch|tensorflow", req.read_text(encoding="utf-8"), re.IGNORECASE)


def test_no_model_file_or_config_mentions_yolo() -> None:
    repo = ROOT.parents[2]
    candidates = list((repo / "data" / "model_weights" / "face_mask").glob("*")) if (repo / "data" / "model_weights" / "face_mask").is_dir() else []
    assert [p.name for p in candidates if "yolo" in p.name.lower()] == []
    yaml_text = (repo / "config" / "use_cases" / "face_mask.yaml").read_text(encoding="utf-8").lower()
    assert "yolo" not in yaml_text.replace("no yolo", "")


def test_forbidden_packages_are_not_installed() -> None:
    import importlib.util

    installed = [m for m in ("ultralytics", "torch", "torchvision", "tensorflow") if importlib.util.find_spec(m)]
    if installed:
        pytest.fail(f"forbidden packages are installed in the face_mask venv: {installed}")
