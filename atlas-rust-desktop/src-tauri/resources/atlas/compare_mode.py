"""Blind side-by-side model comparison mode for Atlas Chat (/compare).

Fans out a single prompt concurrently across 2–4 models (local llama-swap
aliases, LAN compute peers, or enabled cloud models), shuffles their display
order behind blind labels (Model A, Model B, ...), and only reveals real model
identities after the user votes or explicitly reveals.

Votes and speed metrics can be appended to ``.atlas/compare_history.jsonl`` to
build a local-vs-cloud leaderboard without touching user chat history.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import secrets
import threading
import time
import uuid
from typing import Any, Callable

import cloud_llm
import llm

_RNG = secrets.SystemRandom()
_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}
_MAX_SESSIONS = 50
_SLOTS = ("A", "B", "C", "D")


def _default_call_model(
    model_id: str,
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    timeout: int = 120,
) -> tuple[str, str]:
    """Call either a cloud model (``cloud:...``) or local/LAN model via ``llm.py``.

    Returns ``(text, machine_label)``.
    """
    messages: list[dict[str, str]] = []
    if system.strip():
        messages.append({"role": "system", "content": system.strip()})
    messages.append({"role": "user", "content": prompt})

    if cloud_llm.is_cloud_model(model_id):
        completion, machine = cloud_llm.chat_completion(
            {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        text = str((((completion.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")
        return text, machine

    combined = f"{system.strip()}\n\n{prompt}" if system.strip() else prompt
    text = llm.call_llm(
        combined,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model_id,
        timeout=timeout,
    )
    return str(text or ""), "Local / LAN"


def _prune_sessions_locked() -> None:
    while len(_SESSIONS) > _MAX_SESSIONS:
        oldest = next(iter(_SESSIONS))
        _SESSIONS.pop(oldest, None)


def _public_entry(entry: dict[str, Any], reveal: bool) -> dict[str, Any]:
    out = {
        "slot": entry["slot"],
        "label": entry["label"],
        "ok": entry["ok"],
        "text": entry["text"],
        "error": entry["error"],
        "latency_ms": entry["latency_ms"],
        "est_tokens": entry["est_tokens"],
        "tok_per_sec": entry["tok_per_sec"],
    }
    if reveal:
        out["model"] = entry["model"]
        out["machine"] = entry["machine"]
    return out


def run_compare(
    prompt: str,
    models: list[str],
    *,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    timeout: int = 120,
    caller: Callable[..., tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Run ``prompt`` across 2–4 models concurrently and return blind results."""
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise ValueError("Prompt must not be empty")
    if not isinstance(models, list):
        raise ValueError("models must be a list of 2 to 4 model IDs")

    cleaned_models: list[str] = []
    seen: set[str] = set()
    for m in models:
        mid = str(m or "").strip()
        if mid and mid not in seen:
            seen.add(mid)
            cleaned_models.append(mid)

    if len(cleaned_models) < 2 or len(cleaned_models) > 4:
        raise ValueError("Pick between 2 and 4 distinct models to compare")

    call_fn = caller or _default_call_model
    shuffled = list(cleaned_models)
    _RNG.shuffle(shuffled)

    def _run_one(slot: str, model_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            text, machine = call_fn(
                model_id,
                prompt_text,
                system=system,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                timeout=int(timeout),
            )
            elapsed = max(0.001, time.perf_counter() - started)
            est_tokens = max(1, len(text) // 4) if text else 0
            return {
                "slot": slot,
                "label": f"Model {slot}",
                "model": model_id,
                "machine": str(machine or ""),
                "ok": True,
                "text": text,
                "error": "",
                "latency_ms": round(elapsed * 1000.0, 1),
                "est_tokens": est_tokens,
                "tok_per_sec": round(est_tokens / elapsed, 1) if est_tokens else 0.0,
            }
        except Exception as exc:
            elapsed = max(0.001, time.perf_counter() - started)
            return {
                "slot": slot,
                "label": f"Model {slot}",
                "model": model_id,
                "machine": "",
                "ok": False,
                "text": "",
                "error": str(exc),
                "latency_ms": round(elapsed * 1000.0, 1),
                "est_tokens": 0,
                "tok_per_sec": 0.0,
            }

    pairs = [( _SLOTS[i], shuffled[i] ) for i in range(len(shuffled))]
    entries_by_slot: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pairs)) as pool:
        futures = {pool.submit(_run_one, slot, mid): slot for slot, mid in pairs}
        for fut in concurrent.futures.as_completed(futures):
            row = fut.result()
            entries_by_slot[row["slot"]] = row

    ordered = [entries_by_slot[slot] for slot, _ in pairs]
    compare_id = f"cmp-{uuid.uuid4().hex[:12]}"
    session = {
        "compare_id": compare_id,
        "created_at": time.time(),
        "prompt": prompt_text,
        "revealed": False,
        "winner_slot": None,
        "entries": ordered,
    }

    with _LOCK:
        _SESSIONS[compare_id] = session
        _prune_sessions_locked()

    return {
        "ok": True,
        "compare_id": compare_id,
        "prompt": prompt_text,
        "blind": True,
        "revealed": False,
        "entries": [_public_entry(e, reveal=False) for e in ordered],
    }


