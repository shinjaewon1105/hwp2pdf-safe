"""한글(HWP) 수식 스크립트를 복사용 글자로 바꾼다.

    to_unicode("x = {-b +- sqrt {b^2 -4ac}} over {2a}")  ->  "x = (-b±√(b²-4ac))/(2a)"
    to_latex(...)                                          ->  "x = \\frac{-b\\pm\\sqrt{b^{2}-4ac}}{2a}"

한글 수식 문법에서 지킨 것(한글 2024에서 확인한 동작):
- `^`, `_`, `over`의 분모는 띄어쓰기 전까지를 통째로 잡는다(`x^2+1`은 2+1이 올라감).
- `over`의 분자는 바로 앞 띄어쓰기 뒤부터다(`(2,~-8 over 9)`는 `(2,~-8`이 분자).
- `~`, `` ` ``는 빈칸, `#`은 줄 나눔, `&`는 칸 나눔, "따옴표"는 글자 그대로.
"""
import re

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π", "varpi": "ϖ",
    "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "ALPHA": "Α", "BETA": "Β", "GAMMA": "Γ", "DELTA": "Δ", "EPSILON": "Ε", "ZETA": "Ζ",
    "ETA": "Η", "THETA": "Θ", "IOTA": "Ι", "KAPPA": "Κ", "LAMBDA": "Λ", "MU": "Μ", "NU": "Ν",
    "XI": "Ξ", "OMICRON": "Ο", "PI": "Π", "RHO": "Ρ", "SIGMA": "Σ", "TAU": "Τ",
    "UPSILON": "Υ", "PHI": "Φ", "CHI": "Χ", "PSI": "Ψ", "OMEGA": "Ω",
}
# 대문자 그리스 글자는 Alpha 꼴로도 받는다
GREEK.update({k.capitalize(): v for k, v in list(GREEK.items()) if k.isupper()})

