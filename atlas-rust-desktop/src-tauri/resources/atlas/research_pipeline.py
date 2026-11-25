"""Swarm-backed Deep Research pipeline for Atlas Chat (Phase 1B).

Runs a bounded, multi-step research workflow:
  1. Decompose the query into 2–4 focused sub-questions.
  2. Gather web sources concurrently (with SSRF protection and byte caps).
  3. Synthesize a cited Markdown report referencing numbered sources [1], [2], ...
  4. Persist the report under ``<DATA_DIR>/.atlas/research/`` for later review
     or one-click export to Docs Canvas.

Standard library only. Supports both ``hyper`` (cloud-first with local fallback)
and ``local`` (100% local model) routing.
"""
from __future__ import annotations

import concurrent.futures
import html
import ipaddress
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable

import cloud_llm
import llm

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>[\s\S]*?</\1>", re.I)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_DDG_LINK_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', re.I)
_MAX_FETCH_BYTES = 180_000


def _research_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, ".atlas", "research")
    os.makedirs(path, exist_ok=True)
    return path


def _is_safe_public_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        try:
            for info in socket.getaddrinfo(host, None):
                addr = ipaddress.ip_address(info[4][0])
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    return False
        except OSError:
            return False
    return True


def _strip_html(raw_html: str, max_chars: int = 4000) -> str:
    cleaned = _TAG_RE.sub(" ", raw_html)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


