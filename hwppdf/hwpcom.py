"""한글 프로그램(HWPFrame.HwpObject) COM을 직접 다루는 얇은 껍데기.

pyhwpx는 pandas·numpy까지 불러와 설치 파일이 커지므로, 변환에 필요한 것만 여기 둔다.
- 새 한글 인스턴스를 숨긴 채 띄운다(사용자가 열어 둔 한글 창은 건드리지 않음).
- 파일 접근 보안 모듈(FilePathCheckerModule.dll)을 등록해 '접근 허용' 대화상자가 뜨지 않게 한다.
- 암호 걸린 문서는 묻지 않고 실패로 처리한다(숨은 창에서 멈추지 않게).
"""
import os
import sys
import winreg

MODULE_KEY = r"Software\HNC\HwpAutomation\Modules"
MODULE_NAME = "FilePathCheckerModule"


def _bundled_dll():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "FilePathCheckerModule.dll")]
    if getattr(sys, "_MEIPASS", None):
        cands.append(os.path.join(sys._MEIPASS, "hwppdf", "FilePathCheckerModule.dll"))
    try:
        import importlib.util
        spec = importlib.util.find_spec("pyhwpx")
        if spec and spec.origin:
            cands.append(os.path.join(os.path.dirname(spec.origin), "FilePathCheckerModule.dll"))
    except Exception:
        pass
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def ensure_security_module():
    """레지스트리에 보안 모듈이 없거나 파일이 사라졌으면 함께 들어 있는 DLL로 등록한다."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MODULE_KEY) as k:
            val, _ = winreg.QueryValueEx(k, MODULE_NAME)
            if val and os.path.isfile(val):
                return val
    except OSError:
        pass
    dll = _bundled_dll()
    if not dll:
        return None
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MODULE_KEY) as k:
        winreg.SetValueEx(k, MODULE_NAME, 0, winreg.REG_SZ, dll)
    return dll


def hancom_installed():
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"HWPFrame.HwpObject\CLSID").Close()
        return True
    except OSError:
        return False


class Hwp:
    def __init__(self):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        ensure_security_module()
        self.app = win32com.client.dynamic.Dispatch("HWPFrame.HwpObject")
        try:
            self.app.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        try:
            self.app.RegisterModule("FilePathCheckDLL", MODULE_NAME)
        except Exception:
            pass

    # 자주 쓰는 것 그대로 넘기기
    def __getattr__(self, name):
        return getattr(self.app, name)

    def open(self, path):
        return bool(self.app.Open(os.path.abspath(path), "",
                                  "forceopen:true;suspendpassword:true;versionwarning:false"))

    @property
    def page_count(self):
        return int(self.app.PageCount)

    def equations(self):
        out, c = [], self.app.HeadCtrl
        while c:
            if c.CtrlID == "eqed":
                out.append(c)
            c = c.Next
        return out

    def text(self):
        try:
            return self.app.GetTextFile("UNICODE", "") or ""
        except Exception:
            return ""

    def save_pdf(self, path):
        path = os.path.abspath(path)
        act, ps = self.app.HAction, self.app.HParameterSet
        pset = ps.HFileOpenSave
        act.GetDefault("FileSaveAs_S", pset.HSet)
        pset.filename = path
        pset.Format = "PDF"
        pset.Attributes = 0
        if act.Execute("FileSaveAs_S", pset.HSet) and os.path.isfile(path):
            return True
        pset = ps.HFileOpenSave
        act.GetDefault("FileSaveAsPdf", pset.HSet)
        pset.filename = path
        pset.Format = "PDF"
        pset.Attributes = 16384
        return bool(act.Execute("FileSaveAsPdf", pset.HSet)) and os.path.isfile(path)

    def quit(self):
        try:
            self.app.XHwpDocuments.Active_XHwpDocument.Clear(1)   # 고친 내용 버리기
        except Exception:
            pass
        try:
            self.app.Quit()
        except Exception:
            pass
