"""Filesystem fault-injection tests; no test opens the user's real WinX folder."""

import contextlib
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import install_winx_wt as installer
import revert_winx as revert
import winx_common as common


def snapshot(root):
    """Capture contents and directory membership, including leftover staging files."""
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in Path(root).rglob("*")
    }


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="winx-lifecycle-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.group3 = self.root / "user-one" / "Group3"
        self.group3.mkdir(parents=True)
        self.backup = self.root / "state" / "backup"
        self.originals = {name: ("original " + name).encode() for name in common.ENTRY_NAMES}
        self.replacements = {name: ("updated " + name).encode() for name in common.ENTRY_NAMES}
        self.write_entries(self.originals)
        self.target = installer.Target(
            str(self.root / "pwsh.exe"), "-NoLogo", "PowerShell 7",
            str(self.root / "pwsh.exe"), str(self.root),
        )
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def write_entries(self, entries, group3=None):
        group3 = self.group3 if group3 is None else group3
        for name, data in entries.items():
            (group3 / name).write_bytes(data)

    def prepare(self, path, target, runas):
        self.assertNotEqual(Path(path).parent, self.group3)
        Path(path).write_bytes(self.replacements[Path(path).name])

    def install_with_fake_com(self, **kwargs):
        # Only the COM transformation is replaced. Backups, staging, renames,
        # verification and recovery operate on real temporary files.
        with patch.object(installer, "self_check"), patch.object(
            installer, "prepare_shortcut", side_effect=self.prepare
        ):
            installer.install(self.group3, self.backup, self.target, **kwargs)

    def test_missing_hash_aborts_before_com_backup_or_mutation(self):
        header = bytearray(76)
        struct.pack_into("<I", header, 0, 76)
        header[4:20] = uuid.UUID("00021401-0000-0000-c000-000000000046").bytes_le
        (self.group3 / common.ENTRY_NAMES[0]).write_bytes(header + bytes(4))
        before = snapshot(self.root)
        with patch.object(installer, "load_link") as load, self.assertRaisesRegex(ValueError, "[Hh]ash"):
            installer.install(self.group3, self.backup, self.target)
        load.assert_not_called()
        self.assertEqual(snapshot(self.root), before)

    def test_second_original_validation_failure_preserves_everything(self):
        before = snapshot(self.root)
        with patch.object(installer, "self_check", side_effect=[None, RuntimeError("hash mismatch")]), patch.object(
            installer, "prepare_shortcut"
        ) as prepare, self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            installer.install(self.group3, self.backup, self.target)
        prepare.assert_not_called()
        self.assertEqual(snapshot(self.root), before)

    def test_missing_legacy_entry_fails_without_creating_backup(self):
        (self.group3 / common.ENTRY_NAMES[1]).unlink()
        before = snapshot(self.root)
        with patch.object(installer, "self_check") as check, self.assertRaisesRegex(RuntimeError, "missing"):
            installer.install(self.group3, self.backup, self.target)
        check.assert_not_called()
        self.assertEqual(snapshot(self.root), before)

    def test_filesystem_symlink_is_rejected_without_losing_link_identity(self):
        managed = self.group3 / common.ENTRY_NAMES[0]
        target = self.root / "original-target.lnk"
        managed.rename(target)
        try:
            managed.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Creating filesystem symlinks is unavailable: {exc}")
        before = snapshot(self.root)
        with patch.object(installer, "self_check") as check, self.assertRaisesRegex(
            RuntimeError, "symbolic links"
        ):
            installer.install(self.group3, self.backup, self.target)
        check.assert_not_called()
        self.assertTrue(managed.is_symlink())
        self.assertEqual(snapshot(self.root), before)

    def test_second_preparation_failure_never_touches_live_files(self):
        before = snapshot(self.root)
        prepared_paths = []

        def fail_second(path, target, runas):
            self.assertEqual(common.read_entries(self.group3), self.originals)
            prepared_paths.append(Path(path))
            self.prepare(path, target, runas)
            if runas:
                raise RuntimeError("second COM save failed")

        with patch.object(installer, "self_check"), patch.object(
            installer, "prepare_shortcut", side_effect=fail_second
        ), self.assertRaisesRegex(RuntimeError, "second COM save failed"):
            installer.install(self.group3, self.backup, self.target)
        self.assertEqual(len(prepared_paths), 2)
        self.assertTrue(all(not path.exists() for path in prepared_paths))
        self.assertEqual(snapshot(self.root), before)

    def test_second_byte_staging_failure_cleans_up_without_replacement(self):
        before = snapshot(self.group3)
        original_stage = common._stage_bytes
        calls = 0

        def fail_second(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("second staging write failed")
            return original_stage(path, data)

        with patch.object(common, "_stage_bytes", side_effect=fail_second), self.assertRaisesRegex(
            OSError, "second staging write failed"
        ):
            common.replace_entries(self.group3, self.replacements, self.originals)
        self.assertEqual(snapshot(self.group3), before)

    def test_second_replace_failure_restores_first_and_retains_backup(self):
        before = snapshot(self.group3)
        original_replace = os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("second replacement failed")
            return original_replace(source, destination)

        with patch.object(common.os, "replace", side_effect=fail_second), self.assertRaisesRegex(
            OSError, "second replacement failed"
        ):
            self.install_with_fake_com()
        self.assertEqual(calls, 3)  # First install, failed second install, first-file recovery.
        self.assertEqual(snapshot(self.group3), before)
        self.assertEqual(common.load_backup(self.backup, self.group3), self.originals)

    def test_recovery_failure_is_reported_and_original_backup_survives(self):
        original_replace = os.replace
        calls = 0

        def fail_replace_and_recovery(source, destination):
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise OSError("replacement destination locked")
            return original_replace(source, destination)

        with patch.object(common.os, "replace", side_effect=fail_replace_and_recovery), self.assertRaisesRegex(
            RuntimeError, "automatic recovery was incomplete"
        ) as raised:
            self.install_with_fake_com()
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertIn("revert_winx.py", str(raised.exception))
        self.assertIn(str(self.backup), self.output.getvalue())
        self.assertEqual(common.load_backup(self.backup, self.group3), self.originals)
        self.assertEqual((self.group3 / common.ENTRY_NAMES[0]).read_bytes(), self.replacements[common.ENTRY_NAMES[0]])
        self.assertEqual((self.group3 / common.ENTRY_NAMES[1]).read_bytes(), self.originals[common.ENTRY_NAMES[1]])
        self.assertEqual(set(path.name for path in self.group3.iterdir()), set(common.ENTRY_NAMES))

    def test_external_change_before_replacement_is_preserved(self):
        changed = dict(self.originals)
        changed[common.ENTRY_NAMES[1]] = b"changed by another process"
        self.write_entries(changed)
        before = snapshot(self.group3)
        with self.assertRaisesRegex(RuntimeError, "changed since validation"):
            common.replace_entries(self.group3, self.replacements, self.originals)
        self.assertEqual(snapshot(self.group3), before)

    def test_repeated_install_preserves_first_snapshot_and_revert_restores_it(self):
        self.install_with_fake_com()
        self.assertEqual(common.read_entries(self.group3), self.replacements)
        first_backup = snapshot(self.backup)
        self.replacements = {name: ("second update " + name).encode() for name in common.ENTRY_NAMES}
        self.install_with_fake_com()
        self.assertEqual(common.read_entries(self.group3), self.replacements)
        self.assertEqual(snapshot(self.backup), first_backup)
        revert.restore(self.group3, self.backup)
        self.assertEqual(common.read_entries(self.group3), self.originals)
        self.assertEqual(snapshot(self.backup), first_backup)

    def test_shared_backup_cannot_be_installed_or_restored_to_another_user(self):
        common.ensure_backup(self.backup, self.group3, self.originals)
        another_group = self.root / "user-two" / "Group3"
        another_group.mkdir(parents=True)
        another_originals = {name: ("other user " + name).encode() for name in common.ENTRY_NAMES}
        self.write_entries(another_originals, another_group)
        before = snapshot(self.root)
        with patch.object(installer, "self_check"), patch.object(installer, "prepare_shortcut") as prepare:
            with self.assertRaisesRegex(RuntimeError, "another WinX directory/user"):
                installer.install(another_group, self.backup, self.target)
            prepare.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "another WinX directory/user"):
            revert.restore(another_group, self.backup)
        self.assertEqual(snapshot(self.root), before)

    def test_missing_or_corrupt_backup_prevents_all_restore_writes(self):
        common.ensure_backup(self.backup, self.group3, self.originals)
        self.write_entries(self.replacements)
        second = self.backup / common.ENTRY_NAMES[1]
        for damage in ("missing", "corrupt"):
            with self.subTest(damage=damage):
                if damage == "missing":
                    second.unlink()
                else:
                    second.write_bytes(b"not the original link")
                before = snapshot(self.root)
                with self.assertRaisesRegex(RuntimeError, "[Mm]issing|checksum mismatch"):
                    revert.restore(self.group3, self.backup)
                self.assertEqual(snapshot(self.root), before)
                second.write_bytes(self.originals[common.ENTRY_NAMES[1]])

    def test_legacy_unbound_backup_is_not_silently_reused(self):
        self.backup.mkdir(parents=True)
        self.write_entries(self.originals, self.backup)
        before = snapshot(self.root)
        with patch.object(installer, "self_check"), self.assertRaisesRegex(RuntimeError, "manifest"):
            installer.install(self.group3, self.backup, self.target)
        with self.assertRaisesRegex(RuntimeError, "manifest"):
            revert.restore(self.group3, self.backup)
        self.assertEqual(snapshot(self.root), before)

    def test_restore_ignores_unmanaged_files_and_desktop_ini(self):
        common.ensure_backup(self.backup, self.group3, self.originals)
        self.write_entries(self.replacements)
        (self.group3 / "desktop.ini").write_bytes(b"current unrelated localization")
        (self.backup / "desktop.ini").write_bytes(b"stale localization")
        (self.backup / "unexpected.lnk").write_bytes(b"unmanaged backup member")
        (self.backup / "unrelated-directory").mkdir()
        revert.restore(self.group3, self.backup)
        self.assertEqual(common.read_entries(self.group3), self.originals)
        self.assertEqual((self.group3 / "desktop.ini").read_bytes(), b"current unrelated localization")
        self.assertEqual(set(path.name for path in self.group3.iterdir()), set(common.ENTRY_NAMES) | {"desktop.ini"})

    def test_install_dry_run_creates_no_files_or_directories(self):
        before = snapshot(self.root)
        with patch.object(installer, "self_check") as check, patch.object(installer, "prepare_shortcut") as prepare:
            installer.install(self.group3, self.backup, self.target, dry_run=True)
        self.assertEqual(check.call_count, 2)
        prepare.assert_not_called()
        self.assertEqual(snapshot(self.root), before)

    def test_restore_dry_run_validates_without_writing(self):
        common.ensure_backup(self.backup, self.group3, self.originals)
        self.write_entries(self.replacements)
        before = snapshot(self.root)
        revert.restore(self.group3, self.backup, dry_run=True)
        self.assertEqual(snapshot(self.root), before)

    def test_restore_recreates_missing_managed_shortcuts(self):
        common.ensure_backup(self.backup, self.group3, self.originals)
        for name in common.ENTRY_NAMES:
            (self.group3 / name).unlink()
        revert.restore(self.group3, self.backup)
        self.assertEqual(common.read_entries(self.group3), self.originals)

    def test_failed_restore_returns_previously_missing_file_to_missing(self):
        common.ensure_backup(self.backup, self.group3, self.originals)
        self.write_entries(self.replacements)
        (self.group3 / common.ENTRY_NAMES[0]).unlink()
        before = snapshot(self.group3)
        original_replace = os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("second restoration failed")
            return original_replace(source, destination)

        with patch.object(common.os, "replace", side_effect=fail_second), self.assertRaisesRegex(
            OSError, "second restoration failed"
        ):
            revert.restore(self.group3, self.backup)
        self.assertEqual(snapshot(self.group3), before)
        self.assertEqual(common.load_backup(self.backup, self.group3), self.originals)


class TargetDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="winx-target-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "用户 Home"
        self.home.mkdir()
        self.bin = self.root / "Portable Tools"
        self.bin.mkdir()
        environment = patch.dict(os.environ, {
            "USERPROFILE": str(self.home), "PATH": str(self.bin), "PATHEXT": ".EXE",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def executable(self, name, parent=None):
        parent = self.bin if parent is None else parent
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / name
        path.write_bytes(b"test executable placeholder; never executed")
        path.chmod(0o700)
        return path

    def test_path_only_powershell_is_found_without_fixed_install_directory(self):
        pwsh = self.executable("pwsh.exe")
        target = installer.pick_target()
        self.assertEqual(target.executable, str(pwsh))
        self.assertEqual(target.description, "PowerShell 7")

    def test_terminal_without_powershell_has_truthful_label_and_explicit_new_tab(self):
        terminal = self.executable("wt.exe")
        target = installer.pick_target()
        self.assertEqual(target.executable, str(terminal))
        self.assertEqual(target.description, "Windows Terminal")
        self.assertIn("-w new", target.arguments)
        self.assertIn("new-tab", target.arguments)
        self.assertNotIn("pwsh.exe", target.arguments)
        self.assertEqual(target.icon, str(terminal))

    def test_terminal_pins_powershell_executable_independently_of_default_profile(self):
        terminal = self.executable("wt.exe")
        pwsh = self.executable("pwsh.exe")
        target = installer.pick_target()
        self.assertEqual(target.executable, str(terminal))
        self.assertEqual(target.description, "PowerShell 7")
        self.assertIn('"' + str(pwsh) + '"', target.arguments)
        self.assertIn('"' + str(self.home) + '"', target.arguments)
        self.assertIn("-w new", target.arguments)
        self.assertIn("new-tab", target.arguments)
        self.assertEqual(target.icon, str(pwsh))
        self.assertEqual(target.working_directory, str(self.home))

    def test_explicit_paths_take_priority_over_path_discovery(self):
        self.executable("wt.exe")
        self.executable("pwsh.exe")
        explicit = self.root / "Selected Tools"
        terminal = self.executable("wt.exe", explicit)
        pwsh = self.executable("pwsh.exe", explicit)
        target = installer.pick_target(terminal_path=str(terminal), pwsh_path=str(pwsh))
        self.assertEqual(target.executable, str(terminal))
        self.assertIn('"' + str(pwsh) + '"', target.arguments)

    def test_semicolons_in_shell_and_home_paths_remain_literal_terminal_arguments(self):
        terminal = self.executable("wt.exe")
        pwsh = self.executable("pwsh.exe", self.root / "Power; Shell")
        home = self.root / "用户; Home"
        home.mkdir()
        with patch.dict(os.environ, {"USERPROFILE": str(home)}):
            target = installer.pick_target(pwsh_path=str(pwsh))
        self.assertEqual(target.executable, str(terminal))
        self.assertEqual(target.working_directory, str(home))
        # Terminal parses semicolons even inside quoted argv strings, so normal
        # Windows command-line quoting by itself is insufficient for these paths.
        for literal_path in (home, pwsh):
            escaped = str(literal_path).replace(";", chr(92) + ";")
            self.assertIn('"' + escaped + '"', target.arguments)
        separators = [index for index, char in enumerate(target.arguments) if char == ";"]
        self.assertEqual(len(separators), 2)
        self.assertTrue(all(index > 0 and target.arguments[index - 1] == chr(92) for index in separators))

    def test_invalid_explicit_path_is_not_silently_replaced_by_path_candidate(self):
        self.executable("wt.exe")
        for explicit in ("relative-wt.exe", str(self.root / "missing.exe"), str(self.home)):
            with self.subTest(explicit=explicit), self.assertRaisesRegex(RuntimeError, "absolute path"):
                installer.pick_target(terminal_path=explicit)

    def test_powershell_mode_uses_powershell_even_when_terminal_exists(self):
        self.executable("wt.exe")
        pwsh = self.executable("pwsh.exe")
        target = installer.pick_target(mode="pwsh")
        self.assertEqual(target.executable, str(pwsh))
        self.assertNotIn("new-tab", target.arguments)

    def test_required_target_modes_fail_when_only_other_program_exists(self):
        pwsh = self.executable("pwsh.exe")
        with self.assertRaisesRegex(RuntimeError, "Windows Terminal not found"):
            installer.pick_target(mode="terminal")
        pwsh.unlink()
        self.executable("wt.exe")
        with self.assertRaisesRegex(RuntimeError, "PowerShell 7 not found"):
            installer.pick_target(mode="pwsh")

    def test_programfiles_environment_supports_non_default_location(self):
        programfiles = self.root / "Custom Program Files"
        pwsh = self.executable("pwsh.exe", programfiles / "PowerShell" / "7")
        with patch.dict(os.environ, {"ProgramFiles": str(programfiles)}):
            target = installer.pick_target()
        self.assertEqual(target.executable, str(pwsh))

    def test_current_user_windowsapps_alias_is_a_fallback(self):
        local = self.root / "Local App Data"
        terminal = self.executable("wt.exe", local / "Microsoft" / "WindowsApps")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            target = installer.pick_target()
        self.assertEqual(target.executable, str(terminal))

    def test_no_installed_target_reports_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "Neither wt.exe nor pwsh.exe"):
            installer.pick_target()


if __name__ == "__main__":
    unittest.main()
