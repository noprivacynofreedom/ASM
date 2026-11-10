"""Book import into the knowledge library, and the tools a model uses to read a book in parts.
Run from the backend folder (atlas-rust-desktop/src-tauri/resources/atlas):
    python -m unittest discover -s ../../../validation-tests -p "test_book_import.py"
Every test book is built here. No real store-bought book has been tested in the cloud.
"""
import base64
import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src-tauri", "resources", "atlas"))
_DATA = tempfile.TemporaryDirectory(prefix="atlas-book-test-")
os.environ.setdefault("ATLAS_DATA_DIR", _DATA.name)  # never touch real chats or the real library
os.environ.setdefault("ATLAS_OBSERVABILITY_DB", os.path.join(_DATA.name, "observability.sqlite3"))

import books  # noqa: E402
import book_tools  # noqa: E402
import mcp_chat  # noqa: E402
import server  # noqa: E402

CHAPTERS = [("Chapter 1: The Harbour", "Mara kept the lighthouse at Kestrel Point. " + "The sea was grey that winter. " * 30),
            ("Chapter 2: The Storm", "The storm broke the lantern glass. Mara used a brass sextant to fix the lens. " + "Rain fell all night. " * 30),
            ("Chapter 3: The Letter", "A letter came from Wellington with news of the keeper\u2019s caf\u00e9. " + "Nobody spoke at dinner. " * 30)]


