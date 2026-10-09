"""Bounded Shell Link parsing and the Windows WinX hash algorithm.

Binary layouts: MS-SHLLINK sections 2.1--2.5.7; MS-PROPSTORE sections
2.2--2.3; MS-OLEPS section 2.15. Hashing follows riverar/hashlnk,
including its two-space salt, native Program Files directory and Windows
invariant lowercase mapping. No Windows APIs are loaded at import time.

The patch functions only replace existing fields. Call them on staged copies;
the installer is responsible for backups and publishing a complete pair.
"""

import ctypes
import os
from pathlib import Path
import struct


SALT = "do not prehash links.  this should only be done by the user."
KF_PROGRAMFILES = "{905E63B6-C1BF-494E-B29C-65B732D3D21A}"
KF_SYSTEM = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
KF_WINDOWS = "{F38BF404-1D43-42F2-9305-67DE0B28FC23}"
FMTID_BYTES = bytes.fromhex("7B2D8DFBD190344EBF606EAC09922BBF")
SHELL_LINK_CLSID = bytes.fromhex("0114020000000000C000000000000046")
STRING_PROPERTY_FMTID = bytes.fromhex("05D5CDD59C2E1B10939708002B2CF9AE")
RUN_AS_USER = 0x2000
PROPERTY_STORE_SIGNATURE = 0xA0000009


def _require(data, offset, size, end, label):
    if offset < 0 or size < 0 or end > len(data) or offset + size > end:
        raise ValueError("Truncated or out-of-bounds " + label)


def _u16(data, offset, end, label):
    _require(data, offset, 2, end, label)
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset, end, label):
    _require(data, offset, 4, end, label)
    return struct.unpack_from("<I", data, offset)[0]


def _extra_blocks(data):
    """Walk sized structures, never search unrelated bytes for a signature."""
    end = len(data)
    _require(data, 0, 76, end, "ShellLinkHeader")
    if _u32(data, 0, end, "HeaderSize") != 76 or data[4:20] != SHELL_LINK_CLSID:
        raise ValueError("Not a Shell Link (.lnk) file")
    flags = _u32(data, 20, end, "LinkFlags")
    offset = 76

    if flags & 1:  # HasLinkTargetIDList
        size = _u16(data, offset, end, "IDListSize")
        offset += 2
        id_end = offset + size
        _require(data, offset, size, end, "LinkTargetIDList")
        while True:
            item_size = _u16(data, offset, id_end, "ItemIDSize")
            if item_size == 0:
                if offset + 2 != id_end:
                    raise ValueError("Unexpected bytes after IDList terminator")
                offset = id_end
                break
            if item_size < 2:
                raise ValueError("Invalid ItemIDSize")
            _require(data, offset, item_size, id_end, "ItemID")
            offset += item_size

    if flags & 2:  # HasLinkInfo
        size = _u32(data, offset, end, "LinkInfoSize")
        _require(data, offset, max(size, 28), end, "LinkInfo")
        header_size = _u32(data, offset + 4, offset + size, "LinkInfoHeaderSize")
        if size < 28 or header_size > size or not (header_size == 28 or header_size >= 36):
            raise ValueError("Invalid LinkInfo header size")
        # Offset fields are relative to this LinkInfo, not to the whole file.
        offset_fields = [12, 16, 20, 24]
        if header_size >= 36:
            offset_fields.extend([28, 32])
        for field in offset_fields:
            relative = _u32(data, offset + field, offset + size, "LinkInfo offset")
            if relative and not header_size <= relative < size:
                raise ValueError("LinkInfo offset outside its payload")
        offset += size

    char_width = 2 if flags & 0x80 else 1
    for flag in (4, 8, 16, 32, 64):  # The five StringData fields, in order.
        if flags & flag:
            count = _u16(data, offset, end, "StringData count")
            offset += 2
            _require(data, offset, count * char_width, end, "StringData")
            offset += count * char_width

    while True:
        size = _u32(data, offset, end, "ExtraData block size")
        if size < 4:  # MS-SHLLINK permits 0, 1, 2 or 3 as the terminal value.
            if offset + 4 != end:
                raise ValueError("Unexpected bytes after ExtraData terminator")
            return
        if size < 8:
            raise ValueError("Invalid ExtraData block size")
        _require(data, offset, size, end, "ExtraData block")
        signature = _u32(data, offset + 4, offset + size, "ExtraData signature")
        yield signature, offset + 8, offset + size
        offset += size