def _default_search_web(query: str, max_results: int = 3, timeout: int = 12) -> list[dict[str, str]]:
    """Lightweight stdlib DuckDuckGo HTML search returning [{title, url}]."""
    encoded = urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?{encoded}",
        headers={"User-Agent": "AtlasChat-Research/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(_MAX_FETCH_BYTES).decode("utf-8", "replace")
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for href, title_html in _DDG_LINK_RE.findall(body):
        url = html.unescape(href)
        if "uddg=" in url:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if qs.get("uddg"):
                url = qs["uddg"][0]
        title = _strip_html(title_html, max_chars=160)
        if url.startswith(("http://", "https://")):
            out.append({"title": title or url, "url": url})
        if len(out) >= max_results:
            break
    return out


def _default_fetch_url(url: str, timeout: int = 12) -> str:
    if not _is_safe_public_url(url):
        raise ValueError("Blocked non-public URL")
    req = urllib.request.Request(url, headers={"User-Agent": "AtlasChat-Research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(_MAX_FETCH_BYTES).decode("utf-8", "replace")
    return _strip_html(raw, max_chars=3500)


def _pick_model(mode: str, preferred_model: str = "") -> str:
    if preferred_model.strip():
        return preferred_model.strip()
    if mode == "hyper" and cloud_llm.enabled():
        for entry in cloud_llm.picker_models():
            if entry.get("available") and entry.get("free"):
                return str(entry["id"])
    return "mentor"


def _call_model(model_id: str, prompt: str, max_tokens: int = 1600, timeout: int = 120) -> str:
    if cloud_llm.is_cloud_model(model_id):
        completion, _ = cloud_llm.chat_completion(
            {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        return str((((completion.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")
    return llm.call_llm(prompt, temperature=0.3, max_tokens=max_tokens, model=model_id, timeout=timeout)


def _parse_subquestions(raw: str, original_query: str, max_q: int = 3) -> list[str]:
    lines = []
    for line in str(raw or "").splitlines():
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if len(cleaned) >= 6:
            lines.append(cleaned)
    if not lines:
        return [original_query]
    return lines[:max_q]


def run_research(
    query: str,
    *,
    mode: str = "hyper",
    max_sources: int = 6,
    model: str = "",
    data_dir: str | None = None,
    searcher: Callable[[str, int], list[dict[str, str]]] | None = None,
    fetcher: Callable[[str], str] | None = None,
    caller: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Execute a bounded Deep Research run and return a cited Markdown report."""
    q = str(query or "").strip()
    if not q:
        raise ValueError("Research query must not be empty")
    run_mode = str(mode or "hyper").strip().lower()
    if run_mode not in ("hyper", "local"):
        raise ValueError("mode must be 'hyper' or 'local'")
    cap = max(1, min(12, int(max_sources or 6)))

    started = time.perf_counter()
    chosen_model = _pick_model(run_mode, model)
    call_fn = caller or (lambda m, p: _call_model(m, p))
    search_fn = searcher or (lambda subq, k: _default_search_web(subq, max_results=k))
    fetch_fn = fetcher or _default_fetch_url

    # Stage 1: Decompose query into focused sub-questions
    decomp_prompt = (
        "Break the following research question into 3 concise, non-overlapping web search queries. "
        "Return one query per line, no commentary.\n\n"
        f"QUESTION: {q}"
    )
    try:
        sub_raw = call_fn(chosen_model, decomp_prompt)
    except Exception:
        sub_raw = q
    sub_questions = _parse_subquestions(sub_raw, q, max_q=3)

    # Stage 2: Parallel search + deduplicate URLs
    candidates: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    per_q = max(2, (cap // len(sub_questions)) + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sub_questions)) as pool:
        futs = [pool.submit(search_fn, sq, per_q) for sq in sub_questions]
        for fut in concurrent.futures.as_completed(futs):
            try:
                rows = fut.result() or []
            except Exception:
                rows = []
            for row in rows:
                url = str(row.get("url") or "").strip()
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    candidates.append({"title": str(row.get("title") or url), "url": url})
                if len(candidates) >= cap:
                    break
            if len(candidates) >= cap:
                break

    # Stage 3: Parallel source fetch
    sources: list[dict[str, Any]] = []
    if candidates:
        def _fetch_one(idx: int, item: dict[str, str]) -> dict[str, Any]:
            try:
                excerpt = str(fetch_fn(item["url"]) or "").strip()
                return {"index": idx, "title": item["title"], "url": item["url"], "ok": bool(excerpt), "excerpt": excerpt[:2800], "error": ""}
            except Exception as exc:
                return {"index": idx, "title": item["title"], "url": item["url"], "ok": False, "excerpt": "", "error": str(exc)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            futs = [pool.submit(_fetch_one, i + 1, item) for i, item in enumerate(candidates)]
            fetched = [f.result() for f in futs]
        sources = sorted(fetched, key=lambda r: r["index"])

    # Stage 4: Synthesize cited report
    usable = [s for s in sources if s["ok"] and s["excerpt"]]
    source_block = "\n\n".join(
        f"[{s['index']}] {s['title']} ({s['url']})\n{s['excerpt']}" for s in usable
    ) or "(No external web sources could be fetched; synthesize from model knowledge and note the limitation.)"

    synth_prompt = (
        "Write a clear, structured Markdown research report answering the user's question. "
        "Cite sources inline using bracketed numbers like [1], [2] matching the provided source list, "
        "highlight key findings and any contradictions or gaps, and finish with a '## Sources' section.\n\n"
        f"QUESTION: {q}\n\n"
        f"SUB-QUESTIONS: {', '.join(sub_questions)}\n\n"
        f"SOURCES:\n{source_block}"
    )
    report_md = str(call_fn(chosen_model, synth_prompt) or "").strip()
    if usable and "## Sources" not in report_md:
        refs = "\n".join(f"- [{s['index']}] [{s['title']}]({s['url']})" for s in usable)
        report_md = f"{report_md}\n\n## Sources\n{refs}\n"

    research_id = f"res-{uuid.uuid4().hex[:10]}"
    result = {
        "ok": True,
        "research_id": research_id,
        "query": q,
        "mode": run_mode,
        "model": chosen_model,
        "sub_questions": sub_questions,
        "sources": [{"index": s["index"], "title": s["title"], "url": s["url"], "ok": s["ok"]} for s in sources],
        "report_md": report_md,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "created_at": time.time(),
    }

    if data_dir:
        folder = _research_dir(data_dir)
        out_path = os.path.join(folder, f"{research_id}.json")
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, out_path)

    return result


def list_reports(data_dir: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent saved Deep Research reports."""
    folder = _research_dir(data_dir)
    rows: list[dict[str, Any]] = []
    for name in os.listdir(folder):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                item = json.load(f)
            if isinstance(item, dict) and item.get("research_id"):
                rows.append(
                    {
                        "research_id": item["research_id"],
                        "query": item.get("query", ""),
                        "mode": item.get("mode", "hyper"),
                        "model": item.get("model", ""),
                        "source_count": len(item.get("sources") or []),
                        "elapsed_ms": item.get("elapsed_ms", 0.0),
                        "created_at": float(item.get("created_at") or 0.0),
                    }
                )
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda r: -r["created_at"])
    return rows[: max(1, int(limit))]
