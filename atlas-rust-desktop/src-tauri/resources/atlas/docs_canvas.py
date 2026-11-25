"""Writing-first Docs Canvas for Atlas Chat (Phase 2B).

Stores Markdown, HTML, CSV, and plain-text documents under
``<DATA_DIR>/.atlas/docs/`` (isolated from ``data.json`` and user workspaces)
and supports reviewable AI edit proposals with unified diffs before saving.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
import uuid
from typing import Any, Callable

import cloud_llm
import llm

ALLOWED_KINDS = ("md", "html", "csv", "txt")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _docs_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, ".atlas", "docs")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_id(doc_id: str) -> str:
    cleaned = str(doc_id or "").strip()
    if not _ID_RE.fullmatch(cleaned):
        raise ValueError("Invalid document id")
    return cleaned


def _safe_kind(kind: str) -> str:
    k = str(kind or "md").strip().lower().lstrip(".")
    if k not in ALLOWED_KINDS:
        raise ValueError(f"Unsupported document kind '{k}'. Choose one of: {', '.join(ALLOWED_KINDS)}")
    return k


def _meta_path(data_dir: str, doc_id: str) -> str:
    return os.path.join(_docs_dir(data_dir), f"{_safe_id(doc_id)}.meta.json")


def _content_path(data_dir: str, doc_id: str, kind: str) -> str:
    return os.path.join(_docs_dir(data_dir), f"{_safe_id(doc_id)}.{_safe_kind(kind)}")


def _slug_id(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(title or "untitled").strip().lower()).strip("-")[:36]
    if not slug or not slug[0].isalnum():
        slug = "doc"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def list_docs(data_dir: str) -> list[dict[str, Any]]:
    """Return metadata for all saved Docs Canvas documents, newest first."""
    folder = _docs_dir(data_dir)
    rows: list[dict[str, Any]] = []
    for name in os.listdir(folder):
        if not name.endswith(".meta.json"):
            continue
        meta_file = os.path.join(folder, name)
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if not isinstance(meta, dict) or not meta.get("id"):
                continue
            rows.append(
                {
                    "id": meta["id"],
                    "title": str(meta.get("title") or meta["id"]),
                    "kind": str(meta.get("kind") or "md"),
                    "updated_at": float(meta.get("updated_at") or 0.0),
                    "bytes": int(meta.get("bytes") or 0),
                }
            )
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda r: -r["updated_at"])
    return rows


def get_doc(data_dir: str, doc_id: str) -> dict[str, Any]:
    """Load a document's metadata and content."""
    did = _safe_id(doc_id)
    meta_file = _meta_path(data_dir, did)
    if not os.path.isfile(meta_file):
        raise FileNotFoundError(f"Document not found: {did}")
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    kind = _safe_kind(meta.get("kind", "md"))
    body_file = _content_path(data_dir, did, kind)
    content = ""
    if os.path.isfile(body_file):
        with open(body_file, "r", encoding="utf-8") as f:
            content = f.read()
    return {
        "id": did,
        "title": str(meta.get("title") or did),
        "kind": kind,
        "content": content,
        "updated_at": float(meta.get("updated_at") or 0.0),
        "bytes": len(content.encode("utf-8")),
    }


def save_doc(
    data_dir: str,
    title: str,
    content: str,
    *,
    kind: str = "md",
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Create or atomically update a Docs Canvas document (keeping a .prev backup on edits)."""
    clean_title = str(title or "").strip() or "Untitled Document"
    clean_kind = _safe_kind(kind)
    text = str(content or "")
    did = _safe_id(doc_id) if doc_id else _slug_id(clean_title)

    body_file = _content_path(data_dir, did, clean_kind)
    meta_file = _meta_path(data_dir, did)

    if os.path.isfile(body_file):
        prev_file = body_file + ".prev"
        try:
            with open(body_file, "r", encoding="utf-8") as src, open(prev_file, "w", encoding="utf-8") as dst:
                dst.write(src.read())
        except OSError:
            pass

    tmp_body = body_file + ".tmp"
    with open(tmp_body, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp_body, body_file)

    now = time.time()
    meta = {
        "id": did,
        "title": clean_title,
        "kind": clean_kind,
        "updated_at": now,
        "bytes": len(text.encode("utf-8")),
    }
    tmp_meta = meta_file + ".tmp"
    with open(tmp_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp_meta, meta_file)

    return {**meta, "content": text}


def delete_doc(data_dir: str, doc_id: str) -> dict[str, Any]:
    """Delete a Docs Canvas document and its metadata."""
    did = _safe_id(doc_id)
    meta_file = _meta_path(data_dir, did)
    if not os.path.isfile(meta_file):
        raise FileNotFoundError(f"Document not found: {did}")
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    kind = str(meta.get("kind") or "md")
    for path in (meta_file, _content_path(data_dir, did, kind), _content_path(data_dir, did, kind) + ".prev"):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
    return {"ok": True, "deleted": did}


def make_unified_diff(original: str, proposed: str, filename: str = "document") -> str:
    """Compute a unified diff string between ``original`` and ``proposed``."""
    lines = list(
        difflib.unified_diff(
            str(original or "").splitlines(keepends=True),
            str(proposed or "").splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3,
        )
    )
    return "".join(lines)


def _call_editor_model(model_id: str, system: str, prompt: str, timeout: int = 120) -> str:
    if cloud_llm.is_cloud_model(model_id):
        completion, _ = cloud_llm.chat_completion(
            {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
            },
            timeout=timeout,
        )
        return str((((completion.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")
    return llm.call_llm(f"{system}\n\n{prompt}", temperature=0.3, max_tokens=2048, model=model_id, timeout=timeout)


def _strip_code_fence(text: str) -> str:
    s = str(text or "").strip()
    m = re.fullmatch(r"```[A-Za-z0-9_-]*\n([\s\S]*?)\n```", s)
    return m.group(1) if m else s


def propose_edit(
    data_dir: str,
    doc_id: str,
    instruction: str,
    *,
    model: str = "assist",
    caller: Callable[[str, str, str], str] | None = None,
) -> dict[str, Any]:
    """Generate a reviewable AI edit proposal + unified diff without modifying the saved file."""
    instr = str(instruction or "").strip()
    if not instr:
        raise ValueError("Edit instruction must not be empty")
    doc = get_doc(data_dir, doc_id)
    system = (
        f"You are an expert editor working on a .{doc['kind']} document titled '{doc['title']}'. "
        "Apply the user's edit instruction cleanly and return ONLY the complete updated document text "
        "without commentary or surrounding markdown fences."
    )
    prompt = f"EDIT INSTRUCTION:\n{instr}\n\nCURRENT DOCUMENT:\n{doc['content']}"
    fn = caller or (lambda m, s, p: _call_editor_model(m, s, p))
    raw = fn(str(model or "assist"), system, prompt)
    proposed = _strip_code_fence(raw)
    diff = make_unified_diff(doc["content"], proposed, filename=f"{doc['id']}.{doc['kind']}")
    return {
        "ok": True,
        "proposal_id": f"prop-{uuid.uuid4().hex[:10]}",
        "doc_id": doc["id"],
        "title": doc["title"],
        "kind": doc["kind"],
        "model": str(model or "assist"),
        "original": doc["content"],
        "proposed": proposed,
        "diff": diff,
        "changed": proposed != doc["content"],
    }
