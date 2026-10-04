"""Registry manifests stay consistent with the package. Pure file checks."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

SERVER = json.loads((ROOT / "server.json").read_text())
PYPROJECT = tomllib.loads((ROOT / "mcp_server" / "pyproject.toml").read_text())["project"]
README = (ROOT / "mcp_server" / "README.md").read_text()
INIT = (ROOT / "mcp_server" / "prediction_bot_mcp" / "__init__.py").read_text()


def test_versions_match():
    init_version = re.search(r'__version__ = "([^"]+)"', INIT).group(1)
    versions = {SERVER["version"], SERVER["packages"][0]["version"], PYPROJECT["version"], init_version}
    assert len(versions) == 1, versions


def test_pypi_package_and_ownership_line():
    pkg = SERVER["packages"][0]
    assert pkg["registryType"] == "pypi"
    assert pkg["identifier"] == PYPROJECT["name"] == "prediction-bot-mcp"
    # The official registry verifies PyPI ownership by this exact string in the README.
    assert f"mcp-name: {SERVER['name']} " in README or f"mcp-name: {SERVER['name']}\n" in README


def test_namespace_and_limits():
    assert SERVER["name"].startswith("io.github.wballztrading1/")
    assert len(SERVER["description"]) <= 100 and len(SERVER["title"]) <= 100


def test_remote_points_at_hosted_mcp():
    sys.path.insert(0, str(ROOT))
    import landing  # noqa: F401  (import check only; main needs secrets outside TEST_MODE)

    (remote,) = SERVER["remotes"]
    assert remote["type"] == "streamable-http"
    assert remote["url"] == "https://prediction-bot-iggf.onrender.com/mcp"


def test_glama_maintainer():
    glama = json.loads((ROOT / "glama.json").read_text())
    assert glama["maintainers"] == ["wballztrading1"]
