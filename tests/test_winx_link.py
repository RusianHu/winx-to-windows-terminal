"""Synthetic format fixtures; these tests never access the user's WinX menu."""

import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import winx_link as link


def integer_property(pid, value, variant=0x13):
    return struct.pack("<IIBHHI", 17, pid, 0, variant, 0, value)


def storage(properties, fmtid=link.FMTID_BYTES):
    values = b"".join(properties) + bytes(4)
    return struct.pack("<II", 24 + len(values), 0x53505331) + fmtid + values


def property_block(*storages):
    payload = b"".join(storages) + bytes(4)
    return struct.pack("<II", 8 + len(payload), link.PROPERTY_STORE_SIGNATURE) + payload


def shortcut(*blocks, flags=0, variable=b""):
    header = bytearray(76)
    struct.pack_into("<I", header, 0, 76)
    header[4:20] = link.SHELL_LINK_CLSID
    struct.pack_into("<I", header, 20, flags)
    return bytes(header) + variable + b"".join(blocks) + bytes(4)


def hashed_shortcut(value=0x12345678, **kwargs):
    return shortcut(property_block(storage([integer_property(2, value)])), **kwargs)


class LinkBinaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "staged.lnk"

    def write(self, data):
        self.path.write_bytes(data)
        return self.path

    def assert_rejected_without_write(self, data):
        self.write(data)
        with self.assertRaises(ValueError):
            link.patch_hash_inplace(self.path, 0xABCDEF12)
        self.assertEqual(self.path.read_bytes(), data)

    def test_patch_targets_pid_two_and_changes_only_four_bytes(self):
        original = shortcut(property_block(storage([
            integer_property(1, 0x11111111), integer_property(2, 0x12345678),
            integer_property(3, 0x33333333),
        ])))
        self.write(original)
        self.assertEqual(link.read_stored_hash(self.path), 0x12345678)
        self.assertEqual(link.patch_hash_inplace(self.path, 0xAABBCCDD), 0x12345678)
        self.assertEqual(self.path.read_bytes(), original.replace(
            struct.pack("<I", 0x12345678), struct.pack("<I", 0xAABBCCDD)))

    def test_hash_after_many_properties_has_no_search_window_limit(self):
        properties = [integer_property(pid, pid) for pid in range(10, 20)]
        properties.append(integer_property(2, 0xFEEDFACE))
        self.write(shortcut(property_block(storage(properties))))
        self.assertEqual(link.read_stored_hash(self.path), 0xFEEDFACE)

    def test_guid_and_type_decoys_outside_property_store_are_ignored(self):
        decoy = link.FMTID_BYTES + b"\x00\x13\x00\x00\x00" + bytes(4)
        # A counted ANSI description and an unrelated extra block both carry it.
        variable = struct.pack("<H", len(decoy)) + decoy
        unrelated = struct.pack("<II", 8 + len(decoy), 0xA00000FE) + decoy
        self.write(shortcut(unrelated, property_block(storage([
            integer_property(2, 0x12345678),
        ])), flags=4, variable=variable))
        self.assertEqual(link.read_stored_hash(self.path), 0x12345678)

    def test_valid_optional_sections_are_skipped_by_their_lengths(self):
        idlist = struct.pack("<HH", 2, 0)
        info = struct.pack("<IIIIIII", 29, 28, 0, 0, 0, 0, 28) + b"\0"
        strings = b""
        for text in ("name", "relative", "working", "args", "icon"):
            encoded = text.encode("utf-16-le")
            strings += struct.pack("<H", len(encoded) // 2) + encoded
        self.write(hashed_shortcut(flags=0xFF, variable=idlist + info + strings))
        self.assertEqual(link.read_stored_hash(self.path), 0x12345678)

    def test_named_property_storage_does_not_confuse_integer_pid(self):
        name = "metadata\0".encode("utf-16-le")
        value = struct.pack("<IIB", 17 + len(name), len(name), 0)
        value += name + struct.pack("<HHI", 0x13, 0, 99)
        self.write(shortcut(property_block(
            storage([value], link.STRING_PROPERTY_FMTID),
            storage([integer_property(2, 42)]),
        )))
        self.assertEqual(link.read_stored_hash(self.path), 42)

    def test_unrelated_format_with_pid_two_is_ignored(self):
        self.write(shortcut(property_block(
            storage([integer_property(2, 8)], bytes.fromhex("11" * 16)),
            storage([integer_property(2, 42)]),
        )))
        self.assertEqual(link.read_stored_hash(self.path), 42)

    def test_missing_hash_is_an_error(self):
        self.assert_rejected_without_write(shortcut())
        self.assert_rejected_without_write(shortcut(property_block(storage([
            integer_property(1, 2),
        ]))))

    def test_wrong_variant_is_rejected(self):
        self.assert_rejected_without_write(shortcut(property_block(storage([
            integer_property(2, 42, variant=3),
        ]))))

    def test_wrong_ui4_size_is_rejected(self):
        value = struct.pack("<IIBHH", 16, 2, 0, 0x13, 0) + bytes(3)
        self.assert_rejected_without_write(shortcut(property_block(storage([value]))))

    def test_duplicate_property_identity_is_rejected(self):
        self.assert_rejected_without_write(shortcut(property_block(storage([
            integer_property(2, 1), integer_property(2, 2),
        ]))))

    def test_duplicate_format_is_rejected(self):
        one = storage([integer_property(2, 42)])
        self.assert_rejected_without_write(shortcut(property_block(one, one)))

    def test_duplicate_key_in_separate_extra_blocks_is_rejected(self):
        block = property_block(storage([integer_property(2, 42)]))
        self.assert_rejected_without_write(shortcut(block, block))

    def test_bad_reserved_byte_and_variant_padding_are_rejected(self):
        for index in (8, 11, 12):
            with self.subTest(index=index):
                prop = bytearray(integer_property(2, 42))
                prop[index] = 1
                self.assert_rejected_without_write(shortcut(property_block(storage([prop]))))

    def test_bad_storage_version_is_rejected(self):
        prop_storage = bytearray(storage([integer_property(2, 42)]))
        struct.pack_into("<I", prop_storage, 4, 0)
        self.assert_rejected_without_write(shortcut(property_block(prop_storage)))

    def test_each_truncated_prefix_is_rejected_without_a_write(self):
        original = hashed_shortcut()
        for length in range(len(original)):
            with self.subTest(length=length):
                self.assert_rejected_without_write(original[:length])

    def test_oversized_nested_lengths_are_rejected(self):
        original = hashed_shortcut()
        # ExtraData block, SerializedPropertyStorage, SerializedPropertyValue.
        for offset in (76, 84, 108):
            with self.subTest(offset=offset):
                broken = bytearray(original)
                struct.pack_into("<I", broken, offset, 0xFFFFFFFF)
                self.assert_rejected_without_write(broken)

    def test_malformed_tail_is_rejected_even_after_a_valid_hash(self):
        original = hashed_shortcut()
        self.assert_rejected_without_write(original + b"extra")
        self.assert_rejected_without_write(original[:-4] + struct.pack("<I", 5) + bytes(5))

    def test_missing_nested_terminators_are_rejected(self):
        original = bytearray(hashed_shortcut())
        # The final three DWORDs terminate values, storages and extra data.
        for delta in (12, 8):
            with self.subTest(delta=delta):
                broken = bytearray(original)
                struct.pack_into("<I", broken, len(broken) - delta, 1)
                self.assert_rejected_without_write(broken)

    def test_invalid_hash_argument_never_changes_the_file(self):
        original = hashed_shortcut()
        for value in (-1, 0x100000000, True, "42"):
            with self.subTest(value=value):
                self.write(original)
                with self.assertRaises(ValueError):
                    link.patch_hash_inplace(self.path, value)
                self.assertEqual(self.path.read_bytes(), original)

    def test_runas_sets_and_clears_only_its_bit(self):
        original = hashed_shortcut(flags=0x80000)
        self.write(original)
        link.patch_runas_flag(self.path, True)
        expected = bytearray(original)
        expected[21] |= 0x20
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertTrue(link.read_runas_flag(self.path))
        link.patch_runas_flag(self.path, False)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(link.read_runas_flag(self.path))

    def test_runas_rejects_non_links_and_invalid_body(self):
        for original in (bytes(100), hashed_shortcut()[:-1]):
            with self.subTest(length=len(original)):
                self.write(original)
                with self.assertRaises(ValueError):
                    link.patch_runas_flag(self.path, True)
                self.assertEqual(self.path.read_bytes(), original)


class GeneralizePathTests(unittest.TestCase):
    ENV = {"ProgramFiles": "C:\\Program Files", "SystemRoot": "C:\\Windows"}

    def test_native_program_files_under_wow64(self):
        env = dict(self.ENV, ProgramFiles="C:\\Program Files (x86)",
                   ProgramW6432="C:\\Program Files")
        path = "C:\\Program Files\\PowerShell\\7\\pwsh.exe"
        self.assertEqual(link.generalize_path(path, env),
                         link.KF_PROGRAMFILES + "\\PowerShell\\7\\pwsh.exe")

    def test_folder_component_boundaries(self):
        for path in ("C:\\Program Files (x86)\\pwsh.exe", "C:\\Windows.old\\cmd.exe"):
            with self.subTest(path=path):
                self.assertEqual(link.generalize_path(path, self.ENV), path)

    def test_system_directory_is_matched_before_windows(self):
        self.assertEqual(link.generalize_path("c:\\WINDOWS\\System32\\cmd.exe", self.ENV),
                         link.KF_SYSTEM + "\\cmd.exe")
        self.assertEqual(link.generalize_path("C:\\Windows\\System32.old\\cmd.exe", self.ENV),
                         link.KF_WINDOWS + "\\System32.old\\cmd.exe")

    def test_environment_keys_are_case_insensitive(self):
        self.assertEqual(link.generalize_path("C:\\Windows\\cmd.exe", {
            "PROGRAMFILES": "C:\\Program Files", "SYSTEMROOT": "C:\\Windows",
        }), link.KF_WINDOWS + "\\cmd.exe")

    def test_non_bmp_folder_prefix_preserves_suffix(self):
        env = {"ProgramFiles": "C:\\Programs\U0001F600", "SystemRoot": "C:\\Windows"}
        self.assertEqual(link.generalize_path("C:\\Programs\U0001F600\\pwsh.exe", env),
                         link.KF_PROGRAMFILES + "\\pwsh.exe")

    def test_unresolved_environment_and_invalid_targets_are_rejected(self):
        with self.assertRaises(RuntimeError):
            link.generalize_path("C:\\Windows\\cmd.exe", {})
        for path in ("", "C:\\bad\0path", None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                link.generalize_path(path, self.ENV)

    @unittest.skipIf(os.name == "nt", "Non-Windows guard")
    def test_hash_does_not_silently_emulate_windows_on_other_hosts(self):
        with self.assertRaisesRegex(RuntimeError, "requires Windows"):
            link.winx_hash("C:\\Windows\\cmd.exe", "")


@unittest.skipUnless(os.name == "nt", "Requires Windows COM and pywin32")
class WindowsComIntegrationTests(unittest.TestCase):
    def test_prepare_real_com_shortcut_in_temporary_directory(self):
        import pythoncom
        from win32com.shell import shell
        from install_winx_wt import Target, load_link, prepare_shortcut, self_check

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temporary-test.lnk"
            executable = str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe")
            original = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLink,
            )
            persist = original.QueryInterface(pythoncom.IID_IPersistFile)
            original.SetPath(executable)
            original.SetArguments("/d /c echo before")
            persist.Save(str(path), True)
            del persist, original

            saved, persist = load_link(path)
            old_hash = link.winx_hash(saved.GetPath(0)[0], saved.GetArguments())
            del persist, saved
            data = path.read_bytes()
            winx_storage = storage([integer_property(2, old_hash)])
            blocks = list(link._extra_blocks(data))
            # Fixtures only: add the missing property to this new temporary link.
            # Existing WinX links are never synthesized or extended by production code.
            for signature, start, end in blocks:
                if signature == link.PROPERTY_STORE_SIGNATURE:
                    self.assertEqual(data[end - 4:end], bytes(4))
                    payload = data[start:end - 4] + winx_storage + bytes(4)
                    block = struct.pack("<II", 8 + len(payload), signature) + payload
                    data = data[:start - 8] + block + data[end:]
                    break
            else:
                data = data[:-4] + property_block(winx_storage) + data[-4:]
            path.write_bytes(data)
            self_check(path)

            arguments = '/d /c echo "after \U0001F600"'
            target = Target(executable, arguments, "Temporary COM test", executable, directory)
            for runas in (True, False):
                with self.subTest(runas=runas):
                    prepare_shortcut(path, target, runas)
                    self_check(path)
                    saved, persist = load_link(path)
                    self.assertEqual(saved.GetArguments(), arguments)
                    self.assertEqual(os.path.normcase(saved.GetPath(0)[0]),
                                     os.path.normcase(executable))
                    del persist, saved
                    self.assertEqual(link.read_runas_flag(path), runas)
                    self.assertEqual(link.read_stored_hash(path), link.winx_hash(executable, arguments))


if __name__ == "__main__":
    unittest.main()
