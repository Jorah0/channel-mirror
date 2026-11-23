"""Documents in plain stdlib: a Word .docx (zip + WordprocessingML) and a PDF with embedded system TrueType fonts."""
import os
import re
import struct
import unicodedata
import zipfile
import zlib
from pathlib import Path


FONT_DIR = Path(os.environ.get("WINDIR") or r"C:\Windows") / "Fonts"


# tried in order for each character: Latin / Greek / Cyrillic / Hebrew / Arabic first, then wider coverage, CJK, Korean,
# Indian scripts; a font Windows doesn't have (or that may not be embedded) is skipped
PDF_FONTS = ("arial.ttf", "segoeui.ttf", "msyh.ttc", "malgun.ttf", "Nirmala.ttc", "nirmala.ttf", "seguisym.ttf")


def xml_text(s):
    """Any text -> safe inside XML: characters XML 1.0 can't hold are dropped, & < > " escaped."""
    s = re.sub("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "", str(s))
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def docx_write(path, title, lines):
    """A Word document: the title, then one paragraph per (stamp, text) line - the stamp in grey, the text hanging."""
    def para(runs, ppr=""):
        return f"<w:p>{ppr and f'<w:pPr>{ppr}</w:pPr>'}{runs}</w:p>"
    body = [para(f'<w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t xml:space="preserve">{xml_text(title)}</w:t></w:r>',
                 '<w:spacing w:after="240"/>')]
    for st, text in lines:
        body.append(para(f'<w:r><w:rPr><w:color w:val="6B7280"/></w:rPr><w:t>[{xml_text(st)}]</w:t></w:r>'
                         f'<w:r><w:tab/><w:t xml:space="preserve">{xml_text(text)}</w:t></w:r>',
                         '<w:spacing w:after="80"/><w:ind w:left="1300" w:hanging="1300"/>'))
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{w}"><w:body>'
           + "".join(body) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" '
           'w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    pkg = "http://schemas.openxmlformats.org/package/2006"
    parts = {
        "[Content_Types].xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="{pkg}/'
        'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/'
        'document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+'
        'xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-'
        'properties+xml"/></Types>',
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{pkg}/'
        'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.'
        'openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '</Relationships>',
        "docProps/core.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
        f'xmlns:cp="{pkg}/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>'
        f'{xml_text(title)}</dc:title><dc:creator>Channel Mirror</dc:creator></cp:coreProperties>',
        "word/document.xml": doc}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text.encode("utf-8"))


