"""Simple keyword document search for Atlas Chat bots. Standard library only.

Each bot can have a documents folder. On every chat request, server.py calls
search(folder, question) and adds the top 3 snippets to the system prompt.
Scoring: words of 3+ letters (minus common words), weighted by how rare they are
across the folder's chunks (idf), counted per chunk, with a small bonus for
chunks that contain more of the different question words.
"""
import math
import os
import re
import threading

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".html", ".htm", ".xml",
            ".py", ".js", ".ts", ".ps1", ".yaml", ".yml", ".ini", ".cfg", ".rst", ".tex"}
MAX_FILES = 2000
MAX_FILE_BYTES = 2_000_000
CHUNK_CHARS = 900
STOP = set("""the and for are but not you your with this that from have has had was were will would
could should can our out about into than then them they their there what when where which while who
why how all any each its it's also just like more most some such only own same very does did done
been being over under again further once here both few other nor off too yes use using get got
please tell give show want need make know think explain question answer""".split())
WORD = re.compile(r"[a-z0-9][a-z0-9_\-']{2,}")

_cache = {}  # folder -> (signature, chunks, df, postings)
_lock = threading.Lock()


def _words(text):
    return [w.strip("'-") for w in WORD.findall(text.lower()) if w.strip("'-") not in STOP]


def _files(folder):
    out = []
    pending = [os.fspath(folder)]
    while pending:
        root = pending.pop()
        try:
            entries = os.scandir(root)
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not entry.name.startswith(".") and entry.name not in ("node_modules", "__pycache__"):
                            pending.append(entry.path)
                        continue
                    if not entry.is_file():
                        continue
                    if os.path.splitext(entry.name)[1].lower() not in TEXT_EXT:
                        continue
                    st = entry.stat()
                except OSError:
                    continue
                if st.st_size <= MAX_FILE_BYTES:
                    out.append((entry.path, st.st_mtime, st.st_size))
                if len(out) >= MAX_FILES:
                    return out
    return out


def _chunks(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > CHUNK_CHARS:  # split very long paragraphs
            parts.append(para[:CHUNK_CHARS]); para = para[CHUNK_CHARS:]
        if len(cur) + len(para) + 2 > CHUNK_CHARS and cur:
            parts.append(cur); cur = para
        else:
            cur = (cur + "\n\n" + para) if cur else para
    if cur:
        parts.append(cur)
    return parts


def _index(folder):
    files = _files(folder)
    sig = tuple(files)
    with _lock:
        hit = _cache.get(folder)
        if hit and hit[0] == sig:
            return hit[1], hit[2], hit[3]
    chunks, df, postings = [], {}, {}
    for p, _, _ in files:
        for c in _chunks(p):
            counts = {}
            for w in _words(c):
                counts[w] = counts.get(w, 0) + 1
            chunk_index = len(chunks)
            chunks.append((p, c, counts))
            for w in counts:
                df[w] = df.get(w, 0) + 1
                postings.setdefault(w, []).append((chunk_index, counts[w]))
    with _lock:
        _cache[folder] = (sig, chunks, df, postings)
    return chunks, df, postings


def search(folder, query, k=3):
    """Return up to k dicts {file, text, score}, best first. Empty list if nothing matches."""
    if not folder or not os.path.isdir(folder):
        return []
    terms = set(_words(query))
    if not terms:
        return []
    chunks, df, postings = _index(folder)
    n = max(1, len(chunks))
    scores = {}
    hits = {}
    for term in terms:
        term_postings = postings.get(term, ())
        if not term_postings:
            continue
        idf = math.log(1 + n / df[term])
        for chunk_index, tf in term_postings:
            scores[chunk_index] = scores.get(chunk_index, 0.0) + (1 + math.log(tf)) * idf
            hits[chunk_index] = hits.get(chunk_index, 0) + 1
    scored = [
        (score * (1 + hits[index] / len(terms)), index, chunks[index][0], chunks[index][1])
        for index, score in scores.items()
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"file": p, "text": c, "score": round(s, 2)} for s, _, p, c in scored[:k]]


def prompt_block(results):
    """Text added to the system prompt."""
    if not results:
        return ""
    lines = ["Relevant excerpts from the user's documents (use them if they help, and name the file you used):"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] {r['file']}\n{r['text']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    for r in search(sys.argv[1], " ".join(sys.argv[2:])):
        print(r["score"], r["file"], "|", r["text"][:120].replace("\n", " "))
