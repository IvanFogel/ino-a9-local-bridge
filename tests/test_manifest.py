"""Contract tests for the INO-A9 Home Assistant integration metadata."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_declares_config_flow_and_local_polling() -> None:
    manifest_path = (
        Path(__file__).parents[1] / "custom_components" / "ino_a9" / "manifest.json"
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert manifest["single_config_entry"] is True
    assert (manifest_path.parent / "services.yaml").is_file()
    hacs_path = manifest_path.parents[2] / "hacs.json"
    assert json.loads(hacs_path.read_text(encoding="utf-8"))["name"] == (
        "INO-A9 Local Bridge"
    )