# 이름 -> (유니코드, LaTeX, 관계 기호인가)
SYMBOLS = {
    "times": ("×", r"\times", 0), "div": ("÷", r"\div", 0), "cdot": ("·", r"\cdot", 0),
    "cdots": ("⋯", r"\cdots", 0), "ldots": ("…", r"\ldots", 0), "vdots": ("⋮", r"\vdots", 0),
    "ddots": ("⋱", r"\ddots", 0), "inf": ("∞", r"\infty", 0), "infinity": ("∞", r"\infty", 0),
    "infty": ("∞", r"\infty", 0), "partial": ("∂", r"\partial", 0), "nabla": ("∇", r"\nabla", 0),
    "deg": ("°", r"^{\circ}", 0), "prime": ("′", r"'", 0), "angle": ("∠", r"\angle", 0),
    "triangle": ("△", r"\triangle", 0), "TRIANGLE": ("▲", r"\blacktriangle", 0),
    "therefore": ("∴", r"\therefore", 1), "because": ("∵", r"\because", 1),
    "in": ("∈", r"\in", 1), "notin": ("∉", r"\notin", 1), "owns": ("∋", r"\ni", 1), "ni": ("∋", r"\ni", 1),
    "subset": ("⊂", r"\subset", 1), "supset": ("⊃", r"\supset", 1), "subseteq": ("⊆", r"\subseteq", 1),
    "supseteq": ("⊇", r"\supseteq", 1), "nsubset": ("⊄", r"\not\subset", 1),
    "cup": ("∪", r"\cup", 0), "cap": ("∩", r"\cap", 0), "emptyset": ("∅", r"\emptyset", 0),
    "approx": ("≈", r"\approx", 1), "sim": ("∼", r"\sim", 1), "simeq": ("≃", r"\simeq", 1),
    "cong": ("≅", r"\cong", 1), "equiv": ("≡", r"\equiv", 1), "propto": ("∝", r"\propto", 1),
    "perp": ("⊥", r"\perp", 1), "bot": ("⊥", r"\bot", 0), "parallel": ("∥", r"\parallel", 1),
    "FORALL": ("∀", r"\forall", 0), "forall": ("∀", r"\forall", 0), "EXIST": ("∃", r"\exists", 0),
    "exist": ("∃", r"\exists", 0), "wedge": ("∧", r"\wedge", 0), "vee": ("∨", r"\vee", 0),
    "LNOT": ("¬", r"\neg", 0), "neg": ("¬", r"\neg", 0), "oplus": ("⊕", r"\oplus", 0),
    "ominus": ("⊖", r"\ominus", 0), "otimes": ("⊗", r"\otimes", 0), "odot": ("⊙", r"\odot", 0),
    "circ": ("∘", r"\circ", 0), "bullet": ("•", r"\bullet", 0), "star": ("⋆", r"\star", 0),
    "ast": ("∗", r"\ast", 0), "dagger": ("†", r"\dagger", 0), "ddagger": ("‡", r"\ddagger", 0),
    "ell": ("ℓ", r"\ell", 0), "hbar": ("ℏ", r"\hbar", 0), "aleph": ("ℵ", r"\aleph", 0),
    "wp": ("℘", r"\wp", 0), "Re": ("ℜ", r"\Re", 0), "Im": ("ℑ", r"\Im", 0),
    "uparrow": ("↑", r"\uparrow", 1), "downarrow": ("↓", r"\downarrow", 1),
    "larrow": ("←", r"\leftarrow", 1), "rarrow": ("→", r"\rightarrow", 1),
    "lrarrow": ("↔", r"\leftrightarrow", 1), "LARROW": ("⇐", r"\Leftarrow", 1),
    "RARROW": ("⇒", r"\Rightarrow", 1), "LRARROW": ("⇔", r"\Leftrightarrow", 1),
    "leftarrow": ("←", r"\leftarrow", 1), "rightarrow": ("→", r"\rightarrow", 1),
    "mapsto": ("↦", r"\mapsto", 1), "nearrow": ("↗", r"\nearrow", 1), "searrow": ("↘", r"\searrow", 1),
    "le": ("≤", r"\le", 1), "ge": ("≥", r"\ge", 1), "leq": ("≤", r"\le", 1), "geq": ("≥", r"\ge", 1),
    "ne": ("≠", r"\ne", 1), "neq": ("≠", r"\ne", 1), "ll": ("≪", r"\ll", 1), "gg": ("≫", r"\gg", 1),
    "pm": ("±", r"\pm", 0), "mp": ("∓", r"\mp", 0), "doteq": ("≐", r"\doteq", 1),
    "DIAMOND": ("◇", r"\diamond", 0), "diamond": ("⋄", r"\diamond", 0),
    "BOX": ("□", r"\square", 0), "CIRCLE": ("○", r"\bigcirc", 0), "box": ("□", r"\square", 0),
    "lbrace": ("{", r"\{", 0), "rbrace": ("}", r"\}", 0), "langle": ("⟨", r"\langle", 0),
    "rangle": ("⟩", r"\rangle", 0), "lceil": ("⌈", r"\lceil", 0), "rceil": ("⌉", r"\rceil", 0),
    "lfloor": ("⌊", r"\lfloor", 0), "rfloor": ("⌋", r"\rfloor", 0), "vert": ("|", r"|", 0),
    "VERT": ("‖", r"\|", 0), "dline": ("‖", r"\|", 0), "line": ("|", r"|", 0),
    "dag": ("†", r"\dagger", 0), "QED": ("∎", r"\blacksquare", 0), "smallint": ("∫", r"\int", 0),
    "SMALLSUM": ("∑", r"\sum", 0), "smallsum": ("∑", r"\sum", 0),
}
# 기호 글자열(긴 것부터 맞춘다)
OPERATORS = [
    ("<=>", "⇔", r"\Leftrightarrow", 1), ("<->", "↔", r"\leftrightarrow", 1),
    ("==>", "⟹", r"\Longrightarrow", 1), ("...", "…", r"\ldots", 0),
    ("<=", "≤", r"\le", 1), (">=", "≥", r"\ge", 1), ("!=", "≠", r"\ne", 1), ("==", "≡", r"\equiv", 1),
    ("->", "→", r"\to", 1), ("<-", "←", r"\leftarrow", 1), ("=>", "⇒", r"\Rightarrow", 1),
    ("+-", "±", r"\pm", 0), ("-+", "∓", r"\mp", 0), ("<<", "≪", r"\ll", 1), (">>", "≫", r"\gg", 1),
    ("||", "‖", r"\|", 0), ("=", "=", "=", 1), ("<", "<", "<", 1), (">", ">", ">", 1),
]
BIGOPS = {  # 이름 -> (유니코드, LaTeX)
    "int": ("∫", r"\int"), "dint": ("∬", r"\iint"), "tint": ("∭", r"\iiint"),
    "oint": ("∮", r"\oint"), "odint": ("∯", r"\oiint"), "otint": ("∰", r"\oiiint"),
    "sum": ("∑", r"\sum"), "prod": ("∏", r"\prod"), "coprod": ("∐", r"\coprod"),
    "union": ("⋃", r"\bigcup"), "inter": ("⋂", r"\bigcap"), "bigcup": ("⋃", r"\bigcup"),
    "bigcap": ("⋂", r"\bigcap"), "bigsqcup": ("⨆", r"\bigsqcup"), "bigoplus": ("⨁", r"\bigoplus"),
    "bigotimes": ("⨂", r"\bigotimes"), "bigodot": ("⨀", r"\bigodot"), "biguplus": ("⨄", r"\biguplus"),
    "lim": ("lim", r"\lim"), "Lim": ("lim", r"\lim"), "max": ("max", r"\max"), "min": ("min", r"\min"),
    "sup": ("sup", r"\sup"), "liminf": ("lim inf", r"\liminf"), "limsup": ("lim sup", r"\limsup"),
}
FUNCS = {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh",
         "tanh", "coth", "log", "ln", "lg", "exp", "det", "gcd", "lcm", "mod", "arg", "dim",
         "ker", "hom", "deg", "Pr", "sgn"}
