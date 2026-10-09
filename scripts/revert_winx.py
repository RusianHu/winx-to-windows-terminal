# -*- coding: utf-8 -*-
"""
revert_winx.py — 回滚：把 backup/ 中的原始快捷方式恢复回 WinX Group3。
原文件自带有效 hash，恢复后无需重算。完成后需重启 Explorer。
"""
import os
import shutil

GROUP3 = os.path.expandvars("%LOCALAPPDATA%" + chr(92) + r"Microsoft\Windows\WinX\Group3")
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup")


def main():
    if not os.path.isdir(BACKUP):
        raise SystemExit("no backup found at " + BACKUP)
    restored = []
    for name in os.listdir(BACKUP):
        src = os.path.join(BACKUP, name)
        dst = os.path.join(GROUP3, name)
        shutil.copy2(src, dst)
        restored.append(name)
    print("restored: " + ", ".join(restored))
    print("Now restart Explorer:")
    print("  Stop-Process -Name explorer -Force; Start-Process explorer.exe")


if __name__ == "__main__":
    main()
