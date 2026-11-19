"""한글 PDF 변환기 (화면)

한글 파일(.hwp/.hwpx)은 PDF로, 이 도구로 만든 PDF는 원본 한글 파일로 바꾼다. 여러 개를 한 번에.
"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

if getattr(sys, "frozen", False):
    BASE = sys._MEIPASS
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from hwppdf import APP_NAME, APP_TITLE, __version__  # noqa: E402

HWP_EXT = (".hwp", ".hwpx")
SETTINGS = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME, "settings.json")
DEFAULTS = {"embed": True, "eq": "unicode", "dest_mode": "same", "dest_dir": "", "overwrite": False,
            "open_after": True, "check": True}
EQ_CHOICES = [
    ("unicode", "읽기 쉬운 글", "x = (-b±√(b²-4ac))/(2a)"),
    ("latex", "LaTeX", r"x=\frac{-b\pm\sqrt{b^{2}-4ac}}{2a}"),
    ("hwp", "한글 수식 스크립트", "x = {-b +- sqrt {b^2 -4ac}} over {2a}"),
    ("none", "복사 안 되게", "수식은 모양만 남고 긁어도 나오지 않음"),
]
FONT = "맑은 고딕"


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def free_name(path, tag=" (%d)"):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(stem + (tag % n) + ext):
        n += 1
    return stem + (tag % n) + ext


def has_original(pdf_path):
    try:
        import pikepdf
        from hwppdf import embed
        with pikepdf.open(pdf_path) as pdf:
            return embed.find_original(pdf) is not None
    except Exception:
        return False


class App:
    def __init__(self, root, initial_files=()):
        self.root = root
        self.s = load_settings()
        self.items = {}            # tree id -> dict(path, kind, status, out)
        self.q = queue.Queue()
        self.worker = None
        self.stop_flag = threading.Event()

        root.title("%s %s" % (APP_TITLE, __version__))
        try:
            root.iconbitmap(os.path.join(BASE, "assets", "icon.ico"))
        except Exception:
            pass
        root.minsize(int(760 * max(1.0, root.winfo_fpixels("1i") / 96.0)), int(560 * max(1.0, root.winfo_fpixels("1i") / 96.0)))
        self._style()
        self._build()
        self._check_hancom()
        self.add_paths(initial_files)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)

    # ------------------------------------------------------------ 모양
    def _style(self):
        from tkinter import font as tkfont
        self.k = max(1.0, self.root.winfo_fpixels("1i") / 96.0)   # 화면 배율(고해상도 모니터)
        st = ttk.Style(self.root)
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        self.root.option_add("*Font", (FONT, 10))
        for w in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TLabelframe.Label", "Treeview"):
            st.configure(w, font=(FONT, 10))
        st.configure("Treeview.Heading", font=(FONT, 10, "bold"))
        st.configure("Treeview", rowheight=int(tkfont.Font(font=(FONT, 10)).metrics("linespace") + 8 * self.k))
        st.configure("Title.TLabel", font=(FONT, 15, "bold"))
        st.configure("Note.TLabel", foreground="#666666", font=(FONT, 9))
        st.configure("Example.TLabel", foreground="#666666", font=("Segoe UI", 9))   # 맑은 고딕은 \를 ₩로 그림
        st.configure("Warn.TLabel", foreground="#b3261e", font=(FONT, 9))
        st.configure("Go.TButton", font=(FONT, 11, "bold"), padding=(18, 6))

    def _build(self):
        r = self.root
        top = ttk.Frame(r, padding=(14, 12, 14, 4))
        top.pack(fill="x")
        ttk.Label(top, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  한글 → PDF (글·수식 복사 안 깨짐)   ·   이 도구로 만든 PDF → 원본 한글",
                  style="Note.TLabel").pack(side="left", pady=(6, 0))
        self.banner = ttk.Label(r, text="", style="Warn.TLabel", padding=(14, 0))
        self.banner.pack(fill="x")

        # 파일 목록
        mid = ttk.Frame(r, padding=(14, 6))
        mid.pack(fill="both", expand=True)
        cols = ("name", "kind", "status", "out")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended", height=8)
        for c, t, w, stretch in (("name", "파일", 230, True), ("kind", "작업", 95, False),
                                 ("status", "상태", 200, False), ("out", "결과 파일", 200, True)):
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=int(w * self.k), minwidth=int(60 * self.k), stretch=stretch, anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        self.tree.tag_configure("done", foreground="#1b7f3b")
        self.tree.tag_configure("fail", foreground="#b3261e")
        self.tree.tag_configure("skip", foreground="#888888")
        self.tree.bind("<Double-1>", self.open_selected)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.hint = tk.Label(self.tree, text="여기에 한글 파일(.hwp, .hwpx)이나\n이 도구로 만든 PDF를 끌어다 놓으세요",
                             fg="#8a8a8a", bg="white", font=(FONT, 11))
        self._enable_dnd()

        btns = ttk.Frame(mid, padding=(0, 6, 0, 0))
        btns.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(btns, text="파일 추가…", command=self.pick_files).pack(side="left")
        ttk.Button(btns, text="폴더 추가…", command=self.pick_folder).pack(side="left", padx=6)
        ttk.Button(btns, text="선택 빼기", command=self.remove_selected).pack(side="left")
        ttk.Button(btns, text="모두 비우기", command=self.clear_all).pack(side="left", padx=6)
        self.count_lbl = ttk.Label(btns, text="", style="Note.TLabel")
        self.count_lbl.pack(side="right")

        # 설정
        opt = ttk.LabelFrame(r, text=" 변환 설정 (한글 → PDF) ", padding=(12, 8))
        opt.pack(fill="x", padx=14, pady=(4, 6))
        opt.columnconfigure(1, weight=1)

        self.v_embed = tk.BooleanVar(value=self.s["embed"])
        ttk.Checkbutton(opt, text="원본 한글 파일을 PDF에 넣기 (나중에 PDF에서 한글 파일로 되살릴 수 있음)",
                        variable=self.v_embed, command=self._embed_note).grid(row=0, column=0, columnspan=3, sticky="w")
        self.embed_note = ttk.Label(opt, text="", style="Note.TLabel")
        self.embed_note.grid(row=1, column=0, columnspan=3, sticky="w", padx=(22, 0))
        self._embed_note()

        ttk.Label(opt, text="수식을 긁어 복사하면").grid(row=2, column=0, sticky="nw", pady=(8, 0))
        eqf = ttk.Frame(opt)
        eqf.grid(row=2, column=1, columnspan=2, sticky="w", pady=(8, 0))
        self.v_eq = tk.StringVar(value=self.s["eq"])
        for i, (key, name, example) in enumerate(EQ_CHOICES):
            ttk.Radiobutton(eqf, text=name, value=key, variable=self.v_eq).grid(row=i, column=0, sticky="w", padx=(8, 0))
            # ttk 스타일 글꼴이 안 먹어 맑은 고딕으로 그려지면 \ 가 ₩로 보이므로 tk.Label 에 글꼴을 직접 준다
            tk.Label(eqf, text=example, font=("Segoe UI", 9), fg="#666666",
                     bg=ttk.Style(self.root).lookup("TFrame", "background") or "SystemButtonFace"
                     ).grid(row=i, column=1, sticky="w", padx=(10, 0))

        ttk.Label(opt, text="저장 위치").grid(row=3, column=0, sticky="w", pady=(8, 0))
        df = ttk.Frame(opt)
        df.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(8, 0))
        df.columnconfigure(2, weight=1)
        self.v_dest = tk.StringVar(value=self.s["dest_mode"])
        self.v_dir = tk.StringVar(value=self.s["dest_dir"])
        ttk.Radiobutton(df, text="원래 파일과 같은 폴더", value="same", variable=self.v_dest,
                        command=self._dest_state).grid(row=0, column=0, sticky="w", padx=(8, 0))
        ttk.Radiobutton(df, text="이 폴더:", value="dir", variable=self.v_dest,
                        command=self._dest_state).grid(row=0, column=1, sticky="w", padx=(14, 4))
        self.dir_entry = ttk.Entry(df, textvariable=self.v_dir)
        self.dir_entry.grid(row=0, column=2, sticky="ew")
        self.dir_btn = ttk.Button(df, text="찾아보기…", command=self.pick_dest)
        self.dir_btn.grid(row=0, column=3, padx=(6, 0))
        self._dest_state()

        ttk.Label(opt, text="같은 이름이 있으면").grid(row=4, column=0, sticky="w", pady=(8, 0))
        of = ttk.Frame(opt)
        of.grid(row=4, column=1, columnspan=2, sticky="w", pady=(8, 0))
        self.v_over = tk.BooleanVar(value=self.s["overwrite"])
        ttk.Radiobutton(of, text="새 이름으로 저장 ( … (2).pdf )", value=False, variable=self.v_over).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(of, text="덮어쓰기", value=True, variable=self.v_over).pack(side="left", padx=(14, 0))

        ef = ttk.Frame(opt)
        ef.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.v_open = tk.BooleanVar(value=self.s["open_after"])
        self.v_check = tk.BooleanVar(value=self.s["check"])
        ttk.Checkbutton(ef, text="다 되면 결과 열기", variable=self.v_open).pack(side="left")
        ttk.Checkbutton(ef, text="결과 검사하기 (모양·글자·줄바꿈 확인, 조금 느려짐)",
                        variable=self.v_check).pack(side="left", padx=(18, 0))

        # 실행
        bot = ttk.Frame(r, padding=(14, 4, 14, 6))
        bot.pack(fill="x")
        self.prog = ttk.Progressbar(bot, mode="determinate")
        self.prog.pack(side="left", fill="x", expand=True)
        self.stop_btn = ttk.Button(bot, text="멈추기", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(10, 0))
        self.go_btn = ttk.Button(bot, text="변환 시작", style="Go.TButton", command=self.start)
        self.go_btn.pack(side="left", padx=(8, 0))
        st = ttk.Frame(r, padding=(14, 0, 14, 4))
        st.pack(fill="x")
        self.status = ttk.Label(st, text="파일을 추가하세요.", style="Note.TLabel")
        self.status.pack(side="left")
        self.log_btn = ttk.Button(st, text="자세한 기록 보기 ▾", command=self.toggle_log)
        self.log_btn.pack(side="right")
        self.log_frame = ttk.Frame(r, padding=(14, 0, 14, 10))
        self.log = tk.Text(self.log_frame, height=9, font=("Consolas", 9), wrap="word", state="disabled",
                           bg="#fafafa", relief="solid", bd=1)
        lsb = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True)
        lsb.pack(side="left", fill="y")
        self._refresh()

    def _enable_dnd(self):
        try:
            from tkinterdnd2 import DND_FILES
            for w in (self.tree, self.hint):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", lambda e: self.add_paths(self.root.tk.splitlist(e.data)))
            self.dnd = True
        except Exception:
            self.dnd = False
            self.hint.configure(text="'파일 추가'로 한글 파일(.hwp, .hwpx)이나\n이 도구로 만든 PDF를 넣으세요")

    def _check_hancom(self):
        from hwppdf.hwpcom import hancom_installed
        if not hancom_installed():
            self.banner.configure(text="한글 프로그램을 찾지 못했습니다. 한글 → PDF 변환은 한글(한컴오피스)이 설치돼 있어야 합니다. "
                                       "PDF → 한글 되살리기는 그대로 됩니다.")

    def _embed_note(self):
        if self.v_embed.get():
            self.embed_note.configure(text="※ PDF를 받은 사람도 첨부된 원본(메모·숨은 글 포함)을 꺼낼 수 있습니다.",
                                      style="Note.TLabel")
        else:
            self.embed_note.configure(text="※ 원본을 넣지 않으면 이 PDF로는 한글 파일을 되살릴 수 없습니다.",
                                      style="Warn.TLabel")

    def _dest_state(self):
        state = "normal" if self.v_dest.get() == "dir" else "disabled"
        self.dir_entry.configure(state=state)
        self.dir_btn.configure(state=state)

    # ------------------------------------------------------------ 목록
    def add_paths(self, paths):
        added = 0
        known = {v["path"].lower() for v in self.items.values()}
        for p in paths:
            p = os.path.abspath(p)
            files = []
            if os.path.isdir(p):
                for dp, _, fs in os.walk(p):
                    files += [os.path.join(dp, f) for f in fs if f.lower().endswith(HWP_EXT)]
            elif os.path.isfile(p):
                files = [p]
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                if f.lower() in known or ext not in HWP_EXT + (".pdf",):
                    continue
                kind = "한글 → PDF" if ext in HWP_EXT else "PDF → 한글"
                status, tag = "대기", ()
                if ext == ".pdf" and not has_original(f):
                    status, tag = "건너뜀: 첨부된 원본 없음", ("skip",)
                iid = self.tree.insert("", "end", values=(os.path.basename(f), kind, status, ""), tags=tag)
                self.items[iid] = {"path": f, "kind": "pdf" if ext in HWP_EXT else "hwp", "status": status,
                                   "out": None}
                known.add(f.lower())
                added += 1
        self._refresh()
        return added

    def pick_files(self):
        fs = filedialog.askopenfilenames(
            title="파일 고르기", filetypes=[("한글 문서·PDF", "*.hwp *.hwpx *.pdf"), ("한글 문서", "*.hwp *.hwpx"),
                                         ("PDF", "*.pdf"), ("모든 파일", "*.*")])
        self.add_paths(fs)

    def pick_folder(self):
        d = filedialog.askdirectory(title="한글 파일이 든 폴더 고르기")
        if d:
            n = self.add_paths([d])
            if not n:
                messagebox.showinfo(APP_TITLE, "그 폴더(하위 폴더 포함)에서 새로 넣을 한글 파일을 찾지 못했습니다.")

    def pick_dest(self):
        d = filedialog.askdirectory(title="저장할 폴더 고르기")
        if d:
            self.v_dir.set(os.path.abspath(d))

    def remove_selected(self):
        if self.worker:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)
        self._refresh()

    def clear_all(self):
        if self.worker:
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self._refresh()

    def open_selected(self, _e=None):
        for iid in self.tree.selection():
            it = self.items.get(iid)
            if it and it["out"] and os.path.exists(it["out"]):
                os.startfile(it["out"])

    def _refresh(self):
        n = len(self.items)
        if n:
            self.hint.place_forget()
        else:
            self.hint.place(relx=0.5, rely=0.5, anchor="center")
        todo = sum(1 for v in self.items.values() if v["status"] == "대기")
        self.count_lbl.configure(text="%d개 (할 일 %d개)" % (n, todo) if n else "")
        if not self.worker:
            self.go_btn.configure(state="normal" if todo else "disabled")

    def toggle_log(self):
        if self.log_frame.winfo_ismapped():
            self.log_frame.pack_forget()
            self.log_btn.configure(text="자세한 기록 보기 ▾")
        else:
            self.log_frame.pack(fill="both", expand=False)
            self.log_btn.configure(text="자세한 기록 닫기 ▴")

    def _log(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set(self, iid, status=None, out=None, tag=None):
        it = self.items.get(iid)
        if not it:
            return
        if status is not None:
            it["status"] = status
        if out is not None:
            it["out"] = out
        self.tree.item(iid, values=(os.path.basename(it["path"]), self.tree.set(iid, "kind"), it["status"],
                                    os.path.basename(it["out"]) if it["out"] else ""), tags=(tag,) if tag else ())

    # ------------------------------------------------------------ 변환
    def current_settings(self):
        return {"embed": self.v_embed.get(), "eq": self.v_eq.get(), "dest_mode": self.v_dest.get(),
                "dest_dir": self.v_dir.get().strip(), "overwrite": self.v_over.get(),
                "open_after": self.v_open.get(), "check": self.v_check.get()}

    def start(self):
        s = self.current_settings()
        if s["dest_mode"] == "dir":
            if not s["dest_dir"]:
                messagebox.showwarning(APP_TITLE, "저장할 폴더를 고르세요.")
                return
            try:
                os.makedirs(s["dest_dir"], exist_ok=True)
            except OSError as e:
                messagebox.showerror(APP_TITLE, "저장할 폴더를 만들 수 없습니다.\n%s" % e)
                return
        jobs = [(iid, dict(v)) for iid, v in self.items.items() if v["status"] == "대기"]
        if not jobs:
            return
        if any(j[1]["kind"] == "pdf" for j in jobs):
            from hwppdf.hwpcom import hancom_installed
            if not hancom_installed():
                messagebox.showerror(APP_TITLE, "한글 프로그램이 없어 한글 → PDF 변환을 할 수 없습니다.")
                return
        save_settings(s)
        self.s = s
        self.stop_flag.clear()
        self.prog.configure(maximum=len(jobs), value=0)
        self.go_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text="변환하는 중… (한글 프로그램이 화면에 안 보이게 열립니다)")
        self.worker = threading.Thread(target=self._run, args=(jobs, s), daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_flag.set()
        self.stop_btn.configure(state="disabled")
        self.status.configure(text="지금 파일까지만 하고 멈춥니다…")

    def _dest(self, src, ext, s):
        folder = s["dest_dir"] if s["dest_mode"] == "dir" else os.path.dirname(src)
        return os.path.join(folder, os.path.splitext(os.path.basename(src))[0] + ext)

    def _run(self, jobs, s):
        import hwp2pdf
        import pdf2hwp
        q = self.q
        done = []
        for n, (iid, it) in enumerate(jobs):
            if self.stop_flag.is_set():
                break
            src = it["path"]
            q.put(("status", iid, "변환 중…", None, None))
            q.put(("log", "[%s]" % os.path.basename(src)))
            log = lambda m: q.put(("log", m))  # noqa: E731
            try:
                if it["kind"] == "pdf":
                    out = self._dest(src, ".pdf", s)
                    if not s["overwrite"]:
                        out = free_name(out)
                    rep = hwp2pdf.convert(src, out, s["eq"], s["embed"], s["check"], log=log)
                    note = self._summary(rep, s)
                    q.put(("status", iid, note[0], out, note[1]))
                else:
                    folder = s["dest_dir"] if s["dest_mode"] == "dir" else None
                    out = pdf2hwp.restore(src, folder, log=log, overwrite=s["overwrite"])
                    q.put(("status", iid, "완료 (원본과 같음)", out, "done"))
                done.append(out)
            except Exception as e:
                msg = str(e) or type(e).__name__
                q.put(("log", "  실패: %s" % msg))
                q.put(("status", iid, "실패: " + msg[:60], None, "fail"))
            q.put(("progress", n + 1))
        q.put(("finished", done))

    @staticmethod
    def _summary(rep, s):
        v = rep.get("verify") or {}
        warn = []
        if rep.get("equations") and rep.get("located", 0) < rep["equations"]:
            warn.append("수식 %d개 못 찾음" % (rep["equations"] - rep["located"]))
        if v.get("render_diff", 0) > 0.002:
            warn.append("모양 차이")
        if v.get("missing_breaks"):
            warn.append("줄바꿈 %d곳 빠짐" % v["missing_breaks"])
        if any(isinstance(x, dict) and x.get("bad") for x in v.values()):
            warn.append("깨진 글자 있음")
        if warn:
            return "완료 (확인: %s)" % ", ".join(warn), "fail"
        eq = rep.get("equations", 0)
        return ("완료" + (" · 수식 %d개" % eq if eq else "")), "done"

    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "log":
                    self._log(m[1])
                elif m[0] == "status":
                    _, iid, st, out, tag = m
                    self._set(iid, st, out, tag)
                elif m[0] == "progress":
                    self.prog.configure(value=m[1])
                elif m[0] == "finished":
                    self._finished(m[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finished(self, done):
        self.worker = None
        self.stop_btn.configure(state="disabled")
        fails = sum(1 for v in self.items.values() if v["status"].startswith("실패"))
        self.status.configure(text="끝: %d개 완료%s. 결과를 두 번 누르면 열립니다." % (
            len(done), ", %d개 실패" % fails if fails else ""))
        self._refresh()
        if self.s.get("open_after") and done:
            if len(done) <= 3:
                for p in done:
                    try:
                        os.startfile(p)
                    except OSError:
                        pass
            else:
                for d in list(dict.fromkeys(os.path.dirname(p) for p in done))[:3]:
                    os.startfile(d)

    def on_close(self):
        if self.worker and not messagebox.askyesno(APP_TITLE, "변환 중입니다. 그래도 닫을까요?"):
            return
        save_settings(self.current_settings())
        self.root.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--uninstall":
        import uninstall
        return uninstall.main()
    if argv and argv[0] in ("--convert", "--restore"):
        # 명령줄 모드(창 없이). 창 프로그램이라 출력은 --log 파일로.
        args = argv[1:]
        logf = None
        if "--log" in args:
            i = args.index("--log")
            logf = open(args[i + 1], "w", encoding="utf-8")
            del args[i:i + 2]
            sys.stdout = sys.stderr = logf
        try:
            if argv[0] == "--convert":
                import hwp2pdf
                return hwp2pdf.main(args)
            import pdf2hwp
            return pdf2hwp.main(args)
        finally:
            if logf:
                logf.close()
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()
    App(root, [a for a in argv if not a.startswith("--")])
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
