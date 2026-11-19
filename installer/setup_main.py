"""한글 PDF 변환기 설치 프로그램.

사용자 계정에만 설치한다(관리자 권한 필요 없음). 기본 위치: %LOCALAPPDATA%\\Programs\\hwp2pdf-safe
조용히 설치: setup.exe /S [/D=설치폴더] [/NODESKTOP] [/NOSENDTO] [/NOSTART]
"""
import os
import shutil
import subprocess
import sys
import threading
import zipfile

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(BASE))

import install_common as ic  # noqa: E402

VERSION = open(os.path.join(BASE, "VERSION"), encoding="utf-8").read().strip() if \
    os.path.exists(os.path.join(BASE, "VERSION")) else "1.0.0"
PAYLOAD = os.path.join(BASE, "payload.zip")
FONT = "맑은 고딕"


def _locked(install_dir):
    exe = os.path.join(install_dir, ic.EXE)
    if not os.path.exists(exe):
        return False
    try:
        os.rename(exe, exe + ".chk")
        os.rename(exe + ".chk", exe)
        return False
    except OSError:
        return True


def install(install_dir, desktop=True, start=True, sendto=True, progress=lambda f: None):
    install_dir = os.path.abspath(install_dir)
    if os.path.basename(install_dir).lower() != ic.APP_ID.lower():
        install_dir = os.path.join(install_dir, ic.APP_ID)   # 다른 폴더를 통째로 쓰지 않게 항상 전용 하위 폴더
    if _locked(install_dir):
        raise RuntimeError("%s가 실행 중입니다. 프로그램을 닫고 다시 설치하세요." % ic.DISPLAY)
    if os.path.isdir(install_dir) and os.listdir(install_dir):
        if not os.path.isfile(os.path.join(install_dir, ic.EXE)):
            raise RuntimeError("설치할 폴더에 다른 파일이 있습니다. 빈 폴더를 고르세요:\n%s" % install_dir)
        shutil.rmtree(install_dir)          # 예전 설치만 지우고 새로 푼다
    os.makedirs(install_dir, exist_ok=True)
    with zipfile.ZipFile(PAYLOAD) as z:
        names = z.infolist()
        total = sum(i.file_size for i in names) or 1
        done = 0
        for info in names:
            z.extract(info, install_dir)
            done += info.file_size
            progress(done / total)
    exe = os.path.join(install_dir, ic.EXE)
    if not os.path.isfile(exe):
        raise RuntimeError("설치 파일이 손상됐습니다(%s 없음)" % ic.EXE)
    paths = ic.shortcut_paths()
    ic.remove_shortcuts()
    if desktop:
        ic.make_shortcut(paths["desktop"], exe, install_dir, "한글 → PDF, PDF → 한글 변환")
    if start:
        ic.make_shortcut(paths["start"], exe, install_dir, "한글 → PDF, PDF → 한글 변환")
    if sendto:
        ic.make_shortcut(paths["sendto"], exe, install_dir, "골라 둔 파일을 한글 PDF 변환기로 보내기")
    ic.register(install_dir, VERSION, total // 1024)
    return exe


def silent(args):
    d = ic.installed_dir() or ic.default_dir()
    for a in args:
        if a.upper().startswith("/D="):
            d = a[3:]
    exe = install(d, "/NODESKTOP" not in args, "/NOSTART" not in args, "/NOSENDTO" not in args)
    print("설치됨:", exe)
    return 0


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    r = tk.Tk()
    r.title("%s %s 설치" % (ic.DISPLAY, VERSION))
    try:
        r.iconbitmap(os.path.join(BASE, "icon.ico"))
    except Exception:
        pass
    r.resizable(False, False)
    st = ttk.Style(r)
    try:
        st.theme_use("vista")
    except tk.TclError:
        pass
    for w in ("TLabel", "TButton", "TCheckbutton"):
        st.configure(w, font=(FONT, 10))
    st.configure("Title.TLabel", font=(FONT, 15, "bold"))
    st.configure("Note.TLabel", foreground="#666666", font=(FONT, 9))
    st.configure("Warn.TLabel", foreground="#b3261e", font=(FONT, 9))
    f = ttk.Frame(r, padding=20)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=ic.DISPLAY + " 설치", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(f, text="한글 문서를 글·수식이 안 깨지는 PDF로 바꾸고, 그 PDF에서 원본 한글 파일을 되살립니다.",
              style="Note.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"HWPFrame.HwpObject\CLSID").Close()
    except OSError:
        ttk.Label(f, text="※ 한글(한컴오피스)이 없는 것 같습니다. 설치는 되지만 한글 → PDF 변환은 한글이 있어야 합니다.",
                  style="Warn.TLabel", wraplength=520).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 8))
    ttk.Label(f, text="설치할 곳").grid(row=3, column=0, sticky="w")
    v_dir = tk.StringVar(value=ic.installed_dir() or ic.default_dir())
    ttk.Entry(f, textvariable=v_dir, width=52).grid(row=3, column=1, sticky="ew", padx=6)

    def browse():
        d = filedialog.askdirectory(title="설치할 폴더 고르기")
        if d:
            v_dir.set(os.path.join(os.path.abspath(d), ic.APP_ID))
    ttk.Button(f, text="찾아보기…", command=browse).grid(row=3, column=2)
    v_desk, v_start, v_send = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    ttk.Checkbutton(f, text="바탕화면에 바로가기", variable=v_desk).grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 0))
    ttk.Checkbutton(f, text="시작 메뉴에 넣기", variable=v_start).grid(row=5, column=0, columnspan=3, sticky="w")
    ttk.Checkbutton(f, text="파일 우클릭 → '보내기' 메뉴에 넣기 (파일을 골라 바로 변환 창에 넣기)",
                    variable=v_send).grid(row=6, column=0, columnspan=3, sticky="w")
    prog = ttk.Progressbar(f, mode="determinate", maximum=1.0)
    prog.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(16, 4))
    msg = ttk.Label(f, text="", style="Note.TLabel")
    msg.grid(row=8, column=0, columnspan=3, sticky="w")
    bf = ttk.Frame(f)
    bf.grid(row=9, column=0, columnspan=3, sticky="e", pady=(10, 0))
    state = {"exe": None}

    def run_app():
        subprocess.Popen([state["exe"]], cwd=os.path.dirname(state["exe"]))
        r.destroy()

    def do_install():
        go.configure(state="disabled")
        msg.configure(text="설치하는 중…")

        def work():
            try:
                exe = install(v_dir.get().strip(), v_desk.get(), v_start.get(), v_send.get(),
                              progress=lambda x: r.after(0, prog.configure, {"value": x}))
                r.after(0, finished, exe, None)
            except Exception as e:
                r.after(0, finished, None, e)
        threading.Thread(target=work, daemon=True).start()

    def finished(exe, err):
        if err:
            msg.configure(text="")
            go.configure(state="normal")
            messagebox.showerror(ic.DISPLAY, "설치하지 못했습니다.\n%s" % err)
            return
        state["exe"] = exe
        msg.configure(text="설치를 마쳤습니다. 지울 때는 설정 → 앱 → '%s'에서 제거하세요." % ic.DISPLAY)
        go.configure(text="실행", state="normal", command=run_app)
        cancel.configure(text="닫기")

    cancel = ttk.Button(bf, text="취소", command=r.destroy)
    cancel.pack(side="right")
    go = ttk.Button(bf, text="설치", command=do_install)
    go.pack(side="right", padx=(0, 8))
    r.mainloop()
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(silent(args) if "/S" in [a.upper() for a in args] else gui())