def _property_hash_offsets(data, start, end):
    """Validate the property storage envelopes and identify the exact key."""
    storage_start = start
    formats = set()
    while True:
        size = _u32(data, storage_start, end, "property StorageSize")
        if size == 0:
            if storage_start + 4 != end:
                raise ValueError("Unexpected bytes after property store terminator")
            return
        if size < 28:
            raise ValueError("Invalid property StorageSize")
        _require(data, storage_start, size, end, "serialized property storage")
        storage_end = storage_start + size
        if _u32(data, storage_start + 4, storage_end, "property version") != 0x53505331:
            raise ValueError("Unsupported serialized property storage version")
        fmtid = data[storage_start + 8:storage_start + 24]
        if fmtid in formats:
            raise ValueError("Duplicate property storage format ID")
        formats.add(fmtid)
        offset = storage_start + 24
        property_ids = set()
        while True:
            value_size = _u32(data, offset, storage_end, "property ValueSize")
            if value_size == 0:
                if offset + 4 != storage_end:
                    raise ValueError("Unexpected bytes after property value terminator")
                break
            if value_size < 13:
                raise ValueError("Invalid property ValueSize")
            _require(data, offset, value_size, storage_end, "serialized property value")
            value_end = offset + value_size
            identity = _u32(data, offset + 4, value_end, "property identity")
            if data[offset + 8] != 0:
                raise ValueError("Invalid property reserved byte")
            typed_offset = offset + 9
            if fmtid == STRING_PROPERTY_FMTID:
                name_size = identity
                if name_size < 2 or name_size % 2:
                    raise ValueError("Invalid property name size")
                _require(data, typed_offset, name_size + 4, value_end, "named property")
                name = data[typed_offset:typed_offset + name_size]
                if name[-2:] != b"\0\0":
                    raise ValueError("Unterminated property name")
                identity = name.decode("utf-16-le")
                if "\0" in identity[:-1]:
                    raise ValueError("Embedded null in property name")
                typed_offset += name_size
            if identity in property_ids:
                raise ValueError("Duplicate property identity")
            property_ids.add(identity)
            variant_type = _u16(data, typed_offset, value_end, "property type")
            if _u16(data, typed_offset + 2, value_end, "property type padding") != 0:
                raise ValueError("Invalid typed property padding")
            if fmtid == FMTID_BYTES and identity == 2:
                if variant_type != 0x13 or typed_offset + 8 != value_end:
                    raise ValueError("WinX hash must be exactly one VT_UI4 value")
                yield typed_offset + 4
            offset = value_end
        storage_start = storage_end


def _hash_offset(data, required=True):
    offsets = []
    # Consume the entire file before any write, including data after the key.
    for signature, start, end in _extra_blocks(data):
        if signature == PROPERTY_STORE_SIGNATURE:
            offsets.extend(_property_hash_offsets(data, start, end))
    if len(offsets) > 1:
        raise ValueError("Ambiguous duplicate WinX hash properties")
    if not offsets:
        if required:
            raise ValueError("Missing WinX hash property (FMTID / pid 2)")
        return None
    return offsets[0]


def read_stored_hash(path):
    """Read pid 2 as VT_UI4, or reject missing, malformed or ambiguous data."""
    data = Path(path).read_bytes()
    return struct.unpack_from("<I", data, _hash_offset(data))[0]


def patch_hash_inplace(path, new_hash):
    """Replace only the four bytes of a verified existing WinX hash."""
    if isinstance(new_hash, bool) or not isinstance(new_hash, int) or not 0 <= new_hash <= 0xFFFFFFFF:
        raise ValueError("WinX hash must be an unsigned 32-bit integer")
    with open(path, "r+b") as stream:
        data = stream.read()
        offset = _hash_offset(data)
        old_hash = struct.unpack_from("<I", data, offset)[0]
        stream.seek(offset)
        if stream.write(struct.pack("<I", new_hash)) != 4:
            raise OSError("Incomplete WinX hash write")
    return old_hash


