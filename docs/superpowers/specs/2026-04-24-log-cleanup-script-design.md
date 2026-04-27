# Log Cleanup Script Design

## Goal

Provide a repository-local cleanup script that removes old runtime artifacts by retention days.

## Scope

The script will:

- recursively find every directory named `logs` under the current repository root
- clean old files and directories under those `logs/` directories
- clean old session directories under `data/profile_builder/`
- support a `--days N` retention threshold based on modification time
- default to `--dry-run`
- support explicit deletion only with a confirm flag

## Non-Goals

- deleting source code, docs, profiles, or database files
- cleaning directories outside the repository root
- adding background scheduling or automatic cleanup

## Behavior

- age rule: delete entries whose mtime is older than `N` days
- `logs/`: remove old files first, then remove empty old directories
- `data/profile_builder/`: remove whole old session directories as units
- output: print what would be deleted in dry-run mode and what was deleted in apply mode

## Interface

Proposed command:

```bash
python3.11 scripts/cleanup_runtime_artifacts.py --days 7 --dry-run
python3.11 scripts/cleanup_runtime_artifacts.py --days 7 --apply
```

Flags:

- `--days`: required positive integer
- `--dry-run`: preview only, default behavior
- `--apply`: actually delete matched artifacts

## Safety

- resolve all target paths and ensure they remain under repo root
- only operate on discovered `logs/` directories and `data/profile_builder/`
- never delete the root target directories themselves, only their contents

## Tests

- unit test for dry-run selection by age
- unit test for apply mode deletion
- unit test that repo-external paths are ignored
- unit test that `data/profile_builder/<session>` is deleted as a whole unit
