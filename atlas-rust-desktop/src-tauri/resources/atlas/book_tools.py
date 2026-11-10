"""Tools that let a model read the books in the Atlas knowledge library, part by part.

A whole book does not fit in a model's memory. So the model gets three tools:
  list_books                      the books in the library
  read_chapter(book)              the contents list of one book
  read_chapter(book, chapter)     the text of one chapter (long chapters come in parts)
  search_book(query, book)        the best passages for some words

LibraryTools wraps the MCP monitor: to the chat tool loop (mcp_chat.run_tool_loop) the
library looks like one more online tool server named "atlas_library". Standard library only.
Error text is written for the model: it names the problem and the fix.
"""
import math
import re
import time

import books

SERVER = "atlas_library"
PART_CHARS = 24_000     # one read_chapter result (about 6,000 tokens)
CHUNK_CHARS = 900       # one search passage
HITS = 5                # passages in one search_book result
MAX_CONTENTS = 200      # chapter names in one contents list
STOP = set("""the and for are but not you your with this that from have has had was were will would
could should can our out about into than then them they their there what when where which while who
why how all any each its it's also just like more most some such only own same very does did done
been being over under again further once here both few other nor off too yes use using get got
please tell give show want need make know think explain question answer book chapter""".split())
WORD = re.compile(r"[^\W_][\w\-']{2,}")

TOOLS = [
    {"name": "list_books",
     "description": "List the books in the Atlas knowledge library, with the number of chapters of each.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "read_chapter",
     "description": "Read a book from the Atlas knowledge library in parts. Without \"chapter\" it returns the contents list "
                    "(chapter numbers and names). With \"chapter\" it returns the text of that chapter. "
                    "Long chapters come back in several parts.",
     "inputSchema": {"type": "object", "properties": {
         "book": {"type": "string", "description": "Book name or part of it, e.g. dune. Not needed when the library holds one book."},
         "chapter": {"type": "integer", "description": "Chapter number from the contents list, starting at 1. Leave out to get the contents list."},
         "part": {"type": "integer", "description": "Part of a long chapter, starting at 1. Default 1."}}}},
    {"name": "search_book",
     "description": "Find the passages in the books of the Atlas knowledge library that match some words. "
                    "Returns the best passages with book name and chapter number.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words to look for: names, key terms, a short question."},
         "book": {"type": "string", "description": "Book name or part of it. Leave out to search every book."}},
         "required": ["query"]}},
]
ALIASES = {"book": ("path", "name", "title", "file", "filename", "book_name", "id"),
           "chapter": ("chapter_number", "number", "index", "section", "chapter_index"),
           "part": ("part_number", "page"),
           "query": ("q", "search", "text", "question", "keywords", "words")}


class ToolError(Exception):
    """A problem the model can fix. The message says how."""


def _words(text):
    words = (w.strip("'-_") for w in WORD.findall(str(text).lower()))
    return [w for w in words if len(w) > 2 and w not in STOP]


def parts(chapter):
    return books.split_text(chapter["text"], PART_CHARS) or [""]


def contents(book, name=""):
    chapters = book["chapters"]
    words = sum(len(c["text"]) for c in chapters) // 6
    label = f"\"{book['title']}\"" + (f" ({name})" if name and name != book["title"] else "")
    lines = [f"{label}: {len(chapters)} chapters, about {words:,} words. Contents:"]
    for i, c in enumerate(chapters[:MAX_CONTENTS], 1):
        n = len(parts(c))
        lines.append(f"{i}. {c['title']}" + (f" ({n} parts)" if n > 1 else ""))
    if len(chapters) > MAX_CONTENTS:
        lines.append(f"... and {len(chapters) - MAX_CONTENTS} more chapters, up to number {len(chapters)}.")
    lines.append("To read: read_chapter with \"chapter\" set to a number from this list. "
                 "To find a topic or a name: search_book. The book is too long to read in one go.")
    return "\n".join(lines)