def patch_runas_flag(path, runas):
    """Set or clear RunAsUser while preserving every other header bit."""
    if not isinstance(runas, bool):
        raise ValueError("runas must be a boolean")
    with open(path, "r+b") as stream:
        data = stream.read()
        _hash_offset(data, required=False)
        flags = struct.unpack_from("<I", data, 20)[0]
        flags = flags | RUN_AS_USER if runas else flags & ~RUN_AS_USER
        stream.seek(20)
        if stream.write(struct.pack("<I", flags)) != 4:
            raise OSError("Incomplete RunAsUser flag write")


def read_runas_flag(path):
    """Read the elevation flag after validating the file envelopes."""
    data = Path(path).read_bytes()
    _hash_offset(data, required=False)
    return bool(struct.unpack_from("<I", data, 20)[0] & RUN_AS_USER)


def _windows_dll(name):
    if os.name != "nt":
        raise RuntimeError("WinX hash calculation requires Windows")
    return ctypes.WinDLL(name, use_last_error=True)


def _common_prefix_units(prefix, path):
    if os.name == "nt":
        api = _windows_dll("shlwapi.dll").PathCommonPrefixW
        api.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
        api.restype = ctypes.c_int
        return api(prefix, path, None)
    # Pure parsing/path tests can run on other platforms. Hashing cannot.
    matches = path[:len(prefix)].lower() == prefix.lower()
    boundary = len(path) == len(prefix) or path[len(prefix):len(prefix) + 1] == "\\"
    return len(prefix.encode("utf-16-le")) // 2 if matches and boundary else 0


def generalize_path(path, environ=None):
    """Use native known-folder prefixes, including under 32-bit Python/WOW64.

    An explicit environment mapping is supported for portable path tests.
    The returned spelling is preserved until the Windows lowercase/hash step.
    """
    if not isinstance(path, str) or not path or "\0" in path:
        raise ValueError("A nonempty target path without null characters is required")
    env = {key.lower(): value for key, value in (os.environ if environ is None else environ).items()}
    program_files = env.get("programw6432") or env.get("programfiles")
    windows = env.get("systemroot")
    if not program_files or not windows:
        raise RuntimeError("ProgramFiles/ProgramW6432 and SystemRoot must be defined")
    prefixes = [
        (program_files.rstrip("\\"), KF_PROGRAMFILES),
        (windows.rstrip("\\") + "\\System32", KF_SYSTEM),
        (windows.rstrip("\\"), KF_WINDOWS),
    ]
    for prefix, guid in prefixes:
        common_units = _common_prefix_units(prefix, path)
        prefix_units = len(prefix.encode("utf-16-le")) // 2
        if common_units >= prefix_units:
            suffix = path.encode("utf-16-le")[common_units * 2:].decode("utf-16-le")
            return guid + suffix
    return path


def _lowercase_utf16(text):
    api = _windows_dll("kernel32.dll").LCMapStringEx
    api.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_int,
        ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_ssize_t,
    ]
    api.restype = ctypes.c_int
    data = text.encode("utf-16-le")
    source = ctypes.create_string_buffer(data)
    source_pointer = ctypes.cast(source, ctypes.c_wchar_p)
    # cchSrc counts UTF-16 units, not Python code points, and excludes the NUL.
    count = len(data) // 2
    required = api("", 0x100, source_pointer, count, None, 0, None, None, 0)
    if required <= 0:
        raise ctypes.WinError(ctypes.get_last_error())
    result = ctypes.create_unicode_buffer(required)
    written = api("", 0x100, source_pointer, count, result, required, None, None, 0)
    if written <= 0:
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.string_at(result, written * 2)


def winx_hash(target, args):
    """Compute the Windows hash with native invariant Unicode casing."""
    # Fail before an environment-dependent path error on unsupported hosts.
    library = _windows_dll("shlwapi.dll")
    if args is None:
        args = ""
    if not isinstance(args, str) or "\0" in args:
        raise ValueError("Shortcut arguments must be a string without null characters")
    data = _lowercase_utf16(generalize_path(target) + args + SALT)
    api = library.HashData
    byte_pointer = ctypes.POINTER(ctypes.c_ubyte)
    api.argtypes = [byte_pointer, ctypes.c_uint32, byte_pointer, ctypes.c_uint32]
    api.restype = ctypes.c_int32
    source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    result = (ctypes.c_ubyte * 4)()
    hr = api(source, len(data), result, 4)
    if hr != 0:
        raise RuntimeError("HashData failed, HRESULT 0x%08X" % (hr & 0xFFFFFFFF))
    return int.from_bytes(bytes(result), "little")
