"""한컴 PDF의 쪽 내용을 다시 써서 수식을 '복사되는 글'로 만든다.

원리
  A = 원본 그대로 내보낸 PDF, B = 수식마다 표식 색을 입혀 내보낸 PDF.
  두 PDF는 연산 순서가 똑같고 색 숫자만 다르다. B에서 각 그리기 연산이 몇 번 수식인지 읽고,
  A를 다시 쓴다:
    - 수식 글자(HancomEQN 등, 복사하면 사용자 영역 문자로 깨지는 글자)는 그 글꼴의 윤곽선을 꺼내
      똑같은 모양의 벡터 도형으로 바꾼다 -> 보기에는 그대로, 글자로는 안 잡힌다.
    - 수식이 시작되는 자리(스트림 순서 = 복사 순서)에 보이지 않는 글자(Tr 3)로 수식 글을 넣는다.
      크기·기준선은 같은 줄 본문 글자에 맞추고 가로 폭은 수식 폭에 맞춘다.
  그 밖의 본문 글자는 바이트 그대로 둔다.
"""
import io
import math
import zlib
from collections import defaultdict

import pikepdf
from pikepdf import Name, Operator

# ---------------------------------------------------------------- 행렬
I = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mul(m, n):
    """m 다음 n (PDF 식: [m] x [n])"""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


def inv(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return I
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_))


def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def fmt(v):
    if abs(v) < 5e-7:
        return "0"
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


def mat_str(m):
    return " ".join(fmt(v) for v in m)


# ---------------------------------------------------------------- 글꼴 윤곽선
class _PathPen:
    def __init__(self):
        from fontTools.pens.basePen import BasePen

        class P(BasePen):
            def __init__(s):
                super().__init__(None)
                s.parts = []

            def _moveTo(s, p):
                s.parts.append("%s %s m" % (fmt(p[0]), fmt(p[1])))

            def _lineTo(s, p):
                s.parts.append("%s %s l" % (fmt(p[0]), fmt(p[1])))

            def _curveToOne(s, p1, p2, p3):
                s.parts.append("%s %s %s %s %s %s c" % tuple(fmt(v) for v in (*p1, *p2, *p3)))

            def _closePath(s):
                s.parts.append("h")

        self.pen = P()


def _name_str(obj):
    """글꼴 이름에 CP949 바이트(한글 글꼴명)가 들어 있어도 죽지 않게"""
    try:
        return str(obj)
    except UnicodeDecodeError:
        raw = obj.unparse() if hasattr(obj, "unparse") else bytes(obj)
        try:
            import re
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
            return raw.decode("cp949")
        except Exception:
            return raw.decode("latin-1")


