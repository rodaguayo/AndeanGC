from pathlib import Path
import yaml

LANDMARK = "config.yml"
_config_cache = None


def _load():
    global _config_cache
    if _config_cache is None:
        repo_root = find_repo_root()
        cfg = repo_root / LANDMARK
        if cfg.exists():
            with open(cfg) as f:
                _config_cache = yaml.safe_load(f) or {}
        else:
            _config_cache = {}
    return _config_cache


def find_repo_root():
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        if (parent / LANDMARK).exists():
            return parent
    return cwd


def get(key, default=None):
    return _load().get(key, default)


def get_data_root():
    return Path(get("data_root", ""))


def get_dir(subdir):
    return get_data_root() / get("dirs", {}).get(subdir, subdir)
