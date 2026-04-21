from pathlib import Path

import yaml

from autoagent.config.settings import get_settings
from autoagent.profiles.schemas import Profile, parse_profile


def _dir() -> Path:
    d = get_settings().data_root / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(name: str) -> Path:
    if "/" in name or ".." in name or name == "":
        raise ValueError(f"invalid profile name: {name!r}")
    return _dir() / f"{name}.yaml"


def list_profile_names() -> list[str]:
    return sorted(p.stem for p in _dir().glob("*.yaml"))


def load_profile(name: str) -> Profile | None:
    path = _path(name)
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_profile(data)


def load_profile_yaml(name: str) -> str | None:
    path = _path(name)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def save_profile_yaml(name: str, yaml_text: str) -> Profile:
    # Validate before writing
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ValueError("YAML must be a mapping")
    # Enforce name consistency
    data["name"] = name
    profile = parse_profile(data)
    _path(name).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return profile


def delete_profile(name: str) -> bool:
    path = _path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def validate_yaml(yaml_text: str) -> tuple[bool, str | None]:
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return False, "YAML root must be a mapping"
        parse_profile(data)
        return True, None
    except Exception as e:
        return False, str(e)