class TrueType:
    """The parts of a TrueType (glyf) font a PDF needs: character -> glyph, widths, metrics, and a subset that keeps
    only the glyphs used (glyph numbers unchanged). Font collections (.ttc) use their first font."""

    def __init__(self, path):
        self.name = re.sub(r"[^A-Za-z0-9]", "", Path(path).stem) or "Font"
        d = self.data = Path(path).read_bytes()
        base = struct.unpack(">I", d[12:16])[0] if d[:4] == b"ttcf" else 0
        n = struct.unpack(">H", d[base + 4:base + 6])[0]
        self.tables = {}
        for i in range(n):
            tag, _, off, ln = struct.unpack(">4sIII", d[base + 12 + 16 * i:base + 28 + 16 * i])
            self.tables[tag.decode("latin-1")] = (off, ln)
        if "glyf" not in self.tables or "loca" not in self.tables:
            raise ValueError("not a TrueType-outline font")
        head = self.table("head")
        self.upem = struct.unpack(">H", head[18:20])[0]
        self.bbox = [v * 1000 // self.upem for v in struct.unpack(">4h", head[36:44])]
        self.long_loca = struct.unpack(">h", head[50:52])[0] == 1
        hhea = self.table("hhea")
        self.ascent, self.descent = (v * 1000 // self.upem for v in struct.unpack(">hh", hhea[4:8]))
        n_hm = struct.unpack(">H", hhea[34:36])[0]
        self.glyphs = struct.unpack(">H", self.table("maxp")[4:6])[0]
        hmtx = self.table("hmtx")
        adv = list(struct.unpack(f">{2 * n_hm}H", hmtx[:4 * n_hm])[::2])
        self.advance = adv + [adv[-1]] * (self.glyphs - n_hm)
        os2 = self.table("OS/2") if "OS/2" in self.tables else b""
        self.cap = struct.unpack(">h", os2[88:90])[0] * 1000 // self.upem if len(os2) >= 90 else self.ascent
        if len(os2) >= 10 and struct.unpack(">H", os2[8:10])[0] & 0x000F == 2:
            raise ValueError("this font's licence doesn't allow embedding")
        self.cmap = self._cmap() if "cmap" in self.tables else {}  # a subset made here has none

    def table(self, tag):
        off, ln = self.tables[tag]
        return self.data[off:off + ln]

    def _cmap(self):
        c = self.table("cmap")
        subs = {}
        for i in range(struct.unpack(">H", c[2:4])[0]):
            pid, eid, off = struct.unpack(">HHI", c[4 + 8 * i:12 + 8 * i])
            subs[(pid, eid)] = off
        out = {}
        off = next((subs[k] for k in ((3, 10), (0, 4), (0, 6)) if k in subs), None)
        if off is not None and struct.unpack(">H", c[off:off + 2])[0] == 12:
            for g in range(struct.unpack(">I", c[off + 12:off + 16])[0]):
                a, b, gid = struct.unpack(">III", c[off + 16 + 12 * g:off + 28 + 12 * g])
                out.update(zip(range(a, b + 1), range(gid, gid + b - a + 1)))
            return out
        off = next((subs[k] for k in ((3, 1), (0, 3), (0, 1), (0, 0)) if k in subs), None)
        if off is None or struct.unpack(">H", c[off:off + 2])[0] != 4:
            raise ValueError("no Unicode character map")
        seg = struct.unpack(">H", c[off + 6:off + 8])[0] // 2
        arr = lambda k: struct.unpack(f">{seg}H", c[off + 14 + k * 2 * seg + (2 if k else 0):][:2 * seg])
        ends, starts, deltas, ranges = arr(0), arr(1), arr(2), arr(3)
        ro_at = off + 16 + 6 * seg
        for i in range(seg):
            for ch in range(starts[i], min(ends[i], 0xFFFE) + 1):
                if ranges[i] == 0:
                    g = (ch + deltas[i]) & 0xFFFF
                else:
                    at = ro_at + 2 * i + ranges[i] + 2 * (ch - starts[i])
                    g = struct.unpack(">H", c[at:at + 2])[0]
                    g = (g + deltas[i]) & 0xFFFF if g else 0
                if g:
                    out[ch] = g
        return out

    def subset(self, used):
        """The font with only the glyphs in used (and the glyphs they're built from) left in."""
        loca = self.table("loca")
        offs = (struct.unpack(f">{self.glyphs + 1}I", loca[:4 * (self.glyphs + 1)]) if self.long_loca else
                [2 * x for x in struct.unpack(f">{self.glyphs + 1}H", loca[:2 * (self.glyphs + 1)])])
        glyf = self.table("glyf")
        keep, todo = set(), [0, *used]
        while todo:
            g = todo.pop()
            if g in keep or g >= self.glyphs:
                continue
            keep.add(g)
            data = glyf[offs[g]:offs[g + 1]]
            if len(data) >= 10 and struct.unpack(">h", data[:2])[0] < 0:  # composite: its parts too
                at, more = 10, True
                while more and at + 4 <= len(data):
                    flags, part = struct.unpack(">HH", data[at:at + 4])
                    todo.append(part)
                    at += 4 + (4 if flags & 1 else 2) + (2 if flags & 8 else 4 if flags & 0x40 else 8 if flags & 0x80
                                                         else 0)
                    more = flags & 0x20
        new_glyf, new_loca = bytearray(), [0]
        for g in range(self.glyphs):
            if g in keep:
                new_glyf += glyf[offs[g]:offs[g + 1]]
                new_glyf += b"\0" * (-len(new_glyf) % 4)
            new_loca.append(len(new_glyf))
        head = bytearray(self.table("head"))
        head[8:12] = b"\0\0\0\0"  # checksum adjustment: not used by PDF readers
        head[50:52] = struct.pack(">h", 1)  # long glyph offsets
        tables = {t: self.table(t) for t in ("hhea", "maxp", "hmtx", "cvt ", "fpgm", "prep") if t in self.tables}
        tables.update({"head": bytes(head), "glyf": bytes(new_glyf),
                       "loca": struct.pack(f">{len(new_loca)}I", *new_loca)})
        n = len(tables)
        es = n.bit_length() - 1
        out = bytearray(struct.pack(">IHHHH", 0x00010000, n, 16 << es, es, 16 * n - (16 << es)))
        at = 12 + 16 * n
        body = bytearray()
        for tag in sorted(tables):
            t = tables[tag]
            padded = t + b"\0" * (-len(t) % 4)
            check = sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF
            out += struct.pack(">4sIII", tag.encode("latin-1"), check, at + len(body), len(t))
            body += padded
        return bytes(out + body)


def _fonts(names):
    """Each font that loads (missing / not embeddable ones skipped), loaded only when a character needs it."""
    for n in names:
        p = Path(n) if Path(n).is_absolute() else FONT_DIR / n
        if p.is_file():
            try:
                yield TrueType(p)
            except (ValueError, struct.error, OSError, IndexError):
                pass


def pdf_write(path, title, lines, fonts=None, size=10.5):
    """A PDF: the title, then each (stamp, text) line with the text wrapped beside its stamp; A4 pages numbered
    "Page n of N". The text is real text (selectable, searchable, copyable): each font used is embedded (only the
    glyphs used) with a ToUnicode map, and every character comes from the first font in fonts that has it."""
    loader, loaded = _fonts(fonts or PDF_FONTS), []
    pick = {}

    def glyph(ch):
        """ch -> (font index, glyph, width in points at size 1000)."""
        if ch not in pick:
            i, hit = 0, None
            while hit is None:
                if i == len(loaded):
                    nxt = next(loader, None)
                    if nxt is None:
                        break
                    loaded.append(nxt)
                g = loaded[i].cmap.get(ord(ch))
                if g:
                    hit = (i, g, loaded[i].advance[g] * 1000 / loaded[i].upem)
                i += 1
            if hit is None:  # no font here has it: the first font's empty box (still the right width)
                if not loaded:
                    raise RuntimeError("no usable TrueType font was found for the PDF")
                hit = (0, 0, loaded[0].advance[0] * 1000 / loaded[0].upem)
            pick[ch] = hit
        return pick[ch]

    def clean(s):
        s = unicodedata.normalize("NFC", str(s)).replace("\t", " ")
        return "".join(c for c in s if unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co", "Cn"))

    def visual(s):
        """Right-to-left runs (Hebrew, Arabic) in drawing order. ponytail: run reversal only - no full bidi, and
        Arabic letters aren't joined (the text still copies and searches right)."""
        rtl = "\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc"
        return re.sub(rf"[{rtl}](?:[{rtl}\s\d.,:;!?'\"()-]*[{rtl}])?", lambda mt: mt.group()[::-1], s)

    def width(s, sz):
        return sum(glyph(c)[2] for c in s) * sz / 1000

    wide = "\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7ff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef"

    def wrap(text, sz, room):
        units = re.findall(rf"[{wide}]|[^\s{wide}]+|\s+", text)
        out, cur = [], ""
        for u in units:
            if u.isspace():
                if cur:
                    cur += " "
                continue
            if width(cur + u, sz) <= room:
                cur += u
                continue
            if cur.strip():
                out.append(cur.rstrip())
            cur = ""
            while width(u, sz) > room:  # a word wider than the line: broken where it has to be
                k = 1
                while k < len(u) and width(u[:k + 1], sz) <= room:
                    k += 1
                out.append(u[:k])
                u = u[k:]
            cur = u
        if cur.strip():
            out.append(cur.rstrip())
        return out or [""]

    pw, ph, m = 595.28, 841.89, 56.0
    lead, tsize = size * 1.45, size * 1.6
    col = width("[00:00:00]", size) + size
    pages, y = [[]], ph - m  # page -> [(x, y, size, text, grey)]

    def put(x, text, sz, grey=False, gap=0.0):
        nonlocal y
        if y - sz < m + 20:
            pages.append([])
            y = ph - m
        y -= gap
        pages[-1].append((x, y - sz, sz, text, grey))
    for row in wrap(clean(title), tsize, pw - 2 * m):
        put(m, row, tsize)
        y -= tsize * 1.25
    y -= size
    for st, text in lines:
        rows = wrap(clean(text), size, pw - 2 * m - col)
        if y - lead * len(rows) < m + 20 and len(rows) <= 4:  # a short line isn't split over two pages
            y = m
        put(m, f"[{clean(st)}]", size, grey=True)
        for i, row in enumerate(rows):
            if i:
                y -= lead
                put(m + col, row, size)
            else:
                pages[-1].append((m + col, pages[-1][-1][1], size, row, False))
        y -= lead + size * 0.35
    total = len(pages)
    for n, pg in enumerate(pages, 1):
        foot = f"Page {n} of {total}"
        pg.append(((pw - width(foot, 9)) / 2, 30.0, 9, foot, True))

    used = {}  # font index -> {glyph: character}
    streams = []
    for pg in pages:
        ops = []
        for x, y_, sz, text, grey in pg:
            ops.append(f"BT {'0.42 0.45 0.5' if grey else '0.1 0.1 0.12'} rg 1 0 0 1 {x:.2f} {y_:.2f} Tm")
            run, font = [], None
            for c in visual(text):
                fi, g, _ = glyph(c)
                got = used.setdefault(fi, {})
                if g:
                    got.setdefault(g, c)
                if fi != font and run:
                    ops.append(f"/F{font} {sz:g} Tf <{''.join(run)}> Tj")
                    run = []
                font = fi
                run.append(f"{g:04X}")
            if run:
                ops.append(f"/F{font} {sz:g} Tf <{''.join(run)}> Tj")
            ops.append("ET")
        streams.append("\n".join(ops).encode("ascii"))

    objs = []  # object n = index + 1

    def add(body):
        objs.append(body)
        return len(objs)

    def stream(data, extra=""):
        z = zlib.compress(data, 9)
        return f"<< /Length {len(z)} /Filter /FlateDecode{extra} >>\nstream\n".encode() + z + b"\nendstream"
    catalog, pages_n = add(None), add(None)
    font_refs = {}
    for fi, gl in sorted(used.items()):
        f = loaded[fi]
        tag = "".join(chr(65 + (fi * 7 + k * 3 + len(gl)) % 26) for k in range(6)) + "+" + f.name
        sub = f.subset(gl)
        ff = add(stream(sub, f" /Length1 {len(sub)}"))
        desc = add(f"<< /Type /FontDescriptor /FontName /{tag} /Flags 32 /FontBBox [{' '.join(map(str, f.bbox))}] "
                   f"/ItalicAngle 0 /Ascent {f.ascent} /Descent {f.descent} /CapHeight {f.cap} /StemV 80 "
                   f"/FontFile2 {ff} 0 R >>".encode())
        widths = " ".join(f"{g} [{f.advance[g] * 1000 // f.upem}]" for g in sorted({0, *gl}))
        cid = add(f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{tag} /CIDSystemInfo << /Registry (Adobe) "
                  f"/Ordering (Identity) /Supplement 0 >> /FontDescriptor {desc} 0 R /W [{widths}] "
                  f"/CIDToGIDMap /Identity >>".encode())
        pairs = [f"<{g:04X}> <{c.encode('utf-16-be').hex().upper()}>" for g, c in sorted(gl.items())]
        cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) "
                "/Ordering (UCS) /Supplement 0 >> def\n/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
                "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
                + "".join(f"{len(pairs[k:k + 100])} beginbfchar\n" + "\n".join(pairs[k:k + 100]) + "\nendbfchar\n"
                          for k in range(0, len(pairs), 100))
                + "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend")
        uni = add(stream(cmap.encode("ascii")))
        font_refs[fi] = add(f"<< /Type /Font /Subtype /Type0 /BaseFont /{tag} /Encoding /Identity-H /DescendantFonts "
                            f"[{cid} 0 R] /ToUnicode {uni} 0 R >>".encode())
    res = "<< /Font << " + " ".join(f"/F{fi} {r} 0 R" for fi, r in font_refs.items()) + " >> >>"
    kids = []
    for s in streams:
        c = add(stream(s))
        kids.append(add(f"<< /Type /Page /Parent {pages_n} 0 R /MediaBox [0 0 {pw} {ph}] /Resources {res} "
                        f"/Contents {c} 0 R >>".encode()))
    objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_n} 0 R >>".encode()
    objs[pages_n - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    info = add(f"<< /Title <FEFF{clean(title).encode('utf-16-be').hex().upper()}> /Producer (Channel Mirror) >>".encode())
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    at = []
    for n, body in enumerate(objs, 1):
        at.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{a:010d} 00000 n \n" for a in at).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).write_bytes(bytes(out))
