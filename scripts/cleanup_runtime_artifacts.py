from __future__ import annotations

import argparse
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class CleanupEntry:
    path: Path
    kind: str


def _cutoff(days: int, now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current - timedelta(days=days)


def _is_stale(path: Path, *, cutoff: datetime) -> bool:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < cutoff


def _is_under_repo(path: Path, repo_root: Path) -> bool:
    resolved = path.resolve()
    root = repo_root.resolve()
    return resolved == root or root in resolved.parents


def _cleanup_sort_key(entry: CleanupEntry) -> tuple[int, int, str]:
    kind_order = {
        "profile_builder_session": 0,
        "logs_file": 1,
        "logs_dir": 2,
    }
    depth = len(entry.path.resolve().parts)
    return (kind_order.get(entry.kind, 99), -depth, str(entry.path))


def _iter_logs_dirs(repo_root: Path) -> list[Path]:
    return sorted(path for path in repo_root.rglob("*") if path.is_dir() and path.name == "logs")


def collect_cleanup_entries(
    repo_root: Path,
    days: int,
    now: datetime | None = None,
) -> list[CleanupEntry]:
    root = repo_root.resolve()
    cutoff = _cutoff(days, now)
    entries: set[CleanupEntry] = set()

    for logs_dir in _iter_logs_dirs(root):
        for path in sorted(logs_dir.rglob("*")):
            if not _is_under_repo(path, root):
                continue
            if path.is_file() and _is_stale(path, cutoff=cutoff):
                entries.add(CleanupEntry(path, "logs_file"))
        for path in sorted(
            (
                candidate
                for candidate in logs_dir.rglob("*")
                if candidate.is_dir() and candidate != logs_dir
            ),
            key=lambda candidate: len(candidate.parts),
            reverse=True,
        ):
            if not _is_under_repo(path, root):
                continue
            children = list(path.iterdir())
            if children and all(
                CleanupEntry(child, "logs_file") in entries
                or CleanupEntry(child, "logs_dir") in entries
                for child in children
            ):
                entries.add(CleanupEntry(path, "logs_dir"))

    profile_builder_root = root / "data" / "profile_builder"
    if profile_builder_root.exists():
        for session_dir in sorted(path for path in profile_builder_root.iterdir() if path.is_dir()):
            if _is_under_repo(session_dir, root) and _is_stale(session_dir, cutoff=cutoff):
                entries.add(CleanupEntry(session_dir, "profile_builder_session"))

    return sorted(entries, key=_cleanup_sort_key)


def apply_cleanup(entries: list[CleanupEntry], repo_root: Path) -> list[CleanupEntry]:
    root = repo_root.resolve()
    deleted: list[CleanupEntry] = []
    for entry in sorted(entries, key=_cleanup_sort_key):
        resolved = entry.path.resolve()
        if not _is_under_repo(resolved, root):
            raise ValueError(f"path outside repository root: {resolved}")
        if entry.kind == "profile_builder_session":
            if resolved.exists():
                shutil.rmtree(resolved)
                deleted.append(entry)
        elif entry.kind == "logs_file":
            if resolved.exists():
                resolved.unlink()
                deleted.append(entry)
        elif entry.kind == "logs_dir":
            if resolved.exists():
                try:
                    resolved.rmdir()
                except OSError:
                    continue
                deleted.append(entry)
    return deleted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview or delete old runtime artifacts.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--days",
        type=int,
        help="Delete artifacts older than N days.",
    )
    target.add_argument(
        "--all",
        action="store_true",
        help="Delete all cleanup targets under logs/ and data/profile_builder/.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview matching artifacts.")
    mode.add_argument("--apply", action="store_true", help="Delete matching artifacts.")
    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.days is not None and args.days <= 0:
        raise ValueError("--days must be a positive integer")
    if args.all and not args.apply:
        parser.error("--all requires --apply")


def collect_all_cleanup_entries(repo_root: Path) -> list[CleanupEntry]:
    root = repo_root.resolve()
    entries: set[CleanupEntry] = set()

    for logs_dir in _iter_logs_dirs(root):
        for path in sorted(logs_dir.rglob("*")):
            if not _is_under_repo(path, root):
                continue
            if path.is_file():
                entries.add(CleanupEntry(path, "logs_file"))
        for path in sorted(
            (
                candidate
                for candidate in logs_dir.rglob("*")
                if candidate.is_dir() and candidate != logs_dir
            ),
            key=lambda candidate: len(candidate.parts),
            reverse=True,
        ):
            if _is_under_repo(path, root):
                entries.add(CleanupEntry(path, "logs_dir"))

    profile_builder_root = root / "data" / "profile_builder"
    if profile_builder_root.exists():
        for session_dir in sorted(path for path in profile_builder_root.iterdir() if path.is_dir()):
            if _is_under_repo(session_dir, root):
                entries.add(CleanupEntry(session_dir, "profile_builder_session"))

    return sorted(entries, key=_cleanup_sort_key)


def _relative_display(path: Path, repo_root: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve()))


def main(argv: Sequence[str] | None = None, repo_root: Path | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(args, parser)
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    entries = (
        collect_all_cleanup_entries(repo_root=root)
        if args.all
        else collect_cleanup_entries(repo_root=root, days=args.days)
    )
    if args.apply:
        deleted = apply_cleanup(entries, repo_root=root)
        print(f"apply: deleted {len(deleted)} entries")
        for entry in deleted:
            print(f"{entry.kind} { _relative_display(entry.path, root) }")
        return 0

    print(f"dry-run: matched {len(entries)} entries")
    for entry in entries:
        print(f"{entry.kind} { _relative_display(entry.path, root) }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