class FontInfo:
    """쪽 자원의 글꼴 하나: 코드 -> 글리프 윤곽선, 너비, 유니코드."""

    def __init__(self, fobj):
        self.obj = fobj
        self.subtype = str(fobj.get("/Subtype", ""))
        self.name = _name_str(fobj.get("/BaseFont", ""))
        self.two_byte = self.subtype == "/Type0"
        self.vertical = False
        self.widths = {}
        self.dw = 1000.0
        self.first_char = 0
        self.cid2gid = None          # None = Identity
        self.glyphs = None           # 윤곽선을 그릴 함수(gid -> (경로 글, bbox))
        self.upm = 1000.0
        self.font_matrix_scale = 1 / 1000.0
        self.tounicode = {}
        self._cache = {}
        self.error = None
        try:
            self._load()
        except Exception as e:  # 윤곽선을 못 꺼내도 글은 읽을 수 있게
            self.error = "%s: %s" % (type(e).__name__, e)
        try:
            self.tounicode = parse_tounicode(fobj.get("/ToUnicode"))
        except Exception:
            self.tounicode = {}

    def _load(self):
        f = self.obj
        if self.two_byte:
            enc = str(f.get("/Encoding", ""))
            self.vertical = enc.endswith("-V")
            if enc not in ("/Identity-H", "/Identity-V"):
                raise ValueError("지원하지 않는 CMap %s" % enc)
            desc = f.DescendantFonts[0]
            self.dw = float(desc.get("/DW", 1000))
            w = desc.get("/W")
            if w is not None:
                i = 0
                w = list(w)
                while i < len(w):
                    c0 = int(w[i])
                    if isinstance(w[i + 1], pikepdf.Array):
                        for k, v in enumerate(w[i + 1]):
                            self.widths[c0 + k] = float(v)
                        i += 2
                    else:
                        c1, v = int(w[i + 1]), float(w[i + 2])
                        for c in range(c0, c1 + 1):
                            self.widths[c] = v
                        i += 3
            m = desc.get("/CIDToGIDMap")
            if isinstance(m, pikepdf.Stream):
                raw = m.read_bytes()
                self.cid2gid = [raw[i] << 8 | raw[i + 1] for i in range(0, len(raw) - 1, 2)]
            fd = desc.FontDescriptor
            dsub = str(desc.get("/Subtype"))
        else:
            self.first_char = int(f.get("/FirstChar", 0))
            for k, v in enumerate(f.get("/Widths", [])):
                self.widths[self.first_char + k] = float(v)
            self.dw = 0.0
            fd = f.get("/FontDescriptor")
            dsub = self.subtype
            if fd is None:
                raise ValueError("FontDescriptor 없음(기본 14 글꼴)")
        if "/FontFile2" in fd:
            from fontTools.ttLib import TTFont
            tt = TTFont(io.BytesIO(fd.FontFile2.read_bytes()), lazy=True)
            self.upm = float(tt["head"].unitsPerEm)
            order = tt.getGlyphOrder()
            gs = tt.getGlyphSet()
            simple_cmap = None
            if not self.two_byte:
                simple_cmap = {}
                if "cmap" in tt:
                    for sub in tt["cmap"].tables:
                        if (sub.platformID, sub.platEncID) in ((3, 0), (1, 0), (3, 1)):
                            for code, gname in sub.cmap.items():
                                simple_cmap.setdefault(code & 0xFF if sub.platEncID == 0 and
                                                       sub.platformID == 3 else code, gname)

            def draw(code):
                if self.two_byte:
                    gid = self.cid2gid[code] if self.cid2gid is not None and code < len(self.cid2gid) else code
                    if gid >= len(order):
                        return None
                    gname = order[gid]
                else:
                    gname = simple_cmap.get(code) or simple_cmap.get(0xF000 + code)
                    if gname is None:
                        return None
                pen = _PathPen().pen
                gs[gname].draw(pen)
                return pen.parts
            self.glyphs = draw
            self.font_matrix_scale = 1.0 / self.upm
        elif "/FontFile3" in fd:
            from fontTools.cffLib import CFFFontSet
            cff = CFFFontSet()
            cff.decompile(io.BytesIO(fd.FontFile3.read_bytes()), None)
            top = cff[cff.fontNames[0]]
            cs = top.CharStrings
            fm = getattr(top, "FontMatrix", [0.001, 0, 0, 0.001, 0, 0])
            self.font_matrix_scale = fm[0]
            cid_keyed = hasattr(top, "ROS")
            charset = top.charset

            def draw(code):
                if cid_keyed:
                    gname = "cid%05d" % code
                else:
                    gid = code
                    if gid >= len(charset):
                        return None
                    gname = charset[gid]
                if gname not in cs:
                    return None
                pen = _PathPen().pen
                cs[gname].draw(pen)
                return pen.parts
            self.glyphs = draw
        else:
            raise ValueError("내장 글꼴 파일 없음 (%s)" % dsub)

    def codes(self, s):
        b = bytes(s)
        if self.two_byte:
            return [b[i] << 8 | b[i + 1] for i in range(0, len(b) - 1, 2)]
        return list(b)

    def width(self, code):
        return self.widths.get(code, self.dw) / 1000.0

    def path(self, code):
        if code not in self._cache:
            parts = self.glyphs(code) if self.glyphs else None
            self._cache[code] = " ".join(parts) if parts else ("" if parts is not None else None)
        return self._cache[code]

    def unicode(self, code):
        return self.tounicode.get(code)