FUNCS.discard("deg")  # deg는 ° 기호
ACCENTS = {  # 이름 -> (결합 문자, LaTeX)
    "bar": ("̅", r"\overline"), "overline": ("̅", r"\overline"),
    "hat": ("̂", r"\hat"), "check": ("̌", r"\check"), "tilde": ("̃", r"\tilde"),
    "vec": ("⃗", r"\vec"), "dyad": ("⃡", r"\overleftrightarrow"),
    "dot": ("̇", r"\dot"), "ddot": ("̈", r"\ddot"), "acute": ("́", r"\acute"),
    "grave": ("̀", r"\grave"), "arch": ("̑", r"\overset{\frown}"),
    "under": ("̲", r"\underline"), "underline": ("̲", r"\underline"),
}
FONT_WORDS = {"rm", "it", "bold", "RM", "IT", "BOLD", "Rm", "It", "Bold"}
MATRICES = {"matrix": ("", "", "matrix"), "pmatrix": ("(", ")", "pmatrix"),
            "bmatrix": ("[", "]", "bmatrix"), "dmatrix": ("|", "|", "vmatrix")}
PILES = {"pile", "lpile", "rpile", "eqalign", "stack"}
SUP_CHARS = dict(zip("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ"))
SUB_CHARS = dict(zip("0123456789+-=()aeoxhklmnpstijruv", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ"))
SUP_CHARS["′"] = "′"


# ---------------------------------------------------------------- 낱말 나누기
_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"[^"]*"?)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<word>[A-Za-z]+)
  | (?P<op><=>|<->|==>|\.\.\.|<=|>=|!=|==|->|<-|=>|\+-|-\+|<<|>>|\|\|)
  | (?P<ch>.)
""", re.X | re.S)


def tokenize(s):
    out = []
    for m in _TOKEN.finditer(s):
        kind = m.lastgroup
        out.append((kind, m.group()))
    return out


# ---------------------------------------------------------------- 나무 만들기
# 마디: ("seq", [..]) ("atom", text, latex, cls) ("sup", base, x) ("sub", base, x)
#      ("frac", a, b, bar) ("sqrt", x, n) ("bigop", name, lower, upper) ("accent", name, x)
#      ("matrix", kind, rows) ("cases", rows) ("pile", rows) ("text", s) ("space",)
#  cls: "ord" 보통, "rel" 관계 기호, "bin" 연산, "func" 함수 이름, "open"/"close" 괄호, "punct" 쉼표
WS = ("ws",)


class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self, skip_ws=False):
        j = self.i
        while skip_ws and j < len(self.t) and self.t[j][0] == "ws":
            j += 1
        return self.t[j] if j < len(self.t) else (None, None)

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def skip_ws(self):
        while self.i < len(self.t) and self.t[self.i][0] == "ws":
            self.i += 1

    # 띄어쓰기로 나뉜 덩어리 하나: {묶음}이면 그것만, 아니면 다음 띄어쓰기까지
    def chunk(self):
        self.skip_ws()
        kind, val = self.peek()
        if kind is None:
            return ("seq", [])
        if val == "{":
            self.take()
            g = self.group("}")
            # 묶음 바로 뒤에 ^ _ 가 붙어 있으면 이어서 처리
            items = self._postfix([g])
            return items[0] if len(items) == 1 else ("seq", items)
        items = []
        depth = 0
        while True:
            kind, val = self.peek()
            if kind is None or kind == "ws" or val in ("}", "#", "&"):
                break
            if val in ("(", "["):
                depth += 1
            elif val in (")", "]"):
                if depth == 0:   # 짝 없는 닫는 괄호 앞에서 멈춘다: f(x_n) 의 ) 는 첨자가 아니다
                    break
                depth -= 1
            if kind == "word" and val in ("over", "atop", "from", "to", "of", "right", "RIGHT"):
                break
            items.append(self.element(items))
        items = [x for x in items if x is not WS]
        return items[0] if len(items) == 1 else ("seq", items)

    def _postfix(self, items):
        while True:
            kind, val = self.peek()
            if val in ("^", "_") or (kind == "word" and val in ("SUP", "SUB", "sup", "sub") and items):
                self.take()
                arg = self.chunk()
                base = items.pop() if items else ("seq", [])
                items.append(("sup" if val in ("^", "SUP", "sup") else "sub", base, arg))
            else:
                return items

    def group(self, closer):
        """closer('}' 또는 None=끝)까지. # 과 & 은 matrix 쪽에서 나눈다."""
        items = []
        while True:
            kind, val = self.peek()
            if kind is None:
                break
            if val == closer:
                self.take()
                break
            if closer is not None and val == "}":
                self.take()
                break
            if kind == "ws":
                self.take()
                items.append(WS)
                continue
            if val in ("^", "_") or (kind == "word" and val in ("SUP", "SUB", "sup", "sub") and items):
                while items and items[-1] is WS:
                    items.pop()
                items[:] = self._postfix(items)
                continue
            if kind == "word" and val in ("over", "atop", "OVER", "ATOP"):
                self.take()
                while items and items[-1] is WS:
                    items.pop()
                # 분자 = 바로 앞 띄어쓰기 뒤부터
                j = len(items)
                while j > 0 and items[j - 1] is not WS:
                    j -= 1
                num = [x for x in items[j:] if x is not WS]
                del items[j:]
                den = self.chunk()
                items.append(("frac", ("seq", num), den, val.lower() == "over"))
                continue
            items.append(self.element(items))
            items[:] = self._postfix(items)
        return ("seq", items)

    def element(self, items):
        kind, val = self.take()
        if kind == "ws":
            return WS
        if kind == "str":
            return ("text", val.strip('"'))
        if kind == "num":
            return ("atom", val, val, "ord")
        if kind == "op":
            for src, u, lx, rel in OPERATORS:
                if src == val:
                    return ("atom", u, lx, "rel" if rel else "bin")
        if kind == "ch":
            if val == "{":
                g = self.group("}")
                return g
            if val in "~":
                return ("space", " ")
            if val == "`":
                return ("space", "`")
            if val in "#&":
                return ("sep", val)
            if val == "-":
                return ("atom", "-", "-", "bin")
            if val in "+*/":
                return ("atom", "·" if val == "*" else val, r"\ast" if val == "*" else val, "bin")
            if val in "=<>":
                return ("atom", val, val, "rel")
            if val in "([":
                return ("atom", val, val, "open")
            if val in ")]":
                return ("atom", val, val, "close")
            if val in ",;":
                return ("atom", val, val, "punct")
            if val == "'":
                return ("atom", "′", "'", "ord")
            if val == "\\":
                return ("atom", "", "", "ord")
            return ("atom", val, val, "ord")
        # 낱말
        w = _canon(val)
        if w in FONT_WORDS:
            return ("space", "")
        if w in GREEK:
            return ("atom", GREEK[w], "\\" + (w.lower() if not w.isupper() and not w[0].isupper()
                                             else w.capitalize()), "ord")
        if w in ("sqrt", "SQRT"):
            return ("sqrt", self.chunk(), None)
        if w in ("root", "ROOT"):
            n = self.chunk()
            self.skip_ws()
            if self.peek()[1] == "of":
                self.take()
            return ("sqrt", self.chunk(), n)
        if w in ACCENTS:
            return ("accent", w, self.chunk())
        if w in BIGOPS:
            lower = upper = None
            while True:
                kind2, v2 = self.peek(skip_ws=True)
                if v2 in ("_", "from", "SUB", "sub") and lower is None:
                    self.skip_ws(); self.take(); lower = self.chunk()
                elif v2 in ("^", "to", "SUP", "sup") and upper is None:
                    self.skip_ws(); self.take(); upper = self.chunk()
                else:
                    break
            return ("bigop", w, lower, upper)
        if w in MATRICES or w in PILES or w in ("cases", "CASES"):
            self.skip_ws()
            rows = []
            if self.peek()[1] == "{":
                self.take()
                body = self.group("}")
                rows = _split_rows(body)
            if w in MATRICES:
                return ("matrix", w, rows)
            if w in PILES:
                return ("pile", rows)
            return ("cases", rows)
        if w in ("left", "LEFT", "right", "RIGHT", "big", "BIG"):
            self.skip_ws()
            k2, v2 = self.take() if self.i < len(self.t) else (None, "")
            if k2 == "word":
                if v2 in SYMBOLS:
                    u, lx, _ = SYMBOLS[v2]
                    return ("atom", u, lx, "open" if w.lower() == "left" else "close")
                return ("atom", "", "", "ord")
            if v2 == ".":
                return ("atom", "", "", "ord")
            return ("atom", v2, {"{": r"\{", "}": r"\}"}.get(v2, v2),
                    "open" if w.lower() == "left" else "close")
        if w in ("COLOR", "color"):
            self.chunk()  # {r,g,b}
            return self.chunk()
        if w in ("rel", "buildrel"):
            sym = self.chunk(); top = self.chunk()
            self.skip_ws()
            bottom = self.chunk() if self.peek()[1] == "{" else None
            return ("rel", sym, top, bottom)
        if w in SYMBOLS:
            u, lx, rel = SYMBOLS[w]
            return ("atom", u, lx, "rel" if rel else "ord")
        if w in FUNCS:
            return ("atom", w, "\\" + w if w not in ("lcm", "sgn") else r"\operatorname{%s}" % w, "func")
        return ("atom", w, w, "ord")


_KNOWN = set(GREEK) | set(SYMBOLS) | set(BIGOPS) | FUNCS | set(ACCENTS) | FONT_WORDS |     set(MATRICES) | PILES | {"sqrt", "root", "cases", "left", "right", "big", "color", "rel", "buildrel"}
_LOWER = {}
for _k in sorted(_KNOWN):
    _LOWER.setdefault(_k.lower(), _k)


def _canon(w):
    if w in _KNOWN:
        return w
    return _LOWER.get(w.lower(), w)


def _split_rows(body):
    rows, row, cell = [], [], []
    for x in body[1]:
        if isinstance(x, tuple) and x[0] == "sep":
            if x[1] == "&":
                row.append(("seq", cell)); cell = []
            else:
                row.append(("seq", cell)); rows.append(row); row, cell = [], []
        else:
            cell.append(x)
    if cell or row:
        row.append(("seq", cell)); rows.append(row)
    return rows


def parse(script):
    p = _Parser(tokenize(script))
    return p.group(None)


# ---------------------------------------------------------------- 유니코드 한 줄 글
_SCRIPTS = "₀₁₂₃₄₅₆₇₈₉₊₋₌ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼ⁿⁱ′̂̃̅̇̈⃗"
_PLAIN = re.compile(r"[0-9]+(?:\.[0-9]+)?|[√∛∜]?(?:[0-9]+|[^\W\d_][%s]*)|∞" % _SCRIPTS)


def _plain(s):
    """괄호를 안 씌워도 되는 한 덩어리인가: 수 하나, 글자 하나(+첨자·프라임), √글자 하나"""
    return bool(_PLAIN.fullmatch(s))


def _paren(s):
    if not s:
        return "()"
    if _plain(s):
        return s
    if s[0] in "([{" and _balanced_wrap(s):
        return s
    return "(" + s + ")"


def _balanced_wrap(s):
    pairs = {"(": ")", "[": "]", "{": "}"}
    if s[-1] != pairs.get(s[0]):
        return False
    depth = 0
    for i, c in enumerate(s):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0 and i != len(s) - 1:
                return False
    return True


def _script(s, table, mark):
    s = s.replace(" ", "")
    if s and all(c in table for c in s):
        return "".join(table[c] for c in s)
    if len(s) == 1 or re.fullmatch(r"[0-9.]+", s) or (s[0] in "([{" and _balanced_wrap(s)):
        return mark + s
    return mark + "(" + s + ")"


def _u(node):
    """마디 -> (글, 종류)"""
    t = node[0]
    if t == "seq":
        return _u_seq(node[1]), "ord"
    if t == "atom":
        return node[1], node[3]
    if t == "text":
        return node[1], "ord"
    if t == "space":
        return node[1], "space"
    if t == "sep":
        return " ", "space"
    if t == "sup":
        b, bk = _u(node[1]); x, _ = _u(node[2])
        return _base(b) + _script(x, SUP_CHARS, "^"), "func" if bk == "func" else "ord"
    if t == "sub":
        b, bk = _u(node[1]); x, _ = _u(node[2])
        if node[1][0] == "bigop":
            return b, "ord"
        return _base(b) + _script(x, SUB_CHARS, "_"), "func" if bk == "func" else "ord"
    if t == "frac":
        a, _ = _u(node[1]); b, _ = _u(node[2])
        sep = "/" if node[3] else " atop "
        return _paren(a) + sep + _paren(b), "frac"
    if t == "sqrt":
        x, _ = _u(node[1])
        inner = x if _plain(x) else "(" + x + ")"
        if node[2] is None:
            return "√" + inner, "ord"
        n, _ = _u(node[2])
        if n == "3":
            return "∛" + inner, "ord"
        if n == "4":
            return "∜" + inner, "ord"
        return _script(n, SUP_CHARS, "^") + "√" + inner, "ord"
    if t == "bigop":
        sym = BIGOPS[node[1]][0]
        lo = _u(node[2])[0] if node[2] is not None else None
        hi = _u(node[3])[0] if node[3] is not None else None
        s = sym
        if lo:
            s += _script(lo, SUB_CHARS, "_")
        if hi:
            s += _script(hi, SUP_CHARS, "^")
        return s, "func" if sym.isalpha() or lo or hi else "ord"
    if t == "accent":
        mark = ACCENTS[node[1]][0]
        x, _ = _u(node[2])
        if not x:
            return mark.strip(), "ord"
        if node[1] in ("bar", "overline", "under", "underline"):
            return "".join(c + mark for c in x), "ord"
        return x + mark, "ord"
    if t == "matrix":
        l, r, _ = MATRICES[node[1]]
        rows = ["[" + ", ".join(_u(c)[0] for c in row) + "]" for row in node[2]]
        body = ", ".join(rows)
        return (l or "[") + body + (r or "]"), "ord"
    if t == "pile":
        return "; ".join(" ".join(_u(c)[0] for c in row) for row in node[1]), "ord"
    if t == "cases":
        parts = [" ".join(c for c in (_u(x)[0].strip() for x in row) if c) for row in node[1]]
        return "{ " + "; ".join(parts) + " }", "ord"
    if t == "rel":
        sym, _ = _u(node[1]); top, _ = _u(node[2])
        return sym + (f"({top})" if top else ""), "rel"
    return "", "ord"


def _base(b):
    # 글자만 이어진 이름(kmS, MG)은 한글 수식에서도 통째로 첨자가 붙으므로 괄호 없이 둔다
    if _plain(b) or len(b) <= 1 or b[-1] in ")]}" or re.fullmatch(r"[^\W\d_]+", b):
        return b
    return "(" + b + ")"


def _u_seq(items):
    out = []          # (글, 종류, 앞에 띄어쓰기가 있었나)
    gap = False
    for x in items:
        if x is WS:
            continue
        s, k = _u(x)
        if k == "space":
            if s == "`" or s == "":
                gap = True
            else:
                out.append((s, k, False))
                gap = False
            continue
        out.append((s, k, gap))
        gap = False
    text = ""
    prev = None
    for s, k, gap in out:
        if not s:
            continue
        if prev is not None:
            ps, pk = prev
            # 분수 바로 뒤에 글자가 붙으면 분수를 괄호로 묶는다: 1/2ab -> (1/2)ab
            if pk == "frac" and (s[:1].isalnum() or s[:1] in "√(") and text.endswith(ps):
                text = text[: len(text) - len(ps)] + "(" + ps + ")"
            if k == "rel" or pk == "rel":
                if not text.endswith(" "):
                    text += " "
            elif pk == "punct" and ps == ",":
                text += " "
            elif pk == "func" and (s[:1].isalnum() or s[:1] in "√("):
                text += " "
            elif k == "func" and _alnum_end(ps):
                text += " "
            elif gap and _alnum_end(ps) and _alnum_start(s):
                text += " "
        text += s
        prev = (s, k)
    return re.sub(r" {2,}", " ", text).strip() if out else ""


def _alnum_end(s):
    return bool(s) and (s[-1].isalnum() or s[-1] in "′²³¹⁰⁴⁵⁶⁷⁸⁹ⁿⁱ)")


def _alnum_start(s):
    return bool(s) and (s[0].isalnum() or s[0] in "√∫∑∏(")


def to_unicode(script):
    try:
        return _u(parse(script))[0].strip()
    except Exception:
        return script.strip()


# ---------------------------------------------------------------- LaTeX
def _l(node):
    t = node[0]
    if t == "seq":
        parts = []
        for x in node[1]:
            if x is WS:
                continue
            s = _l(x)
            if not s:
                continue
            if parts and s and parts[-1] and parts[-1][-1].isalpha() and parts[-1].startswith("\\") \
                    and s[0].isalnum():
                parts.append(" ")
            parts.append(s)
        return "".join(parts)
    if t == "atom":
        return node[2]
    if t == "text":
        return r"\text{" + node[1] + "}"
    if t == "space":
        return r"\," if node[1] == " " else ""
    if t == "sep":
        return " "
    if t == "sup":
        return _lb(node[1]) + "^{" + _l(node[2]) + "}"
    if t == "sub":
        return _lb(node[1]) + "_{" + _l(node[2]) + "}"
    if t == "frac":
        cmd = r"\frac" if node[3] else r"\genfrac{}{}{0pt}{}"
        return cmd + "{" + _l(node[1]) + "}{" + _l(node[2]) + "}"
    if t == "sqrt":
        n = "[" + _l(node[2]) + "]" if node[2] is not None else ""
        return r"\sqrt" + n + "{" + _l(node[1]) + "}"
    if t == "bigop":
        s = BIGOPS[node[1]][1]
        if node[2] is not None:
            s += "_{" + _l(node[2]) + "}"
        if node[3] is not None:
            s += "^{" + _l(node[3]) + "}"
        return s + " "
    if t == "accent":
        return ACCENTS[node[1]][1] + "{" + _l(node[2]) + "}"
    if t == "matrix":
        env = MATRICES[node[1]][2]
        rows = r" \\ ".join(" & ".join(_l(c) for c in row) for row in node[2])
        return r"\begin{%s}%s\end{%s}" % (env, rows, env)
    if t == "pile":
        return r"\begin{matrix}" + r" \\ ".join(" ".join(_l(c) for c in row) for row in node[1]) + r"\end{matrix}"
    if t == "cases":
        rows = r" \\ ".join(" & ".join(_l(c) for c in row) for row in node[1])
        return r"\begin{cases}" + rows + r"\end{cases}"
    if t == "rel":
        return r"\overset{" + _l(node[2]) + "}{" + _l(node[1]) + "}"
    return ""


def _lb(node):
    s = _l(node)
    return s if len(s) <= 1 or node[0] in ("atom", "accent") else "{" + s + "}"


def to_latex(script):
    try:
        return re.sub(r"\s+", " ", _l(parse(script))).strip()
    except Exception:
        return script.strip()


def convert(script, mode="unicode"):
    if mode == "none":          # 수식은 모양만 두고 복사되지 않게
        return ""
    if mode == "latex":
        return to_latex(script)
    if mode == "hwp":
        return re.sub(r"\s+", " ", script).strip()
    return to_unicode(script)


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:]:
        print(to_unicode(s), "   |   ", to_latex(s))
