"""한글(.hwp/.hwpx) -> PDF

    python hwp2pdf.py 보고서.hwp [다른파일.hwpx ...] [-o 결과.pdf] [--eq unicode|latex|hwp] [--no-embed]

만든 PDF는
  1) 원본 한글 파일을 첨부해 두어 pdf2hwp.py 로 바이트 하나 다르지 않게 되살릴 수 있고,
  2) 본문 글자를 긁으면 그대로 복사되며(깨진 글자 대응표는 원문과 맞춰 고침),
  3) 수식을 긁으면 읽을 수 있는 글(기본: x = (-b±√(b²-4ac))/(2a))로 복사된다.
     수식 모양은 한컴 PDF와 똑같은 벡터 도형이다.
"""
import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pikepdf  # noqa: E402

from hwppdf import eqtext, embed, hwpexport, pdfrewrite, textfix, verify  # noqa: E402


def free_name(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists("%s (%d)%s" % (stem, n, ext)):
        n += 1
    return "%s (%d)%s" % (stem, n, ext)


def convert(src, out, eq_mode="unicode", embed_src=True, check=True, log=print):
    t0 = time.time()
    src = os.path.abspath(src)
    tmp = tempfile.mkdtemp(prefix="hwp2pdf_")
    try:
        pdf_a, pdf_b = os.path.join(tmp, "a.pdf"), os.path.join(tmp, "b.pdf")
        info = hwpexport.export(src, pdf_a, pdf_b, log=log)
        scripts = info["scripts"]
        eq_texts = {i: eqtext.convert(s, eq_mode) for i, s in enumerate(scripts)}
        pdf = pikepdf.open(pdf_a)
        report = {"equations": len(scripts)}
        if scripts:
            with pikepdf.open(pdf_b) as pb:
                summary = pdfrewrite.rewrite_pdf(pdf, pb, eq_texts, log)
        else:
            summary = pdfrewrite.rewrite_pdf(pdf, pdf, {}, log)
        report["located"] = len(summary["located"])
        missing = [i + 1 for i in range(len(scripts)) if i not in summary["located"]]
        fix = textfix.repair(pdf, summary, info["text"], log=log)
        report.update(fix)
        if embed_src:
            report["embedded"] = embed.embed_original(pdf, src, eq_mode)
            embed.mark_pdfa3(pdf)
        work = os.path.join(tmp, "out.pdf")
        pdf.save(work, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        pdf.close()
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        shutil.copyfile(work, out)

        log("  수식 %d개 중 %d개를 PDF에서 찾아 글자층을 넣음" % (len(scripts), report["located"]))
        if missing:
            log("  ! 못 찾은 수식 번호: %s (머리말·글상자 안 개체 묶음 등)" % missing[:20])
        for p in summary["problems"][:10]:
            log("  ! " + p)
        if fix["bad_glyphs"]:
            log("  본문 깨진 글자 %d개 -> 대응표 %d개 고침, 남은 것 %d개" % (
                fix["bad_glyphs"], fix["fixed_codes"], fix["remaining"]))
        if embed_src:
            log("  원본 첨부: %s (%d바이트)" % (report["embedded"]["name"], report["embedded"]["size"]))
        if check:
            v = verify.check(pdf_a, out, eq_texts, summary, log=log)
            report["verify"] = v
        log("  -> %s  (%.1f초)" % (out, time.time() - t0))
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    if not (argv if argv is not None else sys.argv[1:]):
        print("한글 파일(.hwp/.hwpx)을 '한글을 PDF로.bat' 아이콘 위에 끌어다 놓으세요.")
        print("명령줄: python hwp2pdf.py 파일.hwp [--eq unicode|latex|hwp] [--no-embed]")
        return 0
    ap = argparse.ArgumentParser(description="한글 문서를 '되살릴 수 있고 글·수식이 안 깨지는' PDF로")
    ap.add_argument("inputs", nargs="+", help=".hwp / .hwpx 파일")
    ap.add_argument("-o", "--output", help="결과 PDF 경로(입력이 하나일 때)")
    ap.add_argument("--eq", choices=["unicode", "latex", "hwp"], default="unicode",
                    help="수식을 긁었을 때 나올 글: unicode(기본, 읽기 좋은 한 줄), latex, hwp(한글 수식 스크립트)")
    ap.add_argument("--no-embed", action="store_true", help="원본 한글 파일을 첨부하지 않음(복구 불가)")
    ap.add_argument("--no-check", action="store_true", help="결과 검사 생략")
    ap.add_argument("--overwrite", action="store_true", help="같은 이름 PDF가 있으면 덮어씀(기본은 ' (2)' 붙임)")
    a = ap.parse_args(argv)
    if a.output and len(a.inputs) > 1:
        ap.error("-o 는 입력 파일이 하나일 때만 씁니다")
    failed = 0
    for src in a.inputs:
        if not os.path.isfile(src) or os.path.splitext(src)[1].lower() not in (".hwp", ".hwpx"):
            print("건너뜀(한글 파일 아님): %s" % src)
            failed += 1
            continue
        out = a.output or os.path.splitext(src)[0] + ".pdf"
        if not a.overwrite:
            out = free_name(out)
        print("[%s]" % os.path.basename(src))
        try:
            convert(src, out, a.eq, not a.no_embed, not a.no_check)
        except Exception as e:
            failed += 1
            print("  실패: %s: %s" % (type(e).__name__, e))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
