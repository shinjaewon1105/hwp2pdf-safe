"""자체 시험: 한글·옛한글·특수문자·수식·표가 든 문서를 새로 만들어 변환하고, 결과를 확인한다.

    python selftest.py

임시 폴더에서만 작업하고 끝나면 지운다. 실패하면 0이 아닌 값으로 끝난다.
"""
import hashlib
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hwp2pdf  # noqa: E402
import pdf2hwp  # noqa: E402
from hwppdf import eqtext, verify  # noqa: E402

EQS = ["x = {-b +- sqrt {b^2 -4ac}} over {2a}", "int _{0} ^{1} x^2 dx = 1 over 3",
       "sum _{k=1} ^{n} k = {n(n+1)} over 2", "alpha", "lim _{x -> 0} {sin x} over x = 1"]


def make_doc(path):
    from pyhwpx import Hwp
    hwp = Hwp(new=True, visible=False)

    def eq(s):
        pset = hwp.HParameterSet.HEqEdit
        hwp.HAction.GetDefault("EquationCreate", pset.HSet)
        pset.string = s
        pset.BaseUnit = hwp.PointToHwpUnit(10)
        hwp.HAction.Execute("EquationCreate", pset.HSet)
    try:
        hwp.insert_text("가나다 한글 문장. 띄어쓰기  두 칸, 특수문자 ①②③ ℃ “따옴표” 옛한글 ᄒᆞᆫ글.")
        hwp.BreakPara()
        hwp.insert_text("근의 공식은 "); eq(EQS[0]); hwp.insert_text(" 이고 적분 "); eq(EQS[1])
        hwp.insert_text(" 이다. 각 "); eq(EQS[3]); hwp.insert_text("는 작다.")
        hwp.BreakPara()
        eq(EQS[2])
        hwp.BreakPara()
        hwp.create_table(1, 2)
        hwp.insert_text("표 칸")
        hwp.TableRightCell(); eq(EQS[4])
        hwp.save_as(path)
    finally:
        hwp.quit()


def main():
    tmp = tempfile.mkdtemp(prefix="hwp2pdf_test_")
    ok = True
    try:
        src = os.path.join(tmp, "시험 문서.hwp")
        make_doc(src)
        out = os.path.join(tmp, "시험 문서.pdf")
        rep = hwp2pdf.convert(src, out)
        texts = [eqtext.to_unicode(s) for s in EQS]
        for name, fn in (("MuPDF", verify.extract_mupdf), ("PDFium", verify.extract_pdfium)):
            pages = fn(out)
            if pages is None:
                continue
            full = "\n".join(pages)
            flat = re.sub(r"\s+", "", full)
            # 옛한글: PDFium은 겹친 자모를 x 좌표순으로 다시 늘어놓아 순서가 바뀔 수 있다(글자는 다 나옴)
            old = "ᄒᆞᆫ글" if name == "MuPDF" else "글"
            if name != "MuPDF" and not all(j in flat for j in "ᄒᆞᆫ"):
                ok = False
                print("  실패(%s): 옛한글 자모가 빠짐" % name)
            for want in ["근의공식은" + re.sub(r"\s+", "", texts[0]) + "이고",
                         "각" + texts[3] + "는작다", old, "①②③℃“따옴표”"]:
                if want not in flat:
                    ok = False
                    print("  실패(%s): '%s' 가 글자 뽑기에 없음" % (name, want))
            if verify._bad_chars(full):
                ok = False
                print("  실패(%s): 깨진 글자 %d개" % (name, verify._bad_chars(full)))
        if rep["verify"]["render_diff"] > 0.002:
            ok = False
            print("  실패: 모양이 한컴 PDF와 다름")
        back_dir = os.path.join(tmp, "복구")
        os.makedirs(back_dir)
        back = pdf2hwp.restore(out, back_dir)
        if hashlib.sha256(open(back, "rb").read()).digest() != hashlib.sha256(open(src, "rb").read()).digest():
            ok = False
            print("  실패: 복구한 한글 파일이 원본과 다름")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("자체 시험 %s" % ("통과" if ok else "실패"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
