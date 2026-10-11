from __future__ import annotations

from pathlib import Path


REPOSITORY_DIR = Path(__file__).parents[2]
APP_RELEASE_WORKFLOW = REPOSITORY_DIR / ".github/workflows/app-release.yml"
VALIDATION_WORKFLOW = REPOSITORY_DIR / ".github/workflows/validate.yml"
BRIDGE_DOCUMENTATION = REPOSITORY_DIR / "docs/bridge.md"


def test_app_release_workflow_runs_only_for_app_tags() -> None:
    workflow = APP_RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert '  push:\n    tags:\n      - "app-v*"' in workflow
    assert "  release:" not in workflow
    assert 'expected_tag="app-v${app_version}"' in workflow
    assert 'app_version="${APP_VERSION#\\"}"' in workflow
    assert 'app_version="${app_version%\\"}"' in workflow
    assert 'echo "version=${app_version}" >> "$GITHUB_OUTPUT"' in workflow


def test_validation_workflow_checks_published_integration_releases() -> None:
    workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")

    assert "  release:\n    types: [published]" in workflow


def test_bridge_documentation_explains_independent_release_channels() -> None:
    documentation = BRIDGE_DOCUMENTATION.read_text(encoding="utf-8")

    assert "app-v*" in documentation
    assert "v*" in documentation
    assert "HACS" in documentation