def chapter_number(book, chapter):
    chapters = book["chapters"]
    if isinstance(chapter, bool):
        chapter = str(chapter)
    if isinstance(chapter, float) and chapter == int(chapter):
        chapter = int(chapter)
    if not isinstance(chapter, int):
        want = " ".join(str(chapter).split()).casefold()
        titles = [c["title"].casefold() for c in chapters]
        m = re.fullmatch(r"(?:chapter|ch\.?|section|part|no\.?)?\s*#?(\d+)", want)
        if want in titles:
            return titles.index(want) + 1
        if m:
            chapter = int(m.group(1))
        else:
            found = [i for i, t in enumerate(titles, 1) if want and want in t]
            if len(found) == 1:
                return found[0]
            raise ToolError(f"{'More than one' if found else 'No'} chapter name matches \"{chapter}\". Give \"chapter\" as a number. "
                            "Call read_chapter without \"chapter\" to get the contents list.")
    if not 1 <= chapter <= len(chapters):
        raise ToolError(f"There is no chapter {chapter}. This book has chapters 1 to {len(chapters)}. "
                        "Call read_chapter without \"chapter\" to get the contents list.")
    return chapter


def read_chapter(book, chapter=None, part=1, name=""):
    if chapter is None or str(chapter).strip() in ("", "0"):
        return contents(book, name)
    num = chapter_number(book, chapter)
    chapters = book["chapters"]
    ps = parts(chapters[num - 1])
    try:
        part = int(part or 1)
    except (TypeError, ValueError):
        part = 1
    if not 1 <= part <= len(ps):
        raise ToolError(f"Chapter {num} has {len(ps)} part{'s' if len(ps) > 1 else ''}. \"part\" must be 1 to {len(ps)}.")
    head = f"\"{book['title']}\", chapter {num} of {len(chapters)}: {chapters[num - 1]['title']}"
    if len(ps) > 1:
        head += f" (part {part} of {len(ps)})"
    if part < len(ps):
        tail = f"... the chapter continues. Call read_chapter with chapter {num} and part {part + 1} for the next part."
    elif num < len(chapters):
        tail = f"(end of chapter {num}. Next is chapter {num + 1}: {chapters[num]['title']})"
    else:
        tail = "(end of the book)"
    return f"{head}\n\n{ps[part - 1]}\n\n{tail}"


def _index(book):
    """(chunks, df) for one book: built on first search, kept on the book dict."""
    if "_index" not in book:
        chunks, df = [], {}
        for i, ch in enumerate(book["chapters"], 1):
            ps = parts(ch)
            for j, p in enumerate(ps, 1):
                for c in books.split_text(p, CHUNK_CHARS):
                    counts = {}
                    for w in _words(c):
                        counts[w] = counts.get(w, 0) + 1
                    chunks.append(((i, j, len(ps)), c, counts))
                    for w in counts:
                        df[w] = df.get(w, 0) + 1
        book["_index"] = (chunks, df)
    return book["_index"]


def search(named_books, query):
    """named_books: [(name, book)]. The best passages over all of them, as text for the model."""
    query = str(query or "").strip()
    terms = set(_words(query))
    if not terms:
        raise ToolError("\"query\" needs real search words (3 letters or more), for example a name or a key term.")
    scored = []
    for name, book in named_books:
        chunks, df = _index(book)
        n = max(1, len(chunks))
        for where, c, counts in chunks:
            s, hits = 0.0, 0
            for t in terms:
                tf = counts.get(t, 0)
                if tf:
                    hits += 1
                    s += (1 + math.log(tf)) * math.log(1 + n / df[t])
            if s:
                scored.append((s * (1 + hits / len(terms)), book, where, c))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return (f"No passage has these words: {', '.join(sorted(terms))}. "
                "Try other words (a name, a key term), or call read_chapter for the contents list.")
    out = [f"Best passages for \"{query}\":"]
    for n, (_, book, (i, j, total), c) in enumerate(scored[:HITS], 1):
        where = f"\"{book['title']}\", chapter {i}: {book['chapters'][i - 1]['title']}" + (f", part {j} of {total}" if total > 1 else "")
        out.append(f"\n[{n}] {where}\n{c}")
    out.append("\nThese are short pieces. For the full text around one, call read_chapter with that book and chapter number.")
    return "\n".join(out)


