from pathlib import Path
import yaml

LANDMARK = "config.yml"


def find_repo_root():
    cwd = Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        if (parent / LANDMARK).exists():
            return parent
    return cwd


def load_config():
    repo_root = find_repo_root()
    cfg = repo_root / LANDMARK
    if cfg.exists():
        with open(cfg) as f:
            return yaml.safe_load(f) or {}
    return {}


def get_data_root():
    cfg = load_config()
    return Path(cfg.get("data_root", ""))
