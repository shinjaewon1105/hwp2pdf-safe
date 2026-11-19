"""만든 PDF 검사: 모양이 한컴 PDF와 같은가, 글자가 깨지지 않고 복사되는가, 원본이 그대로 첨부됐는가."""
import hashlib
import re
from collections import Counter

import pikepdf

from . import embed
from .pdfrewrite import is_bad_unicode


def _bad_chars(text):
    return sum(1 for ch in text if is_bad_unicode(ch) and not ch.isspace())


def _squash(s):
    return re.sub(r"\s+", "", s)


def extract_mupdf(path):
    import pymupdf
    with pymupdf.open(path) as d:
        return [p.get_text() for p in d]


def extract_pdfium(path):
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    doc = pdfium.PdfDocument(path)
    try:
        out = []
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            out.append(tp.get_text_range())
            tp.close()
        return out
    finally:
        doc.close()


def missing_breaks_pdfium(path):
    """PDFium 글자 좌표로 '아래 줄 왼쪽으로 넘어갔는데 엔터가 없는 곳'을 센다. (빠진 곳 수, 줄 바뀐 수)"""
    try:
        import ctypes
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
    except ImportError:
        return None
    doc = pdfium.PdfDocument(path)
    missed = lines = 0
    try:
        for pno in range(len(doc)):
            tp = doc[pno].get_textpage()
            prev, brk = None, False
            for i in range(tp.count_chars()):
                u = chr(raw.FPDFText_GetUnicode(tp.raw, i))
                if u in "\r\n":
                    brk = True
                    continue
                if raw.FPDFText_IsGenerated(tp.raw, i) or u.isspace():
                    continue
                x, y = ctypes.c_double(), ctypes.c_double()
                raw.FPDFText_GetCharOrigin(tp.raw, i, x, y)
                if prev is not None and abs(y.value - prev[1]) > 6 and x.value < prev[0]:
                    lines += 1
                    missed += not brk
                prev, brk = (x.value, y.value), False
            tp.close()
    finally:
        doc.close()
    return missed, lines


def render_diff(path_a, path_b, dpi=110):
    """쪽마다 회색조로 그려서 많이 다른 화소 비율(최댓값)"""
    import pymupdf
    worst = 0.0
    with pymupdf.open(path_a) as a, pymupdf.open(path_b) as b:
        for pa, pb in zip(a, b):
            xa = pa.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).samples
            xb = pb.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).samples
            if len(xa) != len(xb):
                return 1.0
            try:
                import numpy as np
                da = np.frombuffer(xa, np.uint8).astype(np.int16)
                db = np.frombuffer(xb, np.uint8).astype(np.int16)
                frac = float((np.abs(da - db) > 96).mean())
            except ImportError:
                frac = sum(1 for p, q in zip(xa, xb) if abs(p - q) > 96) / max(len(xa), 1)
            worst = max(worst, frac)
    return worst


def check(pdf_a, out, eq_texts, summary, log=print):
    res = {}
    diff = render_diff(pdf_a, out)
    res["render_diff"] = diff
    log("  검사 - 모양: 한컴 PDF와 다른 화소 %.3f%%%s" % (diff * 100, "" if diff < 0.002 else "  ! 확인 필요"))
    placed = [t for p in summary["pages"] for _, t, _ in p.get("placed", [])]
    for engine, fn in (("MuPDF", extract_mupdf), ("PDFium(크롬·엣지·웨일)", extract_pdfium)):
        pages = fn(out)
        if pages is None:
            continue
        text = "\n".join(pages)
        bad = _bad_chars(text)
        flat = _squash(text)
        need = Counter(_squash(t) for t in placed)
        hit = sum(min(c, flat.count(t)) for t, c in need.items())
        res[engine] = {"bad": bad, "eq_found": hit, "eq_total": len(placed)}
        log("  검사 - %s 글자 뽑기: 깨진 글자 %d개, 수식 글 %d/%d개 그대로 나옴" % (engine, bad, hit, len(placed)))
        if engine.startswith("PDFium"):
            mb = missing_breaks_pdfium(out)
            if mb is not None:
                res["missing_breaks"] = mb[0]
                log("  검사 - PDFium 줄바꿈: 줄 바뀌는 곳 %d곳 중 엔터 빠진 곳 %d곳%s" % (
                    mb[1], mb[0], "" if mb[0] == 0 else "  ! 확인 필요"))
    with pikepdf.open(out) as pdf:
        found = embed.find_original(pdf)
    if found:
        name, data, want = found
        ok = want is None or hashlib.sha256(data).hexdigest() == want
        res["attachment_ok"] = ok
        log("  검사 - 첨부 원본: %s, SHA-256 %s" % (name, "일치" if ok else "불일치!"))
    return res
