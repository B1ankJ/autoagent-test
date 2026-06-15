import logging
import re
from pathlib import Path

import yaml

from autoagent.config.settings import get_settings
from autoagent.profiles.schemas import Profile, parse_profile

_log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")


class _ProfileDumper(yaml.SafeDumper):
    """SafeDumper that flows short scalar-only lists like `[57, 951]`.

    PyYAML's default block style turns coordinate pairs into the very ugly
    `- - 57\\n  - 951` shape. Flow style keeps them readable while leaving
    nested object lists (actions, history) as block.
    """


def _list_representer(dumper: yaml.Dumper, data: list) -> yaml.SequenceNode:
    all_scalar = all(
        isinstance(item, (int, float, str)) and not isinstance(item, bool) for item in data
    )
    flow = all_scalar and len(data) <= 8
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_ProfileDumper.add_representer(list, _list_representer)


def _dir() -> Path:
    d = get_settings().data_root / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(name: str) -> Path:
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"invalid profile name: {name!r}")
    return _dir() / f"{name}.yaml"


def list_profile_names() -> list[str]:
    return sorted(p.stem for p in _dir().glob("*.yaml"))


def load_profile(name: str) -> Profile | None:
    path = _path(name)
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return parse_profile(data)
    except Exception as exc:
        _log.warning("skipping invalid profile %r: %s", name, exc)
        return None


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
    _path(name).write_text(
        yaml.dump(data, Dumper=_ProfileDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
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
