from pathlib import Path

import pytest
from scaffold import scaffold

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "directory",
    ["apps", "services", "agents", "mcp-servers", "packages", "deploy", "docs"],
)
def test_required_monorepo_directory_exists(directory: str) -> None:
    assert (ROOT / directory).is_dir()


@pytest.mark.parametrize(
    "kind,relative", [("service", "services/billing-service"), ("agent", "agents/research-agent")]
)
def test_scaffold_creates_component(tmp_path: Path, kind: str, relative: str) -> None:
    (tmp_path / "templates").symlink_to(ROOT / "templates", target_is_directory=True)
    slug = relative.split("/")[1].removesuffix(f"-{kind}")
    destination = scaffold(kind, slug, tmp_path)
    assert destination == tmp_path / relative
    assert (destination / "pyproject.toml").is_file()
    assert next((destination / "src").rglob("__init__.py")).is_file()
