"""설치·제거에서 같이 쓰는 것: 경로, 바로가기, '앱 및 기능' 등록. (사용자 계정에만 설치, 관리자 권한 필요 없음)"""
import os
import winreg

APP_ID = "hwp2pdf-safe"
DISPLAY = "한글 PDF 변환기"
EXE = "hwp2pdf-safe.exe"
PUBLISHER = "hwp2pdf-safe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\%s" % APP_ID


def default_dir():
    return os.path.join(os.environ["LOCALAPPDATA"], "Programs", APP_ID)


def _shell_folder(name):
    import win32com.client
    return win32com.client.Dispatch("WScript.Shell").SpecialFolders(name)


def shortcut_paths():
    return {
        "desktop": os.path.join(_shell_folder("Desktop"), DISPLAY + ".lnk"),
        "start": os.path.join(_shell_folder("Programs"), DISPLAY + ".lnk"),
        "sendto": os.path.join(_shell_folder("SendTo"), DISPLAY + ".lnk"),
    }


def make_shortcut(lnk, target, workdir, desc):
    import win32com.client
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(lnk)
    sc.TargetPath = target
    sc.WorkingDirectory = workdir
    sc.IconLocation = target + ",0"
    sc.Description = desc
    sc.Save()


def remove_shortcuts():
    for p in shortcut_paths().values():
        try:
            os.remove(p)
        except OSError:
            pass


def register(install_dir, version, size_kb):
    exe = os.path.join(install_dir, EXE)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in (("DisplayName", DISPLAY), ("DisplayVersion", version), ("Publisher", PUBLISHER),
                          ("DisplayIcon", exe + ",0"), ("InstallLocation", install_dir),
                          ("UninstallString", '"%s" --uninstall' % exe),
                          ("QuietUninstallString", '"%s" --uninstall /S' % exe)):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        for name, val in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", int(size_kb))):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)


def unregister():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


def installed_dir():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0]
    except OSError:
        return None