def parse_tounicode(stream):
    out = {}
    if stream is None:
        return out
    data = stream.read_bytes().decode("latin-1")
    import re
    def hexs(h):
        h = h.strip("<>")
        if not h:
            return ""
        bs = bytes.fromhex(h)
        return bs.decode("utf-16-be", "replace")
    for block in re.findall(r"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]*)>", block):
            out[int(src, 16)] = hexs(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", data, re.S):
        for m in re.finditer(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*(\[[^\]]*\]|<[0-9a-fA-F]*>)", block):
            a, b, dst = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
            if dst.startswith("["):
                for k, h in enumerate(re.findall(r"<([0-9a-fA-F]*)>", dst)):
                    out[a + k] = hexs(h)
            else:
                base = bytes.fromhex(dst.strip("<>"))
                for k in range(b - a + 1):
                    v = bytearray(base)
                    v[-1] = (v[-1] + k) & 0xFF
                    out[a + k] = bytes(v).decode("utf-16-be", "replace")
    return out


def is_bad_unicode(u):
    if u is None or u == "":
        return True
    for ch in u:
        o = ord(ch)
        if o in (0xFFFF, 0xFFFD, 0xFFFE) or 0xE000 <= o <= 0xF8FF or o < 0x20 and ch not in "\t":
            return True
    return False


# ---------------------------------------------------------------- 보이지 않는 글꼴
def make_invisible_font(pdf):
    """글리프가 비어 있는 CID 글꼴. 코드 = UTF-16 값이고 ToUnicode가 그대로 돌려준다."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "space"])
    fb.setupCharacterMap({32: "space"})
    empty = TTGlyphPen(None).glyph()
    # 글리프에 상자 윤곽을 둔다(Tr 3 이라 그려지지는 않음). 빈 글리프면 PDFium이 글자 상자를 0으로 보고
    # 한 글자짜리 글(α, x 같은 수식)을 통째로 버린다.
    box = TTGlyphPen(None)
    box.moveTo((0, -200)); box.lineTo((0, 800)); box.lineTo((500, 800)); box.lineTo((500, -200))
    box.closePath()
    fb.setupGlyf({".notdef": empty, "space": box.glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "space": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "HwpPdfText", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    from fontTools.misc.timeTools import timestampNow
    fb.updateHead(created=timestampNow(), modified=timestampNow())
    buf = io.BytesIO()
    fb.save(buf)
    fontfile = pikepdf.Stream(pdf, buf.getvalue())
    fontfile.Length1 = len(buf.getvalue())
    cidmap = pikepdf.Stream(pdf, zlib.compress(b"\x00\x01" * 65536, 9))
    cidmap.Filter = Name.FlateDecode
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /HwpPdf-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    hi = list(range(256))
    for start in range(0, 256, 100):
        chunk = hi[start:start + 100]
        lines.append("%d beginbfrange" % len(chunk))
        for h in chunk:
            lines.append("<%02X00> <%02XFF> <%02X00>" % (h, h, h))
        lines.append("endbfrange")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    tou = pikepdf.Stream(pdf, zlib.compress("\n".join(lines).encode(), 9))
    tou.Filter = Name.FlateDecode
    desc = pdf.make_indirect(pikepdf.Dictionary(
        Type=Name.FontDescriptor, FontName=Name("/HwpPdfText"), Flags=4,
        FontBBox=[0, -200, 500, 800], ItalicAngle=0, Ascent=800, Descent=-200,
        CapHeight=700, StemV=80, FontFile2=pdf.make_indirect(fontfile)))
    cid = pdf.make_indirect(pikepdf.Dictionary(
        Type=Name.Font, Subtype=Name.CIDFontType2, BaseFont=Name("/HwpPdfText"),
        CIDSystemInfo=pikepdf.Dictionary(Registry="Adobe", Ordering="Identity", Supplement=0),
        FontDescriptor=desc, DW=500, CIDToGIDMap=pdf.make_indirect(cidmap)))
    return pdf.make_indirect(pikepdf.Dictionary(
        Type=Name.Font, Subtype=Name.Type0, BaseFont=Name("/HwpPdfText"),
        Encoding=Name("/Identity-H"), DescendantFonts=[cid], ToUnicode=pdf.make_indirect(tou)))


# ---------------------------------------------------------------- 표식 색 읽기
MARK_R = 2


def marker_color(eq_index):
    """0부터 센 수식 번호 -> 한글 Color 값(BGR 정수)과 (r,g,b)"""
    g, b = divmod(eq_index, 250)
    b += 3
    r = MARK_R
    return r | g << 8 | b << 16, (r, g, b)


def decode_marker(comps):
    if comps is None or len(comps) != 3:
        return None
    r, g, b = (int(round(float(v) * 255)) for v in comps)
    if r != MARK_R or b < 3:
        return None
    return g * 250 + (b - 3)


PAINT = {"S": "s", "s": "s", "f": "f", "F": "f", "f*": "f", "B": "f", "B*": "f", "b": "f", "b*": "f"}
SHOW = {"Tj", "TJ", "'", '"'}
PATH_CONS = {"m", "l", "c", "v", "y", "h", "re"}


def scan_markers(ops):
    """B 쪽 연산들 -> {연산 번호: 수식 번호}"""
    stack = []
    fill = stroke = None
    tr = 0
    out = {}
    for i, inst in enumerate(ops):
        if isinstance(inst, pikepdf.ContentStreamInlineImage):
            continue
        operands, op = inst
        op = str(op)
        if op == "q":
            stack.append((fill, stroke, tr))
        elif op == "Q":
            if stack:
                fill, stroke, tr = stack.pop()
        elif op in ("rg", "sc", "scn"):
            fill = list(operands) if len(operands) == 3 else None
        elif op in ("RG", "SC", "SCN"):
            stroke = list(operands) if len(operands) == 3 else None
        elif op in ("g", "k", "cs"):
            fill = None
        elif op in ("G", "K", "CS"):
            stroke = None
        elif op == "Tr":
            tr = int(operands[0])
        elif op in SHOW:
            k = decode_marker(stroke if tr in (1, 5) else fill)
            if k is None and tr in (2, 6):
                k = decode_marker(stroke)
            if k is not None:
                out[i] = k
        elif op in PAINT:
            k = decode_marker(stroke if PAINT[op] == "s" else fill)
            if k is None and op in ("B", "B*", "b", "b*"):
                k = decode_marker(stroke)
            if k is not None:
                out[i] = k
    return out


_COLOR_CLASS = {"g": "fill", "rg": "fill", "k": "fill", "sc": "fill", "scn": "fill",
                "G": "stroke", "RG": "stroke", "K": "stroke", "SC": "stroke", "SCN": "stroke"}


def same_structure(ops_a, ops_b):
    """색 연산(g/rg 등)만 다르고 나머지 연산 순서가 같은가"""
    if len(ops_a) != len(ops_b):
        return False
    for a, b in zip(ops_a, ops_b):
        ia = isinstance(a, pikepdf.ContentStreamInlineImage)
        ib = isinstance(b, pikepdf.ContentStreamInlineImage)
        if ia != ib:
            return False
        if not ia:
            oa, ob = str(a[1]), str(b[1])
            if oa != ob and _COLOR_CLASS.get(oa, oa) != _COLOR_CLASS.get(ob, ob):
                return False
    return True


_NORM_OK = {"Tf", "Tm", "TJ", "Tj", "Tc", "Tw", "Tz", "TL", "Ts", "Tr", "w", "J", "j", "M", "d", "ri", "i",
            "g", "rg", "k", "G", "RG", "K", "cs", "CS", "sc", "scn", "SC", "SCN", "gs", "BDC", "BMC", "EMC"}


def _normalizable_blocks(ops, marks):
    """배율을 옮겨 써도 되는 BT 번호들: 수식이 없고 줄 이동 연산(Td, T*, ', ")이 없는 글자 덩어리"""
    out = set()
    start = None
    ok = True
    for i, inst in enumerate(ops):
        if isinstance(inst, pikepdf.ContentStreamInlineImage):
            ok = False
            continue
        op = str(inst[1])
        if op == "BT":
            start, ok = i, True
        elif op == "ET":
            if start is not None and ok:
                out.add(start)
            start = None
        elif start is not None and (op not in _NORM_OK or i in marks):
            ok = False
    return out


# ---------------------------------------------------------------- 쪽 다시 쓰기
class GState:
    __slots__ = ("ctm", "tc", "tw", "th", "tl", "font", "fs", "tr", "ts", "lw")

    def __init__(self):
        self.ctm, self.tc, self.tw, self.th, self.tl = I, 0.0, 0.0, 1.0, 0.0
        self.font, self.fs, self.tr, self.ts, self.lw = None, 0.0, 0, 0.0, 1.0

    def copy(self):
        g = GState()
        for k in self.__slots__:
            setattr(g, k, getattr(self, k))
        return g


class EqGroup:
    def __init__(self, k):
        self.k = k
        self.bbox = None            # 사용자 공간 [x0, y0, x1, y1]
        self.first = None           # 처음 그린 순서 번호
        self.last = None
        self.placeholder = None     # out 안 자리
        self.ctm = I
        self.glyphs = 0
        self.paths = 0

    def add_pts(self, pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if not xs:
            return
        b = [min(xs), min(ys), max(xs), max(ys)]
        if self.bbox is None:
            self.bbox = b
        else:
            self.bbox = [min(self.bbox[0], b[0]), min(self.bbox[1], b[1]),
                         max(self.bbox[2], b[2]), max(self.bbox[3], b[3])]


def _num(x):
    return float(x)


class PageRewriter:
    def __init__(self, pdf, page, marks, font_cache, inv_font_name):
        self.pdf = pdf
        self.page = page
        self.marks = marks
        self.font_cache = font_cache
        self.inv_font_name = inv_font_name
        self.fonts = {}
        res = page.obj.get("/Resources") or pikepdf.Dictionary()
        fdict = res.get("/Font") or pikepdf.Dictionary()
        for name, fobj in fdict.items():
            key = fobj.objgen if fobj.is_indirect else id(fobj)
            if key not in font_cache:
                font_cache[key] = FontInfo(fobj)
            self.fonts[name] = font_cache[key]
        self.groups = {}
        self.body_glyphs = []        # (순서, x0, x1, 기준선 y, 크기) 같은 줄 맞추기용
        self.text_runs = []          # (글꼴 키, 코드, 유니코드) 본문 글자 순서 — 깨진 글자 고치기용
        self.problems = []

    # ----------------------------------------------------------------
    def rewrite(self, ops):
        out = []                      # 원래 연산 또는 ("raw", bytes) 또는 ("ph", k)
        g = GState()
        stack = []
        in_text = opened = dirty = False
        tm = tlm = I
        path_start = None
        path_pts = []
        order = 0

        def raw(s):
            out.append(("raw", s.encode("latin-1") if isinstance(s, str) else s))

        normalizable = _normalizable_blocks(ops, self.marks)
        norm = None                   # (sx, sy): 이 글자 덩어리의 축소 배율을 글자 크기로 옮겨 쓰는 중

        def emit_state(g, sx, sy):
            s = "%s Tz %s Tc %s Tw %s TL %s Ts" % (fmt(g.th * 100 * sx / sy), fmt(g.tc * sy), fmt(g.tw * sy),
                                                   fmt(g.tl * sy), fmt(g.ts * sy))
            if g.font:
                s += " %s %s Tf" % (g.font, fmt(g.fs * sy))
            raw(s + "\n")

        for i, inst in enumerate(ops):
            if isinstance(inst, pikepdf.ContentStreamInlineImage):
                out.append(inst)
                continue
            operands, opr = inst
            op = str(opr)
            k = self.marks.get(i)

            if op == "q":
                stack.append(g.copy()); out.append(inst); continue
            if op == "Q":
                if stack:
                    g = stack.pop()
                out.append(inst); continue
            if op == "cm":
                g.ctm = mul(tuple(_num(v) for v in operands), g.ctm); out.append(inst); continue
            if op == "w":
                g.lw = _num(operands[0]); out.append(inst); continue
            if op in ("Tc", "Tw", "Tz", "TL", "Tf", "Ts"):
                if op == "Tc":
                    g.tc = _num(operands[0])
                elif op == "Tw":
                    g.tw = _num(operands[0])
                elif op == "Tz":
                    g.th = _num(operands[0]) / 100.0
                elif op == "TL":
                    g.tl = _num(operands[0])
                elif op == "Tf":
                    g.font, g.fs = str(operands[0]), _num(operands[1])
                else:
                    g.ts = _num(operands[0])
                if norm:
                    emit_state(g, *norm)
                else:
                    out.append(inst)
                continue
            if op == "Tr":
                g.tr = int(operands[0]); out.append(inst); continue
            if op == "BT":
                in_text, opened, dirty = True, True, False
                tm = tlm = I
                a, b, c, d = g.ctm[:4]
                if i in normalizable and abs(b) < 1e-9 and abs(c) < 1e-9 and \
                        (abs(abs(a) - 1) > 0.02 or abs(abs(d) - 1) > 0.02) and abs(a) > 1e-6 and abs(d) > 1e-6:
                    # 한컴 PDF는 글자를 92pt로 쓰고 0.12배로 줄인다. 그림은 같게 두고 '11pt를 1배로' 다시 쓴다.
                    # PDFium(크롬·엣지)의 줄바꿈·띄어쓰기 판단이 이 배율 때문에 틀어지는 것을 막는다.
                    norm = (abs(a), abs(d))
                    raw("q\n")
                    out.append(inst)
                    emit_state(g, *norm)
                else:
                    out.append(inst)
                continue
            if op == "ET":
                if opened:
                    out.append(inst)
                if norm:
                    raw("Q\n")
                    norm = None
                in_text = opened = dirty = False
                continue
            if op == "Tm" and norm:
                tm = tlm = tuple(_num(v) for v in operands)
                sx, sy = norm
                raw("%s Tm\n" % mat_str((tm[0] / sx, tm[1] / sx, tm[2] / sy, tm[3] / sy, tm[4], tm[5])))
                continue
            if op in ("Tm", "Td", "TD", "T*"):
                if op == "Tm":
                    tm = tlm = tuple(_num(v) for v in operands)
                elif op == "Td":
                    tm = tlm = mul((1, 0, 0, 1, _num(operands[0]), _num(operands[1])), tlm)
                elif op == "TD":
                    g.tl = -_num(operands[1])
                    tm = tlm = mul((1, 0, 0, 1, _num(operands[0]), _num(operands[1])), tlm)
                else:
                    tm = tlm = mul((1, 0, 0, 1, 0, -g.tl), tlm)
                if opened and not dirty:
                    out.append(inst)
                continue
            if op in SHOW:
                # ' 와 " 는 줄을 옮긴 뒤 찍는다
                if op == "'":
                    tm = tlm = mul((1, 0, 0, 1, 0, -g.tl), tlm)
                    string = operands[0]
                elif op == '"':
                    g.tw, g.tc = _num(operands[0]), _num(operands[1])
                    tm = tlm = mul((1, 0, 0, 1, 0, -g.tl), tlm)
                    string = operands[2]
                else:
                    string = operands[0]
                items = list(string) if op == "TJ" else [string]
                font = self.fonts.get(g.font)
                if k is None or font is None or font.glyphs is None or font.vertical:
                    if k is not None:
                        self.problems.append("수식 %d의 글꼴 %s 윤곽선을 못 꺼내 글자로 남김 (%s)" % (
                            k + 1, font.name if font else g.font, font.error if font else "자원 없음"))
                    # 보통 글자: 그대로 찍고 위치만 따라간다
                    if not opened:
                        raw("BT\n"); opened = True
                    if dirty or not opened:
                        if op == '"':
                            raw("%s Tw %s Tc\n" % (fmt(g.tw), fmt(g.tc)))
                        raw("%s Tm\n" % mat_str(tm))
                        if op in ("'", '"'):
                            out.append(([string], Operator("Tj")))
                        else:
                            out.append(inst)
                    else:
                        out.append(inst)
                    tm = self._advance(items, font, g, tm, order, record=k is None)
                    order += 1
                    continue
                # 수식 글자 -> 도형
                grp = self._group(k, out, g.ctm, order)
                if opened:
                    raw("ET\n"); opened = False
                dirty = True
                tm = self._glyphs_to_paths(items, font, g, tm, grp, raw)
                grp.last = order
                order += 1
                continue
            if op in PATH_CONS:
                if path_start is None:
                    path_start = len(out)
                    path_pts = []
                nums = [_num(v) for v in operands]
                if op == "re":
                    x, y, w, h = nums
                    path_pts += [(x, y), (x + w, y + h)]
                else:
                    path_pts += list(zip(nums[0::2], nums[1::2]))
                out.append(inst)
                continue
            if op in ("W", "W*"):
                out.append(inst); continue
            if op in PAINT or op == "n":
                if k is not None and path_start is not None:
                    grp = self._group(k, out, g.ctm, order, at=path_start)
                    pts = [apply(g.ctm, x, y) for x, y in path_pts]
                    half = g.lw / 2 * math.sqrt(abs(g.ctm[0] * g.ctm[3] - g.ctm[1] * g.ctm[2]))
                    if PAINT.get(op) == "s" and pts:
                        pts += [(x + dx, y + dy) for x, y in pts for dx, dy in ((half, half), (-half, -half))]
                    grp.add_pts(pts)
                    grp.paths += 1
                    grp.last = order
                order += 1
                path_start = None
                out.append(inst)
                continue
            out.append(inst)

        self.final_ctm = g.ctm
        self._fill_placeholders(out)
        return self._serialize(out)

    # ----------------------------------------------------------------
    def _group(self, k, out, ctm, order, at=None):
        grp = self.groups.get(k)
        if grp is None:
            grp = self.groups[k] = EqGroup(k)
            grp.first = order
            grp.ctm = ctm
            ph = ["ph", k]
            if at is None:
                out.append(ph)
            else:
                out.insert(at, ph)
            grp.placeholder = ph
        return grp

    def _trm(self, g, tm):
        return mul(mul((g.fs * g.th, 0, 0, g.fs, 0, g.ts), tm), g.ctm)

    def _advance(self, items, font, g, tm, order, record):
        for it in items:
            if not isinstance(it, (pikepdf.String, bytes)):
                try:
                    n = float(it)
                except Exception:
                    continue
                tm = mul((1, 0, 0, 1, -n / 1000.0 * g.fs * g.th, 0), tm)
                continue
            codes = font.codes(it) if font else list(bytes(it))
            for code in codes:
                if record and font is not None:
                    trm = self._trm(g, tm)
                    x0, y0 = apply(trm, 0, 0)
                    size = math.hypot(trm[2], trm[3])
                    w = font.width(code)
                    x1, _ = apply(trm, w, 0)
                    self.body_glyphs.append((order, min(x0, x1), max(x0, x1), y0, size))
                    key = font.obj.objgen if font.obj.is_indirect else id(font.obj)
                    self.text_runs.append((key, code, font.unicode(code)))
                w = font.width(code) if font else 0.5
                tx = (w * g.fs + g.tc + (g.tw if (font is None or not font.two_byte) and code == 32 else 0)) * g.th
                tm = mul((1, 0, 0, 1, tx, 0), tm)
        return tm

    def _glyphs_to_paths(self, items, font, g, tm, grp, raw):
        s = font.font_matrix_scale
        mode = g.tr % 4
        paint = {0: "f", 1: "S", 2: "B", 3: "n"}[mode]
        for it in items:
            if not isinstance(it, (pikepdf.String, bytes)):
                try:
                    n = float(it)
                except Exception:
                    continue
                tm = mul((1, 0, 0, 1, -n / 1000.0 * g.fs * g.th, 0), tm)
                continue
            for code in font.codes(it):
                path = font.path(code)
                m = mul((s, 0, 0, s, 0, 0), mul((g.fs * g.th, 0, 0, g.fs, 0, g.ts), tm))
                if path is None:
                    self.problems.append("수식 %d: 글리프 %d 윤곽선 없음" % (grp.k + 1, code))
                elif path and paint != "n":
                    raw("q %s cm %s %s Q\n" % (mat_str(m), path, paint))
                    grp.glyphs += 1
                # 글자 상자(전진 폭 x 글꼴 높이)로 수식 범위를 잡는다
                full = mul(m, g.ctm)
                w = font.width(code) / s
                pts = [apply(full, x, y) for x, y in ((0, -0.2 / s), (w, -0.2 / s), (0, 0.8 / s), (w, 0.8 / s))]
                if path:
                    grp.add_pts(pts)
                tx = (font.width(code) * g.fs + g.tc) * g.th
                tm = mul((1, 0, 0, 1, tx, 0), tm)
        return tm

    # ----------------------------------------------------------------
    def _fill_placeholders(self, out):
        self.placed = []
        for k, grp in self.groups.items():
            ph = grp.placeholder
            text = self.eq_texts.get(k, "") if hasattr(self, "eq_texts") else ""
            if not text or grp.bbox is None:
                ph[0] = "raw"; ph[1] = b""
                continue
            x0, y0, x1, y1 = grp.bbox
            base, size = self._baseline(grp)
            n = len(text.encode("utf-16-be")) // 2
            width = max(x1 - x0, 1.0)
            tz = 100.0 * width / (n * 0.5 * size) if n else 100.0
            hexs = text.encode("utf-16-be").hex().upper()
            invm = inv(grp.ctm)
            s = ("q %s cm BT %s %s Tf 3 Tr %s Tz 1 0 0 1 %s %s Tm <%s> Tj ET Q\n" % (
                mat_str(invm), self.inv_font_name, fmt(size), fmt(tz), fmt(x0), fmt(base), hexs))
            ph[0] = "raw"; ph[1] = s.encode("latin-1")
            self.placed.append((k, text, grp.bbox))

    def horizontal_anchor(self):
        """쪽 맨 아래에 본문 폭만큼 넓은 투명 공백 하나.

        PDFium(크롬·엣지)은 쪽의 글자 상자들이 가로로 얼마나 빈틈없이 덮는지 보고 가로쓰기/세로쓰기를 정한다.
        표가 많은 쪽은 글이 열마다 세로로 늘어서 세로쓰기로 판정되고, 그러면 '1', '2' 같은 한 글자 칸에서
        줄바꿈이 빠진다. 가로를 다 덮는 글자 하나를 두면 가로쓰기로 판정된다.
        """
        if not self.body_glyphs:
            return b""
        x0 = min(b[1] for b in self.body_glyphs)
        x1 = max(b[2] for b in self.body_glyphs)
        if x1 - x0 < 10:
            return b""
        size = 4.0
        tz = 100.0 * (x1 - x0) / (0.5 * size)
        return ("\nq %s cm BT %s %s Tf 3 Tr %s Tz 1 0 0 1 %s 2 Tm <0020> Tj ET Q\n" % (
            mat_str(inv(getattr(self, "final_ctm", I))), self.inv_font_name, fmt(size), fmt(tz),
            fmt(x0))).encode("latin-1")

    def _baseline(self, grp):
        x0, y0, x1, y1 = grp.bbox
        h = max(y1 - y0, 1.0)
        best = None
        prev = [b for b in self.body_glyphs if b[0] < grp.first]
        nxt = [b for b in self.body_glyphs if b[0] > (grp.last if grp.last is not None else grp.first)]
        cands = prev[-1:] + nxt[:1]
        for o, gx0, gx1, by, size in cands:
            same_line = y0 - 0.5 * size <= by <= y1 + 0.2 * size
            gap = min(abs(gx1 - x0), abs(gx0 - x1))
            if same_line and gap < 3 * size + 10:
                best = (by, size)
                break
        if best:
            return best
        size = min(h, 14.0) if h > 3 else 10.0
        return y0 + (h - size) / 2 + 0.2 * size, size

    def _serialize(self, out):
        chunks = []
        pending = []

        def flush():
            if pending:
                chunks.append(pikepdf.unparse_content_stream(pending))
                chunks.append(b"\n")
                pending.clear()
        for item in out:
            if isinstance(item, list) and item and item[0] in ("raw", "ph"):
                flush(); chunks.append(item[1] if item[0] == "raw" else b"")
            elif isinstance(item, tuple) and len(item) == 2 and item[0] == "raw":
                flush(); chunks.append(item[1])
            else:
                pending.append(item)
        flush()
        return b"".join(chunks)


def rewrite_pdf(pdf_a, pdf_b, eq_texts, log):
    """pdf_a를 그 자리에서 고친다. 돌려주는 값: 쪽별 결과 요약."""
    inv_font = make_invisible_font(pdf_a)
    font_cache = {}
    summary = {"pages": [], "located": set(), "problems": [], "text_runs": [], "fonts": font_cache}
    if len(pdf_a.pages) != len(pdf_b.pages):
        raise RuntimeError("표식 PDF의 쪽 수가 다릅니다(%d != %d)" % (len(pdf_a.pages), len(pdf_b.pages)))
    for pno, (pa, pb) in enumerate(zip(pdf_a.pages, pdf_b.pages)):
        ops_a = pikepdf.parse_content_stream(pa)
        ops_b = pikepdf.parse_content_stream(pb)
        if not same_structure(ops_a, ops_b):
            raise RuntimeError("%d쪽: 표식 PDF와 연산 순서가 달라 수식 위치를 맞출 수 없습니다" % (pno + 1))
        # 수식이 없는 쪽도 다시 쓴다: 글자 배율 정리와 가로쓰기 기준 글자(줄바꿈 누락 막기)
        marks = scan_markers(ops_b)
        res = pa.obj.get("/Resources")
        if res is None:
            pa.obj.Resources = res = pikepdf.Dictionary()
        if "/Font" not in res:
            res.Font = pikepdf.Dictionary()
        name = "/HwpPdfText"
        n = 0
        while name in res.Font and res.Font[name].objgen != inv_font.objgen:
            n += 1
            name = "/HwpPdfText%d" % n
        res.Font[name] = inv_font
        rw = PageRewriter(pdf_a, pa, marks, font_cache, name)
        rw.eq_texts = eq_texts
        data = rw.rewrite(ops_a) + rw.horizontal_anchor()
        pa.obj.Contents = pdf_a.make_stream(data)
        summary["located"].update(rw.groups.keys())
        summary["problems"] += ["%d쪽: %s" % (pno + 1, p) for p in dict.fromkeys(rw.problems)]
        summary["pages"].append({"page": pno + 1, "equations": len(rw.groups), "placed": rw.placed})
        summary["text_runs"].append(rw.text_runs)
    return summary