def _args(tool, arguments):
    """Accept the other argument names models really send."""
    arguments = arguments if isinstance(arguments, dict) else {}
    spec = next(t for t in TOOLS if t["name"] == tool)
    out = {}
    for key in spec["inputSchema"]["properties"]:
        for k in (key,) + ALIASES.get(key, ()):
            if arguments.get(k) not in (None, ""):
                out[key] = arguments[k]
                break
    return out


class LibraryTools:
    """The MCP monitor plus the library book tools.

    list_books() -> [{"id", "name", "title", "chapters": count}]
    load_book(id) -> {"title", "chapters": [{"title", "text"}]}
    """

    def __init__(self, monitor, list_books, load_book):
        self._monitor, self._list, self._load = monitor, list_books, load_book
        self._loaded = {}

    def __getattr__(self, name):  # everything else is the real monitor
        return getattr(self._monitor, name)

    def status(self):
        status = dict(self._monitor.status() or {})
        try:
            have = bool(self._list())
        except Exception:
            have = False
        if have:
            status["servers"] = list(status.get("servers") or []) + [
                {"name": SERVER, "state": "online", "process_running": True, "tools": TOOLS}]
        return status

    def _book(self, row):
        if row["id"] not in self._loaded:
            self._loaded[row["id"]] = self._load(row["id"])
        return self._loaded[row["id"]]

    def _pick(self, rows, want):
        names = "; ".join(r["name"] for r in rows[:30])
        if want in (None, ""):
            if len(rows) == 1:
                return rows[0]
            raise ToolError(f"The library holds {len(rows)} books. Give \"book\" as one of: {names}")
        want = str(want).strip().strip('"').casefold()
        exact = [r for r in rows if want in (r["id"], r["name"].casefold(), str(r.get("title") or "").casefold())]
        stem = want.rsplit(".", 1)[0]
        found = exact or [r for r in rows if stem and (stem in r["name"].casefold() or stem in str(r.get("title") or "").casefold())]
        if len(found) == 1:
            return found[0]
        raise ToolError(f"{'More than one book matches' if found else 'No book matches'} \"{want}\". The books are: {names}")

    def _run(self, tool, arguments):
        if tool not in [t["name"] for t in TOOLS]:
            raise ToolError(f"There is no library tool named \"{tool}\". The tools are: {', '.join(t['name'] for t in TOOLS)}.")
        rows = self._list()
        if not rows:
            raise ToolError("The knowledge library holds no books. The user can add one with IMPORT SOURCES in the Knowledge panel.")
        if tool == "list_books":
            return "Books in the Atlas knowledge library:\n" + "\n".join(
                f"- {r['name']}" + (f": \"{r['title']}\"" if r.get("title") else "") + f", {r['chapters']} chapters" for r in rows
            ) + "\nCall read_chapter with a book name to get its contents list."
        args = _args(tool, arguments)
        if tool == "read_chapter":
            row = self._pick(rows, args.get("book"))
            return read_chapter(self._book(row), args.get("chapter"), args.get("part", 1), row["name"])
        if "query" not in args:
            raise ToolError("search_book is missing \"query\". Example: {\"query\": \"words to find\"}")
        chosen = [self._pick(rows, args["book"])] if "book" in args else rows
        return search([(r["name"], self._book(r)) for r in chosen], args["query"])

    def call_tool(self, server_name, tool_name, arguments=None, timeout=30):
        if server_name != SERVER:
            return self._monitor.call_tool(server_name, tool_name, arguments, timeout=timeout)
        started = time.perf_counter_ns()
        try:
            text, failed = self._run(tool_name, arguments), False
        except ToolError as e:
            text, failed = "ERROR: " + str(e), True
        except Exception as e:  # never break the chat on a tool bug
            text, failed = f"ERROR: {tool_name} failed: {type(e).__name__}: {e}", True
        evidence = {"server": SERVER, "tool": tool_name,
                    "status": "FAILED" if failed else "EXECUTED_UNVERIFIED", "verification": "not_performed",
                    "duration_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
                    "result": {"content": [{"type": "text", "text": text}], "isError": failed},
                    "timestamp": time.time()}
        if failed:
            evidence["error"] = text
        return evidence
