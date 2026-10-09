# -*- coding: utf-8 -*-
"""
install_winx_wt.py — 把 Win+X 菜单的 PowerShell 项切换为新版终端。

自动选择目标：优先 wt.exe（Windows Terminal），否则 pwsh.exe（PowerShell 7）。
自动备份、改写快捷方式、补写 RunAsUser 标志、重算并原位写入 TWINUI WinX hash。

依赖: pip install pywin32
用法: python install_winx_wt.py
回滚: python revert_winx.py （或把 backup/ 拷回 Group3 并重启 Explorer）
"""
import os
import shutil
import ctypes

import pythoncom
from win32com.shell import shell

GROUP3 = os.path.expandvars("%LOCALAPPDATA%" + chr(92) + r"Microsoft\Windows\WinX\Group3")
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup")

WT_ALIAS = os.path.expandvars("%LOCALAPPDATA%" + chr(92) + r"Microsoft\WindowsApps\wt.exe")
PWSH = r"C:\Program Files\PowerShell\7\pwsh.exe"

ADMIN_SUFFIX = chr(0xFF08) + chr(31649) + chr(29702) + chr(21592) + chr(0xFF09)  # （管理员）

SALT = "do not prehash links.  this should only be done by the user."

# StringFromGUID2 格式：大写带花括号
KF_PROGRAMFILES = "{905E63B6-C1BF-494E-B29C-65B732D3D21A}"
KF_SYSTEM = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
KF_WINDOWS = "{F38BF404-1D43-42F2-9305-67DE0B28FC23}"

# PKEY_WINX_HASH fmtid {FB8D2D7B-90D1-4E34-BF60-6EAC09922BBF} 的线格式字节
FMTID_BYTES = bytes.fromhex("7B2D8DFBD190344EBF606EAC09922BBF")
VT_UI4_MARKER = b"\x00\x13\x00\x00\x00"  # Reserved(1) + Type(2, VT_UI4) + Padding(2)


def pick_target():
    """优先 Windows Terminal，退回 PowerShell 7。"""
    if os.path.isfile(WT_ALIAS):
        return WT_ALIAS, "Windows Terminal + PowerShell 7"
    if os.path.isfile(PWSH):
        return PWSH, "PowerShell 7 (no Windows Terminal found)"
    raise SystemExit("ERROR: neither wt.exe nor pwsh.exe found. "
                     "Install Windows Terminal and/or PowerShell 7 first.")


def generalize_path(path):
    candidates = [
        (os.path.expandvars("%ProgramFiles%"), KF_PROGRAMFILES),
        (os.path.expandvars("%SystemRoot%") + chr(92) + "System32", KF_SYSTEM),
        (os.path.expandvars("%SystemRoot%"), KF_WINDOWS),
    ]
    for prefix, guid in candidates:
        if path.lower().startswith(prefix.lower()):
            return guid + path[len(prefix):]
    return path


def winx_hash(target, args):
    blob = (generalize_path(target) + (args or "") + SALT).lower()
    data = blob.encode("utf-16-le")
    out = (ctypes.c_ubyte * 4)()
    hr = ctypes.windll.shlwapi.HashData(data, len(data), out, 4)
    if hr != 0:
        raise RuntimeError("HashData failed, hr=0x%08X" % hr)
    return int.from_bytes(bytes(out), "little")


def read_stored_hash(path):
    data = open(path, "rb").read()
    i = data.find(FMTID_BYTES)
    if i < 0:
        return None
    j = data.find(VT_UI4_MARKER, i + 16, i + 16 + 64)
    if j < 0:
        return None
    return int.from_bytes(data[j + 5:j + 9], "little")


def patch_hash_inplace(path, new_hash):
    data = bytearray(open(path, "rb").read())
    i = data.find(FMTID_BYTES)
    if i < 0:
        raise RuntimeError("winx hash fmtid not found in " + path)
    j = data.find(VT_UI4_MARKER, i + 16, i + 16 + 64)
    if j < 0:
        raise RuntimeError("VT_UI4 value marker not found in " + path)
    old = int.from_bytes(data[j + 5:j + 9], "little")
    data[j + 5:j + 9] = new_hash.to_bytes(4, "little")
    open(path, "wb").write(bytes(data))
    return old


def patch_runas_flag(path, runas):
    """LinkFlags RunAsUser (0x2000): .lnk 偏移 21 字节的 0x20 位。"""
    with open(path, "r+b") as f:
        f.seek(21)
        b = f.read(1)[0]
        b = (b | 0x20) if runas else (b & ~0x20)
        f.seek(21)
        f.write(bytes([b]))


def load_link(path):
    link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    pf = link.QueryInterface(pythoncom.IID_IPersistFile)
    pf.Load(path)
    return link, pf


def self_check(path):
    """用原文件验证 hash 算法实现：算出来的值必须等于文件内存储的值。"""
    stored = read_stored_hash(path)
    if stored is None:
        print("  [skip] no stored hash to self-check against")
        return
    link, _ = load_link(path)
    computed = winx_hash(link.GetPath(0)[0], link.GetArguments())
    status = "OK" if computed == stored else "MISMATCH!"
    print("  [self-check] stored=0x%08X computed=0x%08X %s" % (stored, computed, status))
    if computed != stored:
        raise SystemExit("hash algorithm self-check failed, aborting before any modification")


def main():
    target, why = pick_target()
    print("Target: %s (%s)" % (target, why))
    os.makedirs(BACKUP, exist_ok=True)

    icon = PWSH if os.path.isfile(PWSH) else target

    entries = [
        ("01a - Windows PowerShell.lnk", False, "PowerShell 7"),
        ("02a - Windows PowerShell.lnk", True, "PowerShell 7 " + ADMIN_SUFFIX),
    ]

    # 第一步：算法自校验（在任何修改之前）
    print("Step 1: self-check hash algorithm on original files")
    for name, _, _ in entries:
        p = os.path.join(GROUP3, name)
        if not os.path.isfile(p):
            raise SystemExit("missing: " + p)
        self_check(p)

    # 第二步：备份 + 改写 + 盖 hash
    print("Step 2: backup, rewrite, re-stamp")
    for name, runas, desc in entries:
        p = os.path.join(GROUP3, name)
        bak = os.path.join(BACKUP, name)
        if not os.path.isfile(bak):
            shutil.copy2(p, bak)

        link, pf = load_link(p)
        link.SetPath(target)
        link.SetArguments("")
        link.SetWorkingDirectory("%HOMEDRIVE%%HOMEPATH%")
        link.SetIconLocation(icon, 0)
        link.SetDescription(desc)  # 菜单显示名来自 Description，不是 desktop.ini
        pf.Save(p, True)
        patch_runas_flag(p, runas)

        link2, _ = load_link(p)
        h = winx_hash(link2.GetPath(0)[0], link2.GetArguments())
        old_h = patch_hash_inplace(p, h)
        print("  [OK] %-32s hash 0x%08X -> 0x%08X runas=%s" % (name, old_h, h, runas))

    ini_bak_src = os.path.join(GROUP3, "desktop.ini")
    ini_bak = os.path.join(BACKUP, "desktop.ini")
    if os.path.isfile(ini_bak_src) and not os.path.isfile(ini_bak):
        shutil.copy2(ini_bak_src, ini_bak)

    print()
    print("Done. Now restart Explorer:")
    print("  Stop-Process -Name explorer -Force; Start-Process explorer.exe")
    print("Then press Win+X to verify.")


if __name__ == "__main__":
    main()
