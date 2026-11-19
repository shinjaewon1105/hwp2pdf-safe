"""본문 글꼴의 ToUnicode가 깨진 글자(옛한글 등 U+F000, U+FFFF, 사용자 영역)를 원문과 맞춰 고친다.

PDF 글자 순서에서 깨진 글자 덩어리의 앞뒤 멀쩡한 글자를 한글 원문에서 찾아,
가운데 글자 수가 같으면 글리프 하나하나에 원문 글자를 붙인다. 같은 글리프의 여러 자리에서 투표한다.
"""
import re
import zlib
from collections import Counter, defaultdict

import pikepdf

from .pdfrewrite import is_bad_unicode


def _norm(s):
    return re.sub(r"\s+", "", s)


def repair(pdf, summary, hwp_text, log=print):
    fonts = summary["fonts"]
    target = _norm(hwp_text)
    votes = defaultdict(Counter)
    bad_total = 0
    for runs in summary["text_runs"]:
        seq = [(key, code, u) for key, code, u in runs if not (u and u.isspace())]
        i = 0
        while i < len(seq):
            if not is_bad_unicode(seq[i][2]):
                i += 1
                continue
            j = i
            while j < len(seq) and is_bad_unicode(seq[j][2]) and seq[j][0] == seq[i][0]:
                j += 1
            bad_total += j - i
            n = j - i
            left = "".join(u for _, _, u in seq[max(0, i - 12):i] if not is_bad_unicode(u))
            right = "".join(u for _, _, u in seq[j:j + 12] if not is_bad_unicode(u))
            got = None
            if target:
                for w in (12, 8, 5, 3):
                    lt, rt = left[-w:], right[:w]
                    if not lt and not rt:
                        break
                    pat = re.escape(lt) + "(.{1,%d}?)" % (n * 3) + re.escape(rt)
                    found = list(re.finditer(pat, target))
                    if len(found) == 1:
                        got = found[0].group(1)
                        break
                    if len(found) > 1 and len({m.group(1) for m in found}) == 1:
                        got = found[0].group(1)
                        break
            if got is not None and len(got) == n:
                for (key, code, _), ch in zip(seq[i:j], got):
                    votes[(key, code)][ch] += 1
            i = j
    fixed = 0
    by_font = defaultdict(dict)
    for (key, code), c in votes.items():
        by_font[key][code] = c.most_common(1)[0][0]
    for key, mapping in by_font.items():
        info = fonts.get(key)
        if info is None:
            continue
        cmap = dict(info.tounicode)
        cmap.update(mapping)
        info.obj.ToUnicode = _cmap_stream(pdf, cmap, info.two_byte)
        info.tounicode = cmap
        fixed += len(mapping)
    remaining = 0
    for runs in summary["text_runs"]:
        for key, code, u in runs:
            info = fonts.get(key)
            uu = info.tounicode.get(code) if info else u
            if is_bad_unicode(uu) and not (uu and uu.isspace()):
                remaining += 1
    return {"bad_glyphs": bad_total, "fixed_codes": fixed, "remaining": remaining}


def _cmap_stream(pdf, cmap, two_byte):
    w = 4 if two_byte else 2
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def", "1 begincodespacerange",
             "<%s> <%s>" % ("0" * w, "F" * w), "endcodespacerange"]
    items = sorted((c, u) for c, u in cmap.items() if u is not None)
    for s in range(0, len(items), 100):
        chunk = items[s:s + 100]
        lines.append("%d beginbfchar" % len(chunk))
        for c, u in chunk:
            lines.append("<%0*X> <%s>" % (w, c, u.encode("utf-16-be").hex().upper()))
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    st = pikepdf.Stream(pdf, zlib.compress("\n".join(lines).encode("latin-1"), 9))
    st.Filter = pikepdf.Name.FlateDecode
    return pdf.make_indirect(st)
