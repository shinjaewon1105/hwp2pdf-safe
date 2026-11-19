"""한글 프로그램(COM)으로 PDF 두 벌을 뽑는다.

A: 원본 그대로.  B: 수식마다 표식 색(수식 번호를 담은 거의 검정색)을 입힌 것.
문서는 저장하지 않고 닫는다. 원본 파일은 읽기만 한다.
"""
import os

from .hwpcom import Hwp
from .pdfrewrite import marker_color


def export(src, pdf_a, pdf_b, log=print):
    hwp = Hwp()
    try:
        if not hwp.open(src):
            raise RuntimeError("한글에서 파일을 열지 못했습니다(암호가 걸렸거나 손상된 파일일 수 있음): %s"
                               % os.path.basename(src))
        pages = hwp.page_count
        eqs = hwp.equations()
        scripts = [c.Properties.Item("String") or "" for c in eqs]
        text = hwp.text()
        log("  한글에서 열림: %d쪽, 수식 %d개" % (pages, len(eqs)))
        if not hwp.save_pdf(pdf_a):
            raise RuntimeError("PDF로 저장하지 못했습니다")
        if eqs:
            for i, c in enumerate(eqs):
                p = c.Properties
                p.SetItem("Color", marker_color(i)[0])
                c.Properties = p
            if not hwp.save_pdf(pdf_b):
                raise RuntimeError("표식 PDF를 저장하지 못했습니다")
        return {"pages": pages, "scripts": scripts, "text": text}
    finally:
        hwp.quit()
