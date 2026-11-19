"""제거: 바로가기·'앱 및 기능' 항목·설정을 지우고, 프로그램이 끝난 뒤 설치 폴더를 지운다.

    hwp2pdf-safe.exe --uninstall [/S]
"""
import os
import shutil
import subprocess
import sys

import install_common as ic


def main():
    silent = "/S" in sys.argv
    if not silent:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        ok = messagebox.askyesno(ic.DISPLAY, "%s를 이 컴퓨터에서 지울까요?\n(만든 PDF와 한글 파일은 지우지 않습니다)"
                                 % ic.DISPLAY)
        if not ok:
            return 0
    ic.remove_shortcuts()
    ic.unregister()
    shutil.rmtree(os.path.join(os.environ.get("APPDATA", ""), ic.APP_ID), ignore_errors=True)
    install_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else None
    if install_dir and os.path.basename(install_dir).lower() == ic.APP_ID.lower():
        # 실행 중인 exe 는 바로 못 지우므로, 이 프로그램이 끝난 뒤 지우는 명령을 따로 띄운다
        cmd = 'ping -n 3 127.0.0.1 >nul & rmdir /s /q "%s"' % install_dir
        subprocess.Popen(["cmd", "/c", cmd], creationflags=0x08000000 | 0x00000008,
                         cwd=os.environ.get("TEMP", "C:\\"))
    if not silent:
        messagebox.showinfo(ic.DISPLAY, "지웠습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
