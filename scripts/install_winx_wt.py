# -*- coding: utf-8 -*-
"""Retarget the current user's existing legacy Win+X PowerShell shortcuts."""

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from winx_common import (
    ENTRY_NAMES, ensure_backup, explorer_notice, load_backup, read_entries,
    replace_entries, user_paths,
)
from winx_link import patch_hash_inplace, patch_runas_flag, read_runas_flag, read_stored_hash, winx_hash


@dataclass(frozen=True)
class Target:
    executable: str
    arguments: str
    description: str
    icon: str
    working_directory: str


def find_executable(explicit, name, candidates):
    if explicit:
        path = Path(os.path.expandvars(explicit)).expanduser()
        if not path.is_absolute() or path.suffix.lower() != ".exe" or not path.is_file():
            raise RuntimeError(f"Expected an absolute path to an existing .exe: {explicit}")
        return os.path.abspath(path)
    found = shutil.which(name)
    for candidate in ([found] if found else []) + candidates:
        if candidate and Path(candidate).is_file():
            return os.path.abspath(candidate)
    return None


def pick_target(mode="auto", terminal_path=None, pwsh_path=None):
    local = os.environ.get("LOCALAPPDATA")
    terminal_candidates = ([str(Path(local) / "Microsoft" / "WindowsApps" / "wt.exe")]
                           if local else [])
    pwsh_candidates = [str(Path(os.environ[key]) / "PowerShell" / "7" / "pwsh.exe")
                       for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
                       if os.environ.get(key)]
    if local:
        pwsh_candidates.append(str(Path(local) / "Microsoft" / "WindowsApps" / "pwsh.exe"))
    terminal = find_executable(terminal_path, "wt.exe", terminal_candidates) if mode != "pwsh" else None
    pwsh = find_executable(pwsh_path, "pwsh.exe", pwsh_candidates)
    user_profile = os.environ.get("USERPROFILE")
    working_directory = str(Path(user_profile) if user_profile else Path.home())
    if not Path(working_directory).is_dir():
        raise RuntimeError(f"User profile directory does not exist: {working_directory}")
    if mode == "terminal" and not terminal:
        raise RuntimeError("Windows Terminal not found. Install it or supply --terminal-path.")
    if mode == "pwsh" and not pwsh:
        raise RuntimeError("PowerShell 7 not found. Install it or supply --pwsh-path.")
    if terminal:
        argv = ["-w", "new", "new-tab", "-d", working_directory]
        if pwsh:
            # A command line overrides the profile's shell, including localized/custom profiles.
            argv += [pwsh, "-NoLogo"]
        description = "PowerShell 7" if pwsh else "Windows Terminal"
        # Terminal splits semicolons even inside quoted arguments. Escape its
        # command separator before applying Windows argv quoting to literal paths.
        arguments = subprocess.list2cmdline([arg.replace(";", r"\;") for arg in argv])
        return Target(terminal, arguments, description,
                      pwsh or terminal, working_directory)
    if pwsh:
        return Target(pwsh, "-NoLogo", "PowerShell 7", pwsh, working_directory)
    raise RuntimeError("Neither wt.exe nor pwsh.exe was found. Install one or supply its explicit path.")


def load_link(path):
    # Keep --help, non-Windows errors and filesystem tests independent of pywin32.
    import pythoncom
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
    )
    persist = link.QueryInterface(pythoncom.IID_IPersistFile)
    persist.Load(str(path))
    return link, persist


def self_check(path):
    stored = read_stored_hash(path)  # Missing/malformed properties must fail before any write.
    link, _ = load_link(path)
    computed = winx_hash(link.GetPath(0)[0], link.GetArguments())
    if computed != stored:
        raise RuntimeError(f"WinX hash self-check failed for {path}: "
                           f"stored=0x{stored:08X}, computed=0x{computed:08X}. No changes applied.")


def prepare_shortcut(path, target, runas):
    """Rewrite only a temporary copy, retaining the existing property storage."""
    link, persist = load_link(path)
    link.SetPath(target.executable)
    link.SetArguments(target.arguments)
    link.SetWorkingDirectory(target.working_directory)
    link.SetIconLocation(target.icon, 0)
    link.SetDescription(target.description + (" （管理员）" if runas else ""))
    persist.Save(str(path), True)
    # Release COM handles before binary writes / replacement on Windows.
    del persist, link
    patch_runas_flag(path, runas)
    saved, persist = load_link(path)
    saved_target, saved_args = saved.GetPath(0)[0], saved.GetArguments()
    if os.path.normcase(saved_target) != os.path.normcase(target.executable) or saved_args != target.arguments:
        raise RuntimeError(f"Saved shortcut target/arguments differ from the requested values: {path}")
    new_hash = winx_hash(saved_target, saved_args)
    del persist, saved
    patch_hash_inplace(path, new_hash)
    self_check(path)
    if read_runas_flag(path) != runas:
        raise RuntimeError(f"Saved shortcut administrator flag is incorrect: {path}")


def install(group3, backup_dir, target, dry_run=False):
    group3, backup_dir = Path(group3), Path(backup_dir)
    originals = read_entries(group3)
    for name in ENTRY_NAMES:
        self_check(group3 / name)
    if backup_dir.exists():
        load_backup(backup_dir, group3)
    print(f"Target: {target.executable}")
    print(f"Arguments: {target.arguments}")
    print(f"Menu label: {target.description}")
    if target.description == "Windows Terminal":
        print("PowerShell 7 was not found; Windows Terminal will use its existing default profile.")
    print(f"WinX directory: {group3}")
    print(f"Backup directory: {backup_dir}")
    if dry_run:
        print("Dry run: both original hashes and any existing backup validated. No WinX or backup files changed.")
        return
    replacements = {}
    with tempfile.TemporaryDirectory(prefix="winx-prepare-") as temporary:
        for index, name in enumerate(ENTRY_NAMES):
            path = Path(temporary) / name
            path.write_bytes(originals[name])
            prepare_shortcut(path, target, runas=bool(index))
            replacements[name] = path.read_bytes()
    # No live shortcut is touched until both copies pass validation and backup is complete.
    ensure_backup(backup_dir, group3, originals)
    replace_entries(group3, replacements, originals)
    print("Both shortcuts updated and verified; original backup retained.")
    explorer_notice()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate and show the plan without writing files")
    parser.add_argument("--target", choices=("auto", "terminal", "pwsh"), default="auto",
                        help="prefer Terminal, require Terminal, or use PowerShell 7 directly")
    parser.add_argument("--terminal-path", help="absolute path to wt.exe, including portable installations")
    parser.add_argument("--pwsh-path", help="absolute path to pwsh.exe")
    parser.add_argument("--backup-dir", type=Path, help="override the current user's persistent backup directory")
    args = parser.parse_args(argv)
    try:
        group3, default_backup = user_paths()
        try:
            import pythoncom  # noqa: F401
            from win32com.shell import shell  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("pywin32 is required: run this Python's -m pip install pywin32.") from exc
        target = pick_target(args.target, args.terminal_path, args.pwsh_path)
        install(group3, args.backup_dir or default_backup, target, args.dry_run)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
