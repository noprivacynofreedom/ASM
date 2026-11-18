"""Small, bounded MCP tools for the Project Gutenberg public-domain catalog."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://gutendex.com/books/"
PG_ROOT = "https://www.gutenberg.org"
MAX_BODY = 20 * 1024 * 1024
MAX_TEXT = 12000
MAX_QUERY = 200
_MIME_SUFFIXES = {
    "text/plain; charset=utf-8": ".txt",
    "text/plain; charset=us-ascii": ".txt",
    "application/epub+zip": ".epub",
}


class _AllowHosts(urllib.request.HTTPRedirectHandler):
    """Do not let redirects turn a book request into an arbitrary network request."""
    hosts = {"gutendex.com", "www.gutenberg.org", "gutenberg.org", "aleph.gutenberg.org"}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in self.hosts:
            raise ValueError("The book source redirected outside the trusted catalog hosts.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_AllowHosts())


def _request(url, accept, max_bytes=MAX_BODY):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _AllowHosts.hosts:
        raise ValueError("Only HTTPS requests to the configured book catalog hosts are allowed.")
    request = urllib.request.Request(url, headers={"User-Agent": "Atlas-Commander/1.0", "Accept": accept})
    try:
        with _OPENER.open(request, timeout=8) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or (final.hostname or "").lower() not in _AllowHosts.hosts:
                raise ValueError("The book source redirected outside the trusted catalog hosts.")
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(f"Response exceeds the {max_bytes // (1024 * 1024)} MB limit.")
            return data, response.headers.get_content_type()
    except urllib.error.URLError as exc:
        raise ValueError(f"Book catalog request failed: {exc.reason}") from exc


def _api(params):
    url = API + "?" + urllib.parse.urlencode(params)
    payload, _ = _request(url, "application/json", 2 * 1024 * 1024)
    result = json.loads(payload.decode("utf-8"))
    return result if isinstance(result, dict) else {}


def _book_id(value):
    text = str(value or "").strip()
    if not re.fullmatch(r"[1-9][0-9]{0,7}", text):
        raise ValueError("book_id must be a Project Gutenberg book number.")
    return text


def _result(book):
    if not isinstance(book, dict):
        raise ValueError("Book was not found in the catalog.")
    authors = [p.get("name", "") for p in book.get("authors", []) if isinstance(p, dict)]
    formats = {}
    for mime, url in (book.get("formats") or {}).items():
        if mime in _MIME_SUFFIXES and isinstance(url, str):
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme == "https" and (parsed.hostname or "").lower() in _AllowHosts.hosts:
                formats[_MIME_SUFFIXES[mime][1:].upper()] = url
    return {
        "id": int(book.get("id", 0)),
        "title": str(book.get("title") or "")[:300],
        "authors": authors[:10],
        "languages": [str(v)[:20] for v in book.get("languages", [])[:10]],
        "subjects": [str(v)[:160] for v in book.get("subjects", [])[:12]],
        "public_domain_catalog_entry": book.get("copyright") is False,
        "formats": formats,
        "viewer_url": f"{PG_ROOT}/ebooks/{int(book.get('id', 0))}",
    }


def tool_definitions(schema, offline=False):
    if offline:
        return []
    return [
        {"name": "book_search", "description": "Search the Project Gutenberg book catalog. Returns public-domain catalog entries and viewer links.",
         "inputSchema": schema({"query": {"type": "string", "description": "Title, author, or topic."}, "limit": {"type": "integer", "description": "1 to 10, default 5."}}, ["query"])},
        {"name": "book_list", "description": "List popular Project Gutenberg catalog entries, optionally filtered by topic or language.",
         "inputSchema": schema({"topic": {"type": "string"}, "language": {"type": "string", "description": "Two-letter language code."}, "page": {"type": "integer", "description": "1 to 100."}})},
        {"name": "book_view", "description": "Show catalog details, supported formats, and the official browser viewer link for a book.",
         "inputSchema": schema({"book_id": {"type": "string"}}, ["book_id"])},
        {"name": "book_read", "description": "Read a bounded text excerpt from a public-domain catalog entry. Does not save a file.",
         "inputSchema": schema({"book_id": {"type": "string"}, "max_chars": {"type": "integer", "description": "1 to 12000, default 5000."}}, ["book_id"])},
        {"name": "book_download", "description": "Download one public-domain catalog entry as TXT or EPUB into downloads/books under the project root. Existing files are never replaced.",
         "inputSchema": schema({"book_id": {"type": "string"}, "format": {"type": "string", "enum": ["TXT", "EPUB"]}}, ["book_id", "format"])},
    ]


def _fetch_book(book_id):
    return _api({"ids": book_id}).get("results", [])


def call_tool(name, args, root):
    if os.environ.get("ATLAS_COMMANDER_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
        raise ValueError("Book catalog access is switched off (ATLAS_COMMANDER_OFFLINE).")
    if name == "book_search":
        query = str(args.get("query") or "").strip()[:MAX_QUERY]
        if not query:
            raise ValueError("query is required.")
        try:
            limit = max(1, min(10, int(args.get("limit", 5))))
        except (TypeError, ValueError):
            raise ValueError("limit must be from 1 to 10.")
        payload = _api({"search": query, "copyright": "false"})
        items = [_result(b) for b in payload.get("results", []) if isinstance(b, dict) and b.get("copyright") is False]
        return {"query": query, "count": payload.get("count", len(items)), "books": items[:limit]}

    if name == "book_list":
        try:
            page = max(1, min(100, int(args.get("page", 1))))
        except (TypeError, ValueError):
            raise ValueError("page must be from 1 to 100.")
        params = {"copyright": "false", "page": page}
        topic = str(args.get("topic") or "").strip()[:MAX_QUERY]
        language = str(args.get("language") or "").strip().lower()
        if topic:
            params["topic"] = topic
        if language:
            if not re.fullmatch(r"[a-z]{2,3}", language):
                raise ValueError("language must be a two or three letter code.")
            params["languages"] = language
        payload = _api(params)
        return {"count": payload.get("count", 0), "page": params["page"],
                "books": [_result(b) for b in payload.get("results", []) if isinstance(b, dict) and b.get("copyright") is False]}

    if name in ("book_view", "book_read", "book_download"):
        book_id = _book_id(args.get("book_id"))
        matches = _fetch_book(book_id)
        if not matches or matches[0].get("copyright") is not False:
            raise ValueError("Book is missing or is not marked public-domain by the catalog.")
        book = matches[0]
        info = _result(book)
        if name == "book_view":
            return info
        formats = info["formats"]
        if name == "book_read":
            url = formats.get("TXT")
            if not url:
                raise ValueError("This book has no supported plain-text format.")
            try:
                limit = max(1, min(MAX_TEXT, int(args.get("max_chars", 5000))))
            except (TypeError, ValueError):
                raise ValueError(f"max_chars must be from 1 to {MAX_TEXT}.")
            data, _ = _request(url, "text/plain", MAX_BODY)
            text = data.decode("utf-8-sig", errors="replace")
            return {"id": info["id"], "title": info["title"], "text": text[:limit], "truncated": len(text) > limit}

        fmt = str(args.get("format") or "").upper()
        if fmt not in ("TXT", "EPUB") or fmt not in formats:
            raise ValueError("Choose TXT or EPUB when the catalog offers that format.")
        data, _ = _request(formats[fmt], "text/plain" if fmt == "TXT" else "application/epub+zip", MAX_BODY)
        folder = (Path(root) / "downloads" / "books").resolve()
        if Path(root).resolve() not in folder.parents:
            raise ValueError("Download folder escaped the project root.")
        folder.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[^A-Za-z0-9._ -]", "_", info["title"]).strip(" .")[:100] or "book"
        target = folder / f"{book_id}-{safe_title}{_MIME_SUFFIXES['text/plain; charset=utf-8'] if fmt == 'TXT' else '.epub'}"
        if target.exists():
            raise ValueError(f"File already exists and was not changed: {target.relative_to(root)}")
        with target.open("xb") as handle:
            handle.write(data)
        return {"id": info["id"], "title": info["title"], "path": str(target.relative_to(root)), "bytes": len(data)}

    raise LookupError("Unknown book tool: " + str(name))