def epub_bytes(chapters=CHAPTERS, drm=False):
    import io
    manifest = "".join(f'<item id="c{i}" href="text/ch{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(len(chapters)))
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    nav = "".join(f'<navPoint id="n{i}"><navLabel><text>{t}</text></navLabel><content src="text/ch{i}.xhtml#top"/></navPoint>'
                  for i, (t, _) in enumerate(chapters))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        if drm:
            z.writestr("META-INF/encryption.xml", '<encryption><EncryptedData><CipherData><CipherReference URI="OEBPS/text/ch0.xhtml"/></CipherData></EncryptedData></encryption>')
        z.writestr("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<metadata><dc:title>The Kestrel Light</dc:title></metadata><manifest>{manifest}'
                   '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
                   f'<spine toc="ncx">{spine}</spine></package>')
        z.writestr("OEBPS/toc.ncx", f'<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{nav}</navMap></ncx>')
        for i, (t, body) in enumerate(chapters):
            z.writestr(f"OEBPS/text/ch{i}.xhtml", '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title>'
                       f'<style>p {{ color: red }}</style></head><body><p>{body}</p><p>Tom &amp; Mara ate.</p></body></html>')
    return buf.getvalue()


def palmdoc_pack(data):
    """A valid PalmDOC stream: plain bytes, escaped bytes and a real back-reference for each repeat."""
    out, i = bytearray(), 0
    while i < len(data):
        if i >= 8 and data[i:i + 8] == data[i - 8:i]:  # repeat of the 8 bytes before: distance 8, length 8
            out += struct.pack(">H", 0x8000 | (8 << 3) | (8 - 3))
            i += 8
            continue
        c = data[i]
        out += bytes([c]) if c == 0 or 9 <= c <= 0x7F else bytes([1, c])
        i += 1
    return bytes(out)


def mobi_bytes(html, compression=2, encryption=0, utf8=True, trailing=False):
    raw = html.encode("utf-8" if utf8 else "cp1252")
    recs = [raw[i:i + 4096] for i in range(0, len(raw), 4096)]
    title = b"The Kestrel Light"
    mobi = bytearray(232)
    mobi[0:4] = b"MOBI"
    struct.pack_into(">III", mobi, 4, 232, 2, 65001 if utf8 else 1252)
    struct.pack_into(">I", mobi, 20, 6)                       # file version
    struct.pack_into(">II", mobi, 68, 16 + 232, len(title))   # full name offset and length
    struct.pack_into(">H", mobi, 226, 3 if trailing else 0)   # extra data flags (offset 242 in the record)
    r0 = struct.pack(">HHIHHHH", compression, 0, len(raw), len(recs), 4096, encryption, 0) + bytes(mobi) + title
    body = []
    for r in recs:
        r = palmdoc_pack(r) if compression == 2 else r
        body.append(r + (b"\x00" + b"xy\x83" if trailing else b""))  # multibyte count byte, then a 3-byte trailing entry
    records = [r0] + body + [b"\xe9\x8e\x0d\x0a"]
    head = bytearray(78)
    head[0:17] = b"The_Kestrel_Light"
    head[60:68] = b"BOOKMOBI"
    struct.pack_into(">H", head, 76, len(records))
    off, table = 78 + 8 * len(records) + 2, b""
    for i, r in enumerate(records):
        table += struct.pack(">II", off, 2 * i)
        off += len(r)
    return bytes(head) + table + b"\x00\x00" + b"".join(records)


def book_html():
    return "<html><head><guide></guide></head><body>" + "".join(
        f"<mbp:pagebreak/><h2>{t}</h2><p>{body}</p>" for t, body in CHAPTERS) + "</body></html>"


def fb2_bytes():
    secs = "".join(f"<section><title><p>{t}</p></title><p>{body}</p></section>" for t, body in CHAPTERS)
    xml = ('<?xml version="1.0" encoding="windows-1251"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
           "<description><title-info><book-title>The Kestrel Light</book-title></title-info></description>"
           f"<body>{secs}</body><binary id=\"cover\">AAAA</binary></FictionBook>")
    return xml.replace("\u2019", "'").replace("\u00e9", "e").encode("windows-1251")


def odt_bytes():
    import io
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')
    body = "".join(f'<text:h text:outline-level="1">{t}</text:h><text:p>{b}</text:p><text:p>Two<text:s text:c="2"/>spaces<text:tab/>tab</text:p>'
                   for t, b in CHAPTERS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", f'<?xml version="1.0"?><office:document-content {ns}><office:body><office:text>{body}</office:text></office:body></office:document-content>')
    return buf.getvalue()


def rtf_bytes():
    body = "".join(t.replace(":", "\\'3a") + "\\par " + b.replace("\u2019", "\\'92").replace("\u00e9", "\\u233?") + "\\par\n" for t, b in CHAPTERS)
    rtf = ("{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0 Times New Roman;}}{\\colortbl;\\red0\\green0\\blue0;}"
           "{\\info{\\title Secret Title}}{\\*\\generator Riched20;}\\f0 " + body + "{\\b Bold \\{end\\}}\\emdash dash}")
    return rtf.encode("latin-1")


class ReadersTest(unittest.TestCase):
    def check(self, name, raw, titled=True):
        b = books.load(name, raw)
        text = books.text(b)
        self.assertIn("brass sextant", text, name)
        self.assertIn("lighthouse at Kestrel Point", text, name)
        self.assertNotIn("<p>", text, name)
        if titled:
            self.assertEqual([c["title"] for c in b["chapters"]], [t for t, _ in CHAPTERS], name)
            self.assertIn("sextant", b["chapters"][1]["text"])
        return b, text

    def test_epub(self):
        b, text = self.check("k.epub", epub_bytes())
        self.assertEqual(b["title"], "The Kestrel Light")
        self.assertIn("Tom & Mara ate.", text)
        self.assertIn("keeper\u2019s caf\u00e9", text)
        self.assertNotIn("color: red", text)  # style sheets are not text

    def test_mobi_compressed_plain_and_trailing_data(self):
        texts = []
        for name, kw in (("a.mobi", {}), ("b.mobi", {"compression": 1}), ("c.azw3", {"trailing": True}), ("d.azw", {"utf8": False})):
            b, text = self.check(name, mobi_bytes(book_html(), **kw))
            self.assertEqual(b["title"], "The Kestrel Light")
            self.assertIn("keeper\u2019s caf\u00e9", text, name)
            texts.append(text)
        self.assertEqual(texts[0], texts[1])
        self.assertEqual(texts[0], texts[2])  # nothing extra and nothing lost when records carry trailing data

    def test_palmdoc_back_reference(self):
        packed = palmdoc_pack(b"abcdefgh" * 4 + b"\xc3\xa9 end")
        self.assertLess(len(packed), 32)
        self.assertEqual(books._palmdoc(packed), b"abcdefgh" * 4 + b"\xc3\xa9 end")
        self.assertEqual(books._palmdoc(b"a\xe2"), b"a b")  # 0xC0-0xFF = space + letter

    def test_fb2_odt_rtf(self):
        self.assertEqual(self.check("k.fb2", fb2_bytes())[0]["title"], "The Kestrel Light")
        self.assertIn("Two  spaces\ttab", self.check("k.odt", odt_bytes())[1])
        text = self.check("k.rtf", rtf_bytes(), titled=False)[1]
        self.assertIn("Chapter 2: The Storm", text)
        self.assertIn("keeper\u2019s caf\u00e9", text)
        self.assertIn("Bold {end}\u2014dash", text)
        for junk in ("Times New Roman", "Secret Title", "Riched20", "?"):
            self.assertNotIn(junk, text)

    def test_protected_and_damaged_books_say_why(self):
        for name, raw, word in (("drm.epub", epub_bytes(drm=True), "DRM"),
                                ("drm.mobi", mobi_bytes(book_html(), encryption=2), "DRM"),
                                ("huff.mobi", mobi_bytes(book_html(), compression=17480), "Calibre")):
            with self.assertRaises(books.BookError) as e:
                books.load(name, raw)
            self.assertIn(word, str(e.exception))
        for name in ("bad.epub", "bad.mobi", "bad.azw3", "bad.fb2", "bad.odt", "bad.rtf", "bad.xyz"):
            self.assertRaises(books.BookError, books.load, name, b"this is not a book" * 20)


class _NoMcp:
    """A monitor with no MCP servers."""
    def status(self): return {"configured": 0, "online": 0, "servers": []}
    def check_all(self): return self.status()
    def call_tool(self, server_name, *_a, **_k): raise KeyError(f"Unknown MCP server: {server_name}")


class LibraryTest(unittest.TestCase):
    """Import through the real HTTP endpoint, then read with the model tools."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (server.LIBRARY_DIR, server.LIBRARY_INDEX, server.LIBRARY_INDEX_FILE)
        server.LIBRARY_DIR = self.tmp.name
        server.LIBRARY_INDEX = os.path.join(self.tmp.name, "index.json")
        server.LIBRARY_INDEX_FILE = os.path.join(self.tmp.name, "semantic-index.json")
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.tools = book_tools.LibraryTools(_NoMcp(), server._library_books, server._library_load_book)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.LIBRARY_DIR, server.LIBRARY_INDEX, server.LIBRARY_INDEX_FILE = self.saved
        self.tmp.cleanup()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def add(self, name, raw):
        return self.post("/api/library/import", {"name": name, "base64": base64.b64encode(raw).decode()})

    def call(self, tool, args=None):
        ev = self.tools.call_tool(book_tools.SERVER, tool, args or {})
        return ev["result"]["content"][0]["text"], ev

    def test_import_saves_text_and_chapters_and_delete_removes_both(self):
        code, d = self.add("kestrel.epub", epub_bytes())
        self.assertEqual(code, 201, d)
        item = d["item"]
        self.assertEqual((item["title"], item["chapters"], item["extension"]), ("The Kestrel Light", 3, ".epub"))
        self.assertIn("brass sextant", server._library_read_source(item["id"]))
        self.assertEqual(len(server._library_load_book(item["id"])["chapters"]), 3)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), sorted([item["id"] + ".source", item["id"] + ".chapters.json", "index.json"]))
        self.assertEqual(self.post("/api/library/delete", {"id": item["id"]})[0], 200)
        self.assertEqual(os.listdir(self.tmp.name), ["index.json"])
        self.assertEqual(server._library_books(), [])

    def test_every_book_format_imports(self):
        for name, raw in (("a.mobi", mobi_bytes(book_html())), ("b.azw3", mobi_bytes(book_html(), trailing=True)),
                          ("c.fb2", fb2_bytes()), ("d.odt", odt_bytes()), ("e.rtf", rtf_bytes()), ("f.epub", epub_bytes())):
            code, d = self.add(name, raw)
            self.assertEqual(code, 201, (name, d))
            self.assertIn("brass sextant", server._library_read_source(d["item"]["id"]), name)
        self.assertEqual(len(server._library_books()), 6)

    def test_plain_text_import_still_works_and_is_not_a_book(self):
        code, d = self.post("/api/library/import", {"name": "notes.md", "content": "# Notes\nDHCP gives out addresses."})
        self.assertEqual(code, 201, d)
        self.assertNotIn("chapters", d["item"])
        self.assertEqual(server._library_books(), [])
        self.assertEqual(self.tools.status()["servers"], [])  # no books: the model gets no book tools

    def test_bad_books_are_refused_with_a_plain_reason(self):
        for name, raw, word in (("drm.epub", epub_bytes(drm=True), "DRM"), ("x.mobi", b"junk" * 100, "not a Kindle"), ("x.epub", b"junk" * 100, "damaged"),
                                ("huff.azw3", mobi_bytes(book_html(), compression=17480), "Calibre"), ("x.exe", b"MZ", "Supported formats")):
            code, d = self.add(name, raw)
            self.assertEqual(code, 400, name)
            self.assertIn(word, d["error"], name)
        self.assertEqual(server._library_index()["items"], [])

    def test_library_search_finds_book_text(self):
        self.add("kestrel.epub", epub_bytes())
        old = server.SETTINGS.get("embedding_model")
        server.SETTINGS["embedding_model"] = ""  # word search: no embedding model in the test
        try:
            hits, _mode = server._library_retrieve("brass sextant lens")
        finally:
            server.SETTINGS["embedding_model"] = old
        self.assertTrue(hits)
        self.assertIn("sextant", hits[0]["text"])

    def test_tools_list_contents_chapter_and_search(self):
        self.add("kestrel.epub", epub_bytes())
        names = [t["name"] for s in self.tools.status()["servers"] if s["name"] == book_tools.SERVER for t in s["tools"]]
        self.assertEqual(names, ["list_books", "read_chapter", "search_book"])
        self.assertIn("kestrel.epub", self.call("list_books")[0])
        toc, ev = self.call("read_chapter")  # one book in the library: no name needed
        self.assertEqual((ev["status"], ev["result"]["isError"]), ("EXECUTED_UNVERIFIED", False))
        self.assertIn("3 chapters", toc)
        self.assertIn("2. Chapter 2: The Storm", toc)
        ch = self.call("read_chapter", {"book": "kestrel", "chapter": 2})[0]
        self.assertIn("chapter 2 of 3: Chapter 2: The Storm", ch)
        self.assertIn("brass sextant", ch)
        self.assertIn("Next is chapter 3", ch)
        self.assertNotIn("lighthouse at Kestrel", ch)
        for how in ("2", "chapter 2", "the storm", 2.0):
            self.assertIn("brass sextant", self.call("read_chapter", {"title": "The Kestrel Light", "chapter_number": how})[0], how)
        self.assertIn("end of the book", self.call("read_chapter", {"book": "kestrel.epub", "chapter": 3})[0])
        found = self.call("search_book", {"q": "brass sextant"})[0]
        self.assertIn('[1] "The Kestrel Light", chapter 2: Chapter 2: The Storm', found)
        self.assertIn("No passage", self.call("search_book", {"query": "dragon"})[0])

    def test_tool_errors_tell_the_model_what_to_do(self):
        self.add("kestrel.epub", epub_bytes())
        self.add("other.fb2", fb2_bytes())
        text, ev = self.call("read_chapter", {"chapter": 1})
        self.assertEqual((ev["status"], ev["result"]["isError"]), ("FAILED", True))
        self.assertIn("kestrel.epub", text)  # two books: the error lists the names
        self.assertIn("No book matches", self.call("read_chapter", {"book": "dune"})[0])
        self.assertIn("chapters 1 to 3", self.call("read_chapter", {"book": "kestrel.epub", "chapter": 9})[0])
        self.assertIn("as a number", self.call("read_chapter", {"book": "kestrel.epub", "chapter": "epilogue"})[0])
        self.assertIn("must be 1 to 1", self.call("read_chapter", {"book": "kestrel.epub", "chapter": 1, "part": 5})[0])
        self.assertIn('missing "query"', self.call("search_book", {"book": "kestrel.epub"})[0])
        self.assertIn("More than one book matches", self.call("read_chapter", {"book": "kestrel"})[0])  # both titles hold "kestrel"
        self.assertIn("search words", self.call("search_book", {"query": "to be or"})[0])
        self.assertIn("no library tool", self.call("burn_book")[0])
        self.assertIn("The Kestrel Light", self.call("search_book", {"query": "sextant"})[0])  # no book given: all books

    def test_long_chapter_comes_in_parts_with_nothing_lost(self):
        long = [("Chapter 1: Long", "</p>" + "\n".join(f"<p>Paragraph {i} about the tide tables.</p>" for i in range(3000)) + "<p>"),
                ("Chapter 2: Short", "The needle in the haystack is a zebra. " * 10)]
        self.assertEqual(self.add("long.epub", epub_bytes(long))[0], 201)
        self.assertIn("1. Chapter 1: Long (", self.call("read_chapter")[0])
        first = self.call("read_chapter", {"chapter": 1})[0]
        self.assertLess(len(first), book_tools.PART_CHARS + 400)
        self.assertIn("part 1 of", first)
        self.assertIn("chapter 1 and part 2", first)
        second = self.call("read_chapter", {"chapter": 1, "part": 2})[0]
        n = int(first.rsplit("Paragraph ", 1)[1].split()[0])
        self.assertIn(f"Paragraph {n + 1} about", second.split("\n\n")[1])
        self.assertIn("chapter 2: Chapter 2: Short", self.call("search_book", {"query": "zebra haystack"})[0])

    def test_other_tool_servers_still_work_and_the_model_sees_the_book_tools(self):
        self.add("kestrel.epub", epub_bytes())

        class Mcp(_NoMcp):
            def status(self):
                return {"configured": 1, "online": 1, "servers": [{"name": "files", "state": "online", "process_running": True,
                        "tools": [{"name": "read", "description": "read a file", "inputSchema": {"type": "object"}}]}]}
            def call_tool(self, server_name, tool_name, arguments=None, timeout=30):
                return {"status": "EXECUTED_UNVERIFIED", "result": {"content": [{"type": "text", "text": "from mcp"}]}}

        tools = book_tools.LibraryTools(Mcp(), server._library_books, server._library_load_book)
        self.assertEqual(tools.call_tool("files", "read", {})["result"]["content"][0]["text"], "from mcp")
        defs, lookup = mcp_chat._tool_definitions(tools)
        self.assertEqual(sorted(lookup), ["atlas_library__list_books", "atlas_library__read_chapter", "atlas_library__search_book", "files__read"])
        self.assertEqual(lookup["atlas_library__read_chapter"], ("atlas_library", "read_chapter"))

    def test_chat_tool_loop_reads_a_chapter_for_the_model(self):
        self.add("kestrel.epub", epub_bytes())
        sent = []

        def fake_model(_host, _port, request):
            sent.append(request)
            last = request["messages"][-1]
            if last.get("role") == "tool":
                return {"choices": [{"message": {"role": "assistant", "content": "Mara used a brass sextant."}, "finish_reason": "stop"}]}
            return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "atlas_library__read_chapter", "arguments": json.dumps({"book": "kestrel", "chapter": 2})}}]}, "finish_reason": "tool_calls"}]}

        old = mcp_chat._post_completion
        mcp_chat._post_completion = fake_model
        try:
            completion, events = mcp_chat.run_tool_loop(
                {"model": "assist", "messages": [{"role": "user", "content": "How did Mara fix the lens?"}]},
                self.tools, lambda e: e, "127.0.0.1", 9)
        finally:
            mcp_chat._post_completion = old
        self.assertIn("brass sextant", completion["choices"][0]["message"]["content"])
        self.assertEqual([(e.get("server"), e.get("tool"), e.get("status")) for e in events], [("atlas_library", "read_chapter", "EXECUTED_UNVERIFIED")])
        tool_msgs = [m for m in sent[-1]["messages"] if m.get("role") == "tool"]
        self.assertIn("Mara used a brass sextant to fix the lens", tool_msgs[0]["content"])
        self.assertIn("atlas_library__search_book", [t["function"]["name"] for t in sent[0]["tools"]])


if __name__ == "__main__":
    unittest.main()
