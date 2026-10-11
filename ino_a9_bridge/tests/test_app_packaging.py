from __future__ import annotations

from pathlib import Path

import yaml


APP_DIR = Path(__file__).parents[1]


def test_app_manifest_publishes_rtsp_only() -> None:
    config = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))

    assert config["name"] == "INO-A9 Local Bridge"
    assert config["version"] == "0.4.2"
    assert config["slug"] == "ino_a9_bridge"
    assert "image" not in config
    assert config["url"].endswith("/tree/main/ino_a9_bridge")
    assert config["arch"] == ["amd64", "aarch64"]
    assert config["homeassistant"] == "2026.6.0"
    assert config["init"] is False
    assert config["discovery"] == ["ino_a9"]
    assert config["ports"] == {"8554/tcp": 8554}
    assert config["ports_description"]["8554/tcp"] == "RTSP camera stream"
    assert config["schema"]["cameras"] == [
        {
            "name": "match(^[A-Za-z0-9_-]+$)",
            "host": "str(1,)",
            "port": "port",
            "bootstrap_prefix": "password",
            "user": "password",
            "lan_password": "password",
        }
    ]


def test_app_image_pins_go2rtc_and_supervises_both_processes() -> None:
    dockerfile = (APP_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert "ghcr.io/home-assistant/base:3.23" in dockerfile
    assert "sha256:1c7a8c7321c15cdc327c264232a76e6fbfdaf7f2b1734a8d8da6fcc994f66015" in dockerfile
    assert "alexxit/go2rtc:1.9.14" in dockerfile
    assert "sha256:675c318b23c06fd862a61d262240c9a63436b4050d177ffc68a32710d9e05bae" in dockerfile
    assert "COPY rootfs /" in dockerfile
    assert (APP_DIR / "rootfs/etc/cont-init.d/10-runtime-config").is_file()
    assert (APP_DIR / "rootfs/etc/services.d/bridge/run").is_file()
    assert (APP_DIR / "rootfs/etc/services.d/go2rtc/run").is_file()
