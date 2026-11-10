"""Book readers for the Atlas knowledge library. Standard library only.

Formats: .epub, .mobi / .azw / .azw3 (Kindle without DRM), .fb2, .rtf, .odt.
load(name, raw_bytes) turns a book file into a title and a list of chapters:

    {"title": "...", "chapters": [{"title": "...", "text": "..."}, ...]}

server.py calls this when a book is imported into the library. A whole book does not fit
in a model's memory, so book_tools.py lets the model read it chapter by chapter.
"""
import codecs
import io
import os
import posixpath
import re
import struct
import zipfile
from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree

BOOK_EXT = {".epub", ".mobi", ".azw", ".azw3", ".fb2", ".rtf", ".odt"}
MAX_BOOK_CHARS = 20_000_000     # text kept from one book
PART_CHARS = 24_000             # size of one part for files that have no chapters
MIN_SECTION = 300               # shorter sections (title page, part heading) join the next one


class BookError(Exception):
    """The book cannot be read. The message says why in plain words."""


def _tag(el):
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _decode(raw):
    """Bytes of an (x)html or xml file as text."""
    m = re.search(rb'encoding=["\']([\w.-]+)["\']', raw[:300]) or re.search(rb'charset=["\']?([\w.-]+)', raw[:2000])
    name = m.group(1).decode("ascii", "replace") if m else "utf-8"
    try:
        codecs.lookup(name)
    except LookupError:
        name = "utf-8"
    return raw.decode("utf-8-sig" if name.lower().replace("-", "") == "utf8" else name, errors="replace")


# ---------- html -> sections ----------

_BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section", "article",
          "table", "ul", "ol", "dd", "dt", "pre", "hr", "body", "figcaption", "center"}
_SKIP = {"script", "style", "head", "svg"}
_HEAD = {"h1", "h2"}
_BREAK = {"mbp:pagebreak"}  # Kindle page break = start of a chapter


class _Html(HTMLParser):
    """Text of an html document, split into sections at h1 / h2 headings and Kindle page breaks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = [["", []]]
        self.skip = 0
        self.head = None
        self.dirty = False

    def _new(self):
        if self.dirty:
            self.sections.append(["", []])
            self.dirty = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag in _BREAK:
            self._new()
        elif tag in _HEAD:
            self._new()
            self.head = []
        if tag == "br":
            self.sections[-1][1].append("\n")
        elif tag in _BLOCK:
            self.sections[-1][1].append("\n\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in _HEAD and self.head is not None:
            title = " ".join("".join(self.head).split())
            if title and not self.sections[-1][0]:
                self.sections[-1][0] = title[:120]
            self.head = None
        if tag in _BLOCK:
            self.sections[-1][1].append("\n\n")

    def handle_data(self, data):
        if self.skip:
            return
        data = re.sub(r"\s+", " ", data)
        if data.strip():
            self.dirty = True
        self.sections[-1][1].append(data)
        if self.head is not None:
            self.head.append(data)


def _clean(text):
    text = re.sub(r"[ \t\xa0]*\n[ \t\xa0]*", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _html_sections(html):
    p = _Html()
    try:
        p.feed(html)
        p.close()
    except Exception:  # keep what was read before the bad markup
        pass
    out = [(title, _clean("".join(parts))) for title, parts in p.sections]
    return [(t, x) for t, x in out if x]


# ---------- epub ----------

def _epub_labels(z, base_of, items):
    """Chapter names from the book's own contents list: file path -> label."""
    labels = {}
    for href, mtype, props in items.values():
        try:
            if "ncx" in mtype or href.lower().endswith(".ncx"):
                root = ElementTree.fromstring(z.read(href))
                for nav in root.iter():
                    if _tag(nav) != "navPoint":
                        continue
                    text = next((" ".join("".join(e.itertext()).split()) for e in nav if _tag(e) == "navLabel"), "")
                    src = next((e.get("src") or "" for e in nav if _tag(e) == "content"), "")
                    if text and src:
                        labels.setdefault(base_of(href, src), text[:120])
            elif "nav" in props.split():
                for src, inner in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', _decode(z.read(href)), re.S | re.I):
                    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", inner)).split())
                    if text:
                        labels.setdefault(base_of(href, src), text[:120])
        except (KeyError, ElementTree.ParseError):
            continue
    return labels


