from pathlib import Path

from tw_model_v880 import VERSION


def test_root_version_matches_runtime_version():
    """Keep the public root VERSION contract tied to the executable runtime."""
    published = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    assert published == VERSION
