"""Shared fixtures and compatibility shims for the Home Assistant tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _TurboJPEG:
    """Small no-op implementation; camera tests do not resize JPEGs."""

    def decode_header(self, _content: bytes) -> tuple[int, int, int, int]:
        return (0, 0, 0, 0)

    def scale_with_quality(
        self,
        content: bytes,
        *,
        scaling_factor: tuple[int, int],
        quality: int,
    ) -> bytes:
        return content


sys.modules.setdefault("turbojpeg", types.SimpleNamespace(TurboJPEG=_TurboJPEG))
