"""Project configuration, read once from the repo-root config.yml.
"""

from pathlib import Path
from typing import Any

import yaml

LANDMARK = "config.yml"

def _find_root() -> Path:
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        if (parent / LANDMARK).exists():
            return parent
    return cwd


ROOT = _find_root()
_config_file = ROOT / LANDMARK
_config = yaml.safe_load(_config_file.read_text()) or {} if _config_file.exists() else {}

# Project data layout, fixed by convention: <repo>/data holds one folder per
# dataset version (config.yml `version`) plus the shared resources folder.
# Only the version ever changes, so these are not config knobs.
#
# VERSION holds the published artifacts of the current version directly; only
# derived material that is not part of the release gets a subdirectory, e.g.
# VERSION / "figures". RESOURCES sits beside the version folders rather than
# inside them: the raw institutional records are the same for every version.
VERSION = ROOT / "data" / _config.get("version", "")
RESOURCES = ROOT / "data" / "resources"


def __getattr__(name: str) -> Any:
    """Resolve unknown module attributes against config.yml (PEP 562).

    Only called when normal lookup fails, so the names defined above always win.
    """
    try:
        return _config[name]
    except KeyError:
        raise AttributeError(f"{name!r} is not defined in {_config_file}") from None

def __dir__() -> list[str]:
    """Include the config.yml keys, so `cfg.<tab>` completes them in Jupyter."""
    return sorted(set(globals()) | set(_config))


def data_dir(subdir: str) -> Path:
    """An external dataset directory under `data_root`, e.g. data_dir('era5')."""
    return Path(_config.get("data_root", "")) / _config.get("dirs", {}).get(subdir, subdir)
