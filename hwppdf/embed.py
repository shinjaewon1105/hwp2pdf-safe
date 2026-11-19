"""원본 한글 파일을 PDF 안에 첨부하고(복구용), 다시 꺼낸다.

PDF/A-3 방식의 '연결 파일'(AF, AFRelationship /Source)로 넣는다. Acrobat·Edge·한컴 PDF 뷰어의
첨부 파일 창에서도 보이고, pdf2hwp.py 로 꺼내면 SHA-256 으로 바이트가 같은지 확인한다.
"""
import datetime
import hashlib
import os

import pikepdf
from pikepdf import Name

MIME = {".hwp": "application/x-hwp", ".hwpx": "application/hwp+zip"}
KEY = "/HwpPdf"


def embed_original(pdf, src_path, eq_mode):
    data = open(src_path, "rb").read()
    name = os.path.basename(src_path)
    sha = hashlib.sha256(data).hexdigest()
    from pikepdf.models.metadata import encode_pdf_date
    mtime = encode_pdf_date(datetime.datetime.fromtimestamp(os.path.getmtime(src_path)).astimezone())
    fs = pikepdf.AttachedFileSpec(
        pdf, data, description="원본 한글 문서 (이 PDF에서 한글 파일로 복구할 때 씀)",
        filename=name, mime_type=MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream"),
        creation_date=mtime, mod_date=mtime, relationship=Name.Source)
    pdf.attachments[name] = fs
    spec = pdf.attachments[name].obj
    spec.AFRelationship = Name.Source
    af = pdf.Root.get("/AF")
    if af is None:
        pdf.Root.AF = pikepdf.Array([spec])
    else:
        af.append(spec)
    pdf.Root[KEY] = pikepdf.Dictionary(
        Version=1, Source=pikepdf.String(name), SHA256=pikepdf.String(sha),
        Size=len(data), EquationText=pikepdf.String(eq_mode))
    return {"name": name, "sha256": sha, "size": len(data)}


def mark_pdfa3(pdf):
    """한컴 PDF는 XMP에 PDF/A-1b 라고 적는데, 첨부 파일은 PDF/A-3 에서만 허용된다."""
    try:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            if "pdfaid:part" in meta:
                meta["pdfaid:part"] = "3"
                meta["pdfaid:conformance"] = "B"
                return True
    except Exception:
        pass
    return False


def find_original(pdf):
    """첨부된 원본 (이름, 바이트, 기대 SHA-256 또는 None). 없으면 None."""
    info = pdf.Root.get(KEY)
    want_name = str(info.get("/Source")) if info is not None else None
    want_sha = str(info.get("/SHA256")) if info is not None else None
    cands = []
    for name, spec in pdf.attachments.items():
        ext = os.path.splitext(name)[1].lower()
        rel = spec.obj.get("/AFRelationship")
        if name == want_name or ext in MIME or (rel is not None and str(rel) == "/Source"):
            cands.append((name != want_name, ext not in MIME, name, spec))
    if not cands:
        return None
    cands.sort(key=lambda t: t[:2])
    _, _, name, spec = cands[0]
    data = spec.get_file().read_bytes()
    return name, data, (want_sha if name == want_name else None)