def _read_epub(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = set(z.namelist())
        if "META-INF/encryption.xml" in names:  # font protection also lives here: only text files count
            enc = z.read("META-INF/encryption.xml").lower()
            if re.search(rb'uri="[^"]+\.x?html?"', enc):
                raise BookError("this book is protected by DRM (copy protection), so its text cannot be read")
        opf_path = None
        try:
            for el in ElementTree.fromstring(z.read("META-INF/container.xml")).iter():
                if _tag(el) == "rootfile" and el.get("full-path"):
                    opf_path = el.get("full-path")
                    break
        except (KeyError, ElementTree.ParseError):
            pass
        if opf_path not in names:
            opf_path = next((n for n in sorted(names) if n.lower().endswith(".opf")), None)
        if not opf_path:
            raise BookError("this is not a complete EPUB file (it has no contents list)")

        def base_of(owner, href):  # path inside the zip of a link found in the file `owner`
            return posixpath.normpath(posixpath.join(posixpath.dirname(owner), unquote(href.split("#")[0])))

        opf = ElementTree.fromstring(z.read(opf_path))
        items, spine, title = {}, [], ""
        for el in opf.iter():
            t = _tag(el)
            if t == "item" and el.get("id") and el.get("href"):
                items[el.get("id")] = (base_of(opf_path, el.get("href")), el.get("media-type") or "", el.get("properties") or "")
            elif t == "itemref":
                spine.append(el.get("idref"))
            elif t == "title" and not title:
                title = " ".join((el.text or "").split())
        labels = _epub_labels(z, base_of, items)
        sections, total = [], 0
        for ref in spine:
            href, mtype, props = items.get(ref, ("", "", ""))
            if href not in names or "nav" in props.split():
                continue
            if "html" not in mtype and not href.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            info = z.getinfo(href)
            if info.file_size > MAX_BOOK_CHARS * 4:  # zip bomb guard
                continue
            secs = _html_sections(_decode(z.read(info)))
            if secs and labels.get(href):
                secs[0] = (labels[href], secs[0][1])
            sections += secs
            total += sum(len(x) for _, x in secs)
            if total > MAX_BOOK_CHARS:
                break
    return title, sections


# ---------- mobi / azw / azw3 ----------

def _palmdoc(data):
    """PalmDOC (LZ77) decompression of one text record."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        i += 1
        if c == 0 or 9 <= c <= 0x7F:
            out.append(c)
        elif c <= 8:
            out += data[i:i + c]
            i += c
        elif c <= 0xBF:
            if i >= n:
                break
            c = (c << 8) | data[i]
            i += 1
            dist, length = (c >> 3) & 0x7FF, (c & 7) + 3
            if 0 < dist <= len(out):
                for _ in range(length):
                    out.append(out[-dist])
        else:
            out.append(32)
            out.append(c ^ 0x80)
    return bytes(out)


def _trim_record(rec, flags):
    """Remove the extra data some Kindle files add after the text of each record."""
    for bit in range(15, 0, -1):
        if flags >> bit & 1:
            size = 0
            for v in rec[-4:]:
                size = (0 if v & 0x80 else size << 7) | (v & 0x7F)
            rec = rec[:-size] if 0 < size <= len(rec) else rec
    if flags & 1 and rec:
        rec = rec[:-((rec[-1] & 3) + 1)]
    return rec


def _read_mobi(data):
    if data[60:68] not in (b"BOOKMOBI", b"TEXtREAd"):
        raise BookError("this is not a Kindle / Mobipocket book file")
    count = struct.unpack_from(">H", data, 76)[0]
    offs = [struct.unpack_from(">I", data, 78 + 8 * i)[0] for i in range(count)] + [len(data)]

    def rec(i):
        return data[offs[i]:offs[i + 1]]

    r0 = rec(0)
    compression, _, _, n_text, _, encryption = struct.unpack_from(">HHIHHH", r0, 0)
    if encryption:
        raise BookError("this Kindle book is protected by DRM (copy protection), so its text cannot be read")
    if compression not in (1, 2):
        raise BookError("this Kindle book uses a compression this app cannot read (HUFF/CDIC). "
                        "Convert it to EPUB with Calibre, then use the EPUB file")
    codec, title, flags, version, fdst = "cp1252", "", 0, 0, None
    if r0[16:20] == b"MOBI":
        length, _, enc = struct.unpack_from(">III", r0, 20)
        version = struct.unpack_from(">I", r0, 36)[0]
        codec = "utf-8" if enc == 65001 else "cp1252"
        name_off, name_len = struct.unpack_from(">II", r0, 84)
        title = r0[name_off:name_off + name_len].decode(codec, "replace").strip()
        if length >= 0xE4 and len(r0) >= 244:
            flags = struct.unpack_from(">H", r0, 242)[0]
        if version >= 8 and len(r0) >= 200:
            fdst = struct.unpack_from(">I", r0, 192)[0]
    parts, total = [], 0
    for i in range(1, min(n_text, count - 1) + 1):
        r = _trim_record(rec(i), flags)
        r = _palmdoc(r) if compression == 2 else r
        parts.append(r)
        total += len(r)
        if total > MAX_BOOK_CHARS:
            break
    raw = b"".join(parts)
    if fdst and fdst < count and rec(fdst)[:4] == b"FDST":  # azw3: the text comes first, style sheets follow
        table = rec(fdst)
        start, n_flows = struct.unpack_from(">II", table, 4)
        if n_flows and len(table) >= start + 8:
            raw = raw[:struct.unpack_from(">I", table, start + 4)[0]]
    return title, _html_sections(raw.decode(codec, "replace"))


# ---------- fb2 ----------

_FB2_LEAF = {"p", "v", "subtitle", "text-author", "td", "th"}


def _read_fb2(raw):
    root = ElementTree.fromstring(raw)
    title = next((" ".join("".join(e.itertext()).split()) for e in root.iter() if _tag(e) == "book-title"), "")
    sections = []

    def lines(el):
        leaves = [e for e in el.iter() if _tag(e) in _FB2_LEAF] or [el]
        return [t for t in (" ".join("".join(e.itertext()).split()) for e in leaves) if t]

    def walk(sec):
        head, paras = [], []
        for ch in sec:
            t = _tag(ch)
            if t == "title":
                head += lines(ch)
            elif t not in ("section", "image"):
                paras += lines(ch)
        if paras:
            name = " ".join(head)[:120]
            sections.append((name, "\n\n".join(([name] if name else []) + paras)))
        for ch in sec:
            if _tag(ch) == "section":
                walk(ch)

    for body in root:
        if _tag(body) == "body":
            walk(body)
    return title, sections


# ---------- odt ----------

def _read_odt(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        info = z.getinfo("content.xml")
        if info.file_size > MAX_BOOK_CHARS * 4:  # zip bomb guard
            raise BookError("the file is too large to read")
        root = ElementTree.fromstring(z.read(info))
    sections = [["", []]]

    def para(el):
        parts = [el.text or ""]
        for ch in el:
            t = _tag(ch)
            if t == "s":
                n = next((v for k, v in ch.attrib.items() if k.endswith("}c")), "1")
                parts.append(" " * (int(n) if n.isdigit() else 1))
            elif t == "tab":
                parts.append("\t")
            elif t == "line-break":
                parts.append("\n")
            else:
                parts.append(para(ch))
            parts.append(ch.tail or "")
        return "".join(parts)

    def walk(el):
        for ch in el:
            t = _tag(ch)
            if t in ("h", "p"):
                text = para(ch).strip()
                if not text:
                    continue
                level = next((v for k, v in ch.attrib.items() if k.endswith("}outline-level")), "1")
                if t == "h" and level in ("1", "2"):
                    if sections[-1][1]:
                        sections.append(["", []])
                    if not sections[-1][0]:
                        sections[-1][0] = " ".join(text.split())[:120]
                sections[-1][1].append(text)
            elif t != "tracked-changes":  # deleted text is kept there
                walk(ch)

    for el in root.iter():
        if _tag(el) == "body":
            walk(el)
            break
    return "", [(t, "\n\n".join(p)) for t, p in sections if p]


# ---------- rtf ----------

_RTF_TOKEN = re.compile(r"\\([a-zA-Z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|[\r\n]+|([^\\{}\r\n]+)")
_RTF_SKIP = set("""fonttbl colortbl stylesheet info pict object header footer headerl headerr headerf footerl
footerr footerf themedata colorschememapping datastore latentstyles listtable listoverridetable rsidtbl
generator xmlnstbl pgdsctbl revtbl filetbl fldinst operator author company title subject keywords doccomm
nonshppict shpinst mmathPr panose falt""".split())
_RTF_CHARS = {"par": "\n\n", "sect": "\n\n", "page": "\n\n", "line": "\n", "row": "\n", "tab": "\t", "cell": "\t",
              "emdash": "\u2014", "endash": "\u2013", "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c",
              "rdblquote": "\u201d", "bullet": "\u2022", "emspace": " ", "enspace": " ", "qmspace": " "}
_RTF_SYMBOLS = {"~": "\xa0", "_": "-", "-": "", "\n": "\n\n", "\r": "\n\n", "{": "{", "}": "}", "\\": "\\"}


def _rtf_text(data):
    if not data.lstrip()[:5] == b"{\\rtf":
        raise BookError("this is not an RTF file")
    out, stack, hexbuf = [], [], bytearray()
    skip, uc, pending, codec = False, 1, 0, "cp1252"
    for m in _RTF_TOKEN.finditer(data.decode("latin-1")):
        word, arg, hx, sym, brace, plain = m.groups()
        if hx is None and hexbuf:  # a run of \'hh bytes ended: decode it in one go (double-byte code pages)
            out.append(hexbuf.decode(codec, "replace"))
            hexbuf.clear()
        if brace == "{":
            stack.append((skip, uc))
        elif brace == "}":
            if stack:
                skip, uc = stack.pop()
            pending = 0
        elif sym:
            if sym == "*":
                skip = True
            elif not skip:
                out.append(_RTF_SYMBOLS.get(sym, ""))
        elif word:
            if word in _RTF_SKIP:
                skip = True
            elif word == "ansicpg" and arg:
                try:
                    codec = codecs.lookup("cp" + arg).name
                except LookupError:
                    pass
            elif word == "uc" and arg:
                uc = max(0, int(arg))
            elif skip:
                pass
            elif word == "u" and arg:
                out.append(chr(int(arg) % 65536))
                pending = uc  # the plain-text stand-in that follows \uN is dropped
            elif word in _RTF_CHARS:
                out.append(_RTF_CHARS[word])
        elif hx:
            if pending:
                pending -= 1
            elif not skip:
                hexbuf.append(int(hx, 16))
        elif plain:
            n = min(pending, len(plain))
            pending -= n
            if not skip:
                out.append(plain[n:])
    if hexbuf:
        out.append(hexbuf.decode(codec, "replace"))
    text = "".join(out).encode("utf-16", "surrogatepass").decode("utf-16", "replace")  # join \u surrogate pairs
    return _clean(text)


def _read_rtf(raw):
    return "", split_sections("Part", _rtf_text(raw))


# ---------- files without chapters ----------

def split_text(text, size=PART_CHARS):
    """Split text into pieces of at most `size` characters, on blank lines where possible, in order."""
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(cur) + len(para) + 2 > size and cur:
            parts.append(cur)
            cur = ""
        while len(para) > size:  # split very long paragraphs
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(para[:size])
            para = para[size:]
        cur = (cur + "\n\n" + para) if cur else para
    if cur:
        parts.append(cur)
    return parts


def split_sections(word, text):
    return [(f"{word} {i}", part) for i, part in enumerate(split_text(text), 1)]


READERS = {".epub": _read_epub, ".mobi": _read_mobi, ".azw": _read_mobi, ".azw3": _read_mobi,
           ".fb2": _read_fb2, ".odt": _read_odt, ".rtf": _read_rtf}


# ---------- load ----------

def _tidy(sections):
    """Join very short sections to the next one and give every chapter a name."""
    out, carry = [], None
    for title, text in sections:
        if carry:
            title, text, carry = title or carry[0], carry[1] + "\n\n" + text, None
        if len(text) < MIN_SECTION:
            carry = (title, text)
        else:
            out.append([title, text])
    if carry:
        if out:
            out[-1][1] += "\n\n" + carry[1]
        else:
            out.append(list(carry))
    chapters = []
    for i, (title, text) in enumerate(out, 1):
        if not title:
            first = text.split("\n", 1)[0].strip()
            title = first if 0 < len(first) <= 80 else f"Section {i}"
        chapters.append({"title": title, "text": text})
    return chapters


def make_book(title, sections):
    """A book from (title, text) sections. Raises BookError when there is no text."""
    chapters = _tidy([(t, x) for t, x in sections if x and x.strip()])
    if not chapters:
        raise BookError("no text was found in this file. It may hold only scanned images, or be copy protected (DRM)")
    return {"title": title, "chapters": chapters}


def load(name, raw):
    """The book in the bytes `raw` (file name `name`) as {"title", "chapters": [{"title", "text"}]}.
    Raises BookError with a plain reason when the book cannot be read."""
    ext = os.path.splitext(name)[1].lower()
    if ext not in READERS:
        raise BookError(f"{ext or 'this file type'} is not a supported book format")
    try:
        title, sections = READERS[ext](raw)
    except BookError:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, struct.error, KeyError, IndexError, ValueError,
            UnicodeError, OSError, EOFError) as e:
        raise BookError(f"the file is damaged or is not a real {ext.lstrip('.').upper()} file ({type(e).__name__})")
    return make_book(title or os.path.splitext(os.path.basename(name))[0], sections)


def text(book):
    """All the text of a book, chapter after chapter (for the library index)."""
    return "\n\n".join(c["text"] for c in book["chapters"])
