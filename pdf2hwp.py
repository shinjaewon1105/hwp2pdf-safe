"""PDF -> 한글: hwp2pdf.py 로 만든 PDF에 첨부된 원본 한글 파일을 꺼낸다.

    python pdf2hwp.py 보고서.pdf [-o 폴더또는파일] [--open]

꺼낸 파일은 SHA-256 으로 원본과 같은지 확인한다. 같은 이름 파일이 있으면 덮어쓰지 않고 ' (복구)'를 붙인다.
"""
import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pikepdf  # noqa: E402

from hwppdf import embed  # noqa: E402


def free_name(path, tag=" (복구)"):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    cand = stem + tag + ext
    n = 2
    while os.path.exists(cand):
        cand = "%s%s %d%s" % (stem, tag, n, ext)
        n += 1
    return cand


def restore(pdf_path, out=None, log=print):
    with pikepdf.open(pdf_path) as pdf:
        found = embed.find_original(pdf)
    if found is None:
        raise RuntimeError("이 PDF에는 첨부된 한글 원본이 없습니다(hwp2pdf.py 로 만든 PDF가 아님)")
    name, data, want = found
    got = hashlib.sha256(data).hexdigest()
    if want and got != want:
        raise RuntimeError("첨부 파일이 손상됐습니다(SHA-256 불일치)")
    if out is None:
        out = os.path.join(os.path.dirname(os.path.abspath(pdf_path)), name)
    elif os.path.isdir(out):
        out = os.path.join(out, name)
    out = free_name(out)
    with open(out, "wb") as f:
        f.write(data)
    log("  %s -> %s (%d바이트, SHA-256 %s)" % (os.path.basename(pdf_path), out, len(data),
                                            "일치" if want else got[:16]))
    return out


def main(argv=None):
    if not (argv if argv is not None else sys.argv[1:]):
        print("hwp2pdf 로 만든 PDF를 'PDF를 한글로.bat' 아이콘 위에 끌어다 놓으세요.")
        return 0
    ap = argparse.ArgumentParser(description="hwp2pdf 로 만든 PDF에서 원본 한글 파일 되살리기")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--output", help="저장할 폴더 또는 파일 경로")
    ap.add_argument("--open", action="store_true", help="꺼낸 뒤 한글로 열기")
    a = ap.parse_args(argv)
    failed = 0
    for p in a.inputs:
        try:
            out = restore(p, a.output)
            if a.open:
                os.startfile(out)
        except Exception as e:
            failed += 1
            print("  실패(%s): %s" % (os.path.basename(p), e))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
