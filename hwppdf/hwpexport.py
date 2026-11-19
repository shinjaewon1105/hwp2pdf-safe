"""한글 프로그램(COM, pyhwpx)으로 PDF 두 벌을 뽑는다.

A: 원본 그대로.  B: 수식마다 표식 색(수식 번호를 담은 거의 검정색)을 입힌 것.
문서는 저장하지 않고 닫는다. 원본 파일은 읽기만 한다.
"""
import os

from .pdfrewrite import marker_color


def _equations(hwp):
    out, c = [], hwp.hwp.HeadCtrl
    while c:
        if c.CtrlID == "eqed":
            out.append(c)
        c = c.Next
    return out


def export(src, pdf_a, pdf_b, log=print):
    from pyhwpx import Hwp
    hwp = Hwp(new=True, visible=False)
    try:
        if not hwp.open(os.path.abspath(src)):
            raise RuntimeError("한글에서 파일을 열지 못했습니다: %s" % src)
        pages = hwp.PageCount
        eqs = _equations(hwp)
        scripts = []
        for c in eqs:
            p = c.Properties
            scripts.append(p.Item("String") or "")
        try:
            text = hwp.GetTextFile("UNICODE", "") or ""
        except Exception:
            text = ""
        log("  한글에서 열림: %d쪽, 수식 %d개" % (pages, len(eqs)))
        if not hwp.save_as(os.path.abspath(pdf_a), format="PDF"):
            raise RuntimeError("PDF로 저장하지 못했습니다")
        if eqs:
            for i, c in enumerate(eqs):
                p = c.Properties
                p.SetItem("Color", marker_color(i)[0])
                c.Properties = p
            if not hwp.save_as(os.path.abspath(pdf_b), format="PDF"):
                raise RuntimeError("표식 PDF를 저장하지 못했습니다")
        return {"pages": pages, "scripts": scripts, "text": text}
    finally:
        try:
            hwp.clear(1)        # 고친 내용 버리고 닫기
        except Exception:
            pass
        hwp.quit()
