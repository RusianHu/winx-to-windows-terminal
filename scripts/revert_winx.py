# -*- coding: utf-8 -*-
"""Restore the two managed Win+X shortcuts from this user's verified backup."""

import argparse
from pathlib import Path
import sys

from winx_common import explorer_notice, load_backup, read_entries, replace_entries, user_paths


def restore(group3, backup_dir, dry_run=False):
    originals = load_backup(backup_dir, group3)
    current = read_entries(group3, allow_missing=True)
    print(f"Restore to: {group3}")
    print(f"Backup directory: {backup_dir}")
    if dry_run:
        print("Dry run: both backup checksums and destination validated. No WinX or backup files changed.")
        return
    replace_entries(group3, originals, current)
    print("Restored and verified both original shortcuts. Backup retained.")
    explorer_notice()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate the complete backup without changing files")
    parser.add_argument("--backup-dir", type=Path, help="override the current user's persistent backup directory")
    args = parser.parse_args(argv)
    try:
        group3, default_backup = user_paths()
        restore(group3, args.backup_dir or default_backup, args.dry_run)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