def _append_history(history_path: str, record: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(history_path)), exist_ok=True)
    with _LOCK:
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def vote_compare(
    compare_id: str,
    winner_slot: str,
    *,
    history_path: str | None = None,
) -> dict[str, Any]:
    """Record a vote for ``winner_slot`` (e.g. ``'A'`` or ``'tie'``) and reveal models."""
    cid = str(compare_id or "").strip()
    choice = str(winner_slot or "").strip()
    if choice.lower() == "tie":
        choice = "tie"
    else:
        choice = choice.upper()

    with _LOCK:
        session = _SESSIONS.get(cid)
        if not session:
            raise KeyError(f"Unknown compare session: {cid}")
        valid_slots = {e["slot"] for e in session["entries"]}
        if choice != "tie" and choice not in valid_slots:
            raise ValueError(f"winner_slot must be 'tie' or one of {sorted(valid_slots)}")
        session["revealed"] = True
        session["winner_slot"] = choice
        entries = list(session["entries"])
        prompt = session["prompt"]

    winner_model = None
    if choice != "tie":
        for e in entries:
            if e["slot"] == choice:
                winner_model = e["model"]
                break

    record = {
        "compare_id": cid,
        "timestamp": time.time(),
        "prompt_preview": prompt[:160],
        "winner_slot": choice,
        "winner_model": winner_model,
        "models": [
            {
                "slot": e["slot"],
                "model": e["model"],
                "machine": e["machine"],
                "ok": e["ok"],
                "latency_ms": e["latency_ms"],
                "tok_per_sec": e["tok_per_sec"],
            }
            for e in entries
        ],
    }
    if history_path:
        _append_history(history_path, record)

    return {
        "ok": True,
        "compare_id": cid,
        "blind": False,
        "revealed": True,
        "winner_slot": choice,
        "winner_model": winner_model,
        "entries": [_public_entry(e, reveal=True) for e in entries],
    }


def reveal_compare(compare_id: str) -> dict[str, Any]:
    """Reveal real model identities without recording a vote."""
    cid = str(compare_id or "").strip()
    with _LOCK:
        session = _SESSIONS.get(cid)
        if not session:
            raise KeyError(f"Unknown compare session: {cid}")
        session["revealed"] = True
        entries = list(session["entries"])
        winner_slot = session["winner_slot"]

    return {
        "ok": True,
        "compare_id": cid,
        "blind": False,
        "revealed": True,
        "winner_slot": winner_slot,
        "entries": [_public_entry(e, reveal=True) for e in entries],
    }


def list_history(history_path: str, limit: int = 30) -> list[dict[str, Any]]:
    """Read the most recent compare votes from ``history_path``."""
    if not history_path or not os.path.isfile(history_path):
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        rows.append(item)
                except ValueError:
                    continue
    except OSError:
        return []
    return rows[-max(1, int(limit)):][::-1]


def leaderboard(history_path: str) -> list[dict[str, Any]]:
    """Aggregate per-model win-rate, tie-rate, latency, and tok/s."""
    rows = list_history(history_path, limit=1000)
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        winner = row.get("winner_model")
        is_tie = row.get("winner_slot") == "tie"
        for m in row.get("models") or []:
            mid = str(m.get("model") or "").strip()
            if not mid:
                continue
            bucket = stats.setdefault(
                mid,
                {"model": mid, "matches": 0, "wins": 0, "ties": 0, "latency_sum": 0.0, "tps_sum": 0.0, "ok_count": 0},
            )
            bucket["matches"] += 1
            if is_tie:
                bucket["ties"] += 1
            elif winner == mid:
                bucket["wins"] += 1
            if m.get("ok"):
                bucket["ok_count"] += 1
                bucket["latency_sum"] += float(m.get("latency_ms") or 0.0)
                bucket["tps_sum"] += float(m.get("tok_per_sec") or 0.0)

    out: list[dict[str, Any]] = []
    for bucket in stats.values():
        matches = bucket["matches"]
        ok_n = bucket["ok_count"]
        out.append(
            {
                "model": bucket["model"],
                "matches": matches,
                "wins": bucket["wins"],
                "ties": bucket["ties"],
                "win_rate": round((bucket["wins"] / matches) * 100.0, 1) if matches else 0.0,
                "avg_latency_ms": round(bucket["latency_sum"] / ok_n, 1) if ok_n else 0.0,
                "avg_tok_per_sec": round(bucket["tps_sum"] / ok_n, 1) if ok_n else 0.0,
            }
        )
    out.sort(key=lambda r: (-r["wins"], -r["win_rate"], r["avg_latency_ms"]))
    return out
