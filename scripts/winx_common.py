"""Shared, filesystem-only backup and replacement operations."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


ENTRY_NAMES = (
    "01a - Windows PowerShell.lnk",
    "02a - Windows PowerShell.lnk",
)


def user_paths():
    """Resolve state for the user running native Windows Python, never the skill."""
    if os.name != "nt":
        raise RuntimeError("Run this script with native Windows Python, not Linux, macOS or WSL Python.")
    local = os.environ.get("LOCALAPPDATA")
    if not local or not Path(local).is_absolute():
        raise RuntimeError("LOCALAPPDATA must point to the current Windows user's local application data.")
    root = Path(local)
    return (root / "Microsoft" / "Windows" / "WinX" / "Group3",
            root / "winx-to-windows-terminal" / "backup")


def path_identity(path):
    return os.path.normcase(str(Path(path).resolve()))


def read_entries(group3, allow_missing=False):
    group3 = Path(group3)
    if not group3.is_dir():
        raise RuntimeError(f"Legacy WinX Group3 directory not found: {group3}")
    if any((group3 / name).is_symlink() for name in ENTRY_NAMES):
        raise RuntimeError("Managed shortcuts must be regular .lnk files, not filesystem symbolic links.")
    missing = [name for name in ENTRY_NAMES if not (group3 / name).is_file()]
    if missing and not allow_missing:
        raise RuntimeError(
            "Required legacy PowerShell menu entries are missing: " + ", ".join(missing)
            + ". Use the native Terminal settings on systems that already have Terminal entries; "
            "this script does not create or replace CMD/native Terminal entries."
        )
    result = {}
    for name in ENTRY_NAMES:
        path = group3 / name
        try:
            result[name] = path.read_bytes()
        except FileNotFoundError:
            if not allow_missing:
                raise
            result[name] = None
    return result


def load_backup(backup_dir, group3):
    """Validate the entire manifest and both files before returning any bytes."""
    backup_dir = Path(backup_dir)
    try:
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Missing or invalid backup manifest at {backup_dir}. "
            "Do not reuse legacy scripts/backup or incomplete backups without checking their origin."
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise RuntimeError("Unsupported backup manifest version.")
    if manifest.get("group3") != path_identity(group3):
        raise RuntimeError("This backup belongs to another WinX directory/user; refusing to restore or reuse it.")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(ENTRY_NAMES):
        raise RuntimeError("Backup must describe exactly the two managed PowerShell shortcuts.")
    originals = {}
    for name in ENTRY_NAMES:
        path = backup_dir / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Backup shortcut missing or not a regular file: {path}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != files[name]:
            raise RuntimeError(f"Backup checksum mismatch: {path}")
        originals[name] = data
    return originals


def ensure_backup(backup_dir, group3, originals):
    """Keep the first complete, directory-bound snapshot; never overwrite it."""
    backup_dir = Path(backup_dir)
    if backup_dir.exists():
        load_backup(backup_dir, group3)
        return
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".winx-backup-", dir=backup_dir.parent))
    try:
        for name in ENTRY_NAMES:
            (temporary / name).write_bytes(originals[name])
        manifest = {
            "version": 1,
            "group3": path_identity(group3),
            "files": {name: hashlib.sha256(originals[name]).hexdigest() for name in ENTRY_NAMES},
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        # Rename only a complete snapshot into place. An existing nonempty backup wins.
        temporary.rename(backup_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    load_backup(backup_dir, group3)


def _stage_bytes(path, data):
    fd, name = tempfile.mkstemp(prefix=".winx-", suffix=".tmp", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def replace_entries(group3, replacements, before):
    """Stage both files, then replace; compensate for ordinary partial failures.

    Individual renames are atomic. The pair cannot be atomic across process death
    or power loss, so the persistent backup remains the recovery source.
    """
    group3 = Path(group3)
    if set(replacements) != set(ENTRY_NAMES) or set(before) != set(ENTRY_NAMES):
        raise ValueError("Replacement requires exactly the two managed shortcuts.")
    staged = {}
    changed = []
    try:
        for name in ENTRY_NAMES:
            staged[name] = _stage_bytes(group3 / name, replacements[name])
        if read_entries(group3, allow_missing=True) != before:
            raise RuntimeError("WinX shortcuts changed since validation; rerun after checking the files.")
        for name in ENTRY_NAMES:
            destination = group3 / name
            if read_entries(group3, allow_missing=True)[name] != before[name]:
                raise RuntimeError(f"Shortcut changed concurrently: {destination}")
            os.replace(staged[name], destination)
            changed.append(name)
        if read_entries(group3) != replacements:
            raise RuntimeError("Shortcut verification failed after replacement.")
    except BaseException as exc:
        failures = []
        for name in reversed(changed):
            destination = group3 / name
            recovery = None
            try:
                if destination.read_bytes() != replacements[name]:
                    raise RuntimeError("file changed concurrently; preserving the external change")
                if before[name] is None:
                    destination.unlink()
                else:
                    recovery = _stage_bytes(destination, before[name])
                    os.replace(recovery, destination)
            except Exception as recovery_error:
                failures.append(f"{name}: {recovery_error}")
            finally:
                if recovery is not None:
                    recovery.unlink(missing_ok=True)
        if failures:
            raise RuntimeError(
                "Replacement failed and automatic recovery was incomplete. "
                "Use revert_winx.py with the printed backup directory. Details: " + "; ".join(failures)
            ) from exc
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def explorer_notice():
    print("After saving any Explorer file operations, restart Windows Explorer for this user "
          "from Task Manager, or sign out and back in. Then verify both Win+X entries.")
