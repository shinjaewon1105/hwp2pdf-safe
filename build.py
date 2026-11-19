"""설치 파일 만들기: python build.py

1) 변환기 화면을 PyInstaller 폴더형 exe로 만든다 (build/dist/hwp2pdf-safe/)
2) 그 폴더를 payload.zip 으로 묶는다
3) payload.zip 을 품은 설치 프로그램 하나짜리 exe를 만든다 (release/hwp2pdf-safe-setup-<버전>.exe)
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from hwppdf import __version__  # noqa: E402

B = os.path.join(ROOT, "build")
SEP = ";"


def pyinstaller(args):
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
           "--workpath", os.path.join(B, "work"), "--specpath", B] + args
    print(">", " ".join(cmd[3:]))
    subprocess.check_call(cmd, cwd=ROOT)


def main():
    os.makedirs(B, exist_ok=True)
    icon = os.path.join(ROOT, "assets", "icon.ico")
    dll = os.path.join(ROOT, "hwppdf", "FilePathCheckerModule.dll")
    pyinstaller([
        "--windowed", "--name", "hwp2pdf-safe", "--icon", icon, "--distpath", os.path.join(B, "dist"),
        "--paths", ROOT,
        "--add-data", icon + SEP + "assets",
        "--add-binary", dll + SEP + "hwppdf",
        "--hidden-import", "hwp2pdf", "--hidden-import", "pdf2hwp",
        "--hidden-import", "uninstall", "--hidden-import", "install_common",
        "--collect-submodules", "fontTools.ttLib.tables",
        "--collect-all", "tkinterdnd2", "--collect-all", "pypdfium2", "--collect-all", "pypdfium2_raw",
        "--collect-all", "pikepdf",
        "--exclude-module", "numpy", "--exclude-module", "pandas", "--exclude-module", "PIL",
        "--exclude-module", "pyhwpx", "--exclude-module", "matplotlib", "--exclude-module", "openpyxl",
        "--exclude-module", "IPython", "--exclude-module", "pytest",
        os.path.join(ROOT, "hwp2pdf_gui.py"),
    ])
    app_dir = os.path.join(B, "dist", "hwp2pdf-safe")
    payload = os.path.join(B, "payload.zip")
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, _, fs in os.walk(app_dir):
            for f in fs:
                full = os.path.join(dp, f)
                z.write(full, os.path.relpath(full, app_dir))
    ver = os.path.join(B, "VERSION")
    open(ver, "w", encoding="utf-8").write(__version__)
    name = "hwp2pdf-safe-setup-%s" % __version__
    pyinstaller([
        "--onefile", "--windowed", "--name", name, "--icon", icon,
        "--distpath", os.path.join(B, "setup"), "--paths", ROOT,
        "--add-data", payload + SEP + ".", "--add-data", icon + SEP + ".", "--add-data", ver + SEP + ".",
        "--hidden-import", "install_common",
        "--exclude-module", "numpy", "--exclude-module", "PIL", "--exclude-module", "pyhwpx",
        os.path.join(ROOT, "installer", "setup_main.py"),
    ])
    os.makedirs(os.path.join(ROOT, "release"), exist_ok=True)
    out = os.path.join(ROOT, "release", name + ".exe")
    shutil.copyfile(os.path.join(B, "setup", name + ".exe"), out)
    print("만듦:", out, "(%.1f MB)" % (os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
