"""Backend API handlers for Atlas CTF Swarm rooms and Conduit orchestration state/devlog.

Stdlib-only module loaded by server.py so the Tauri desktop shell (CTF & Conduit tabs)
can persist Conduit state/DEVLOG.md and coordinate live /swarm CTF rooms on port 8090
without requiring an extra Node/Express process.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_ROOMS: dict[str, dict[str, Any]] = {}
_VALID_ROLES = {"player", "organizer", "admin"}


def sanitize_room_id(raw: Any) -> str:
    if not isinstance(raw, str):
        return "atlas-alpha"
    cleaned = re.sub(r"[^a-z0-9_-]", "", raw.strip().lower())[:48]
    return cleaned if len(cleaned) >= 2 else "atlas-alpha"


def _make_event_id() -> str:
    return f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:7]}"


def _get_or_create_room(room_id: str) -> dict[str, Any]:
    safe_id = sanitize_room_id(room_id)
    room = _ROOMS.get(safe_id)
    if room is None:
        room = {
            "roomId": safe_id,
            "peers": {},
            "claims": {},
            "sharedNotes": {},
            "archiveManifest": None,
            "feed": [],
            "lastFocus": None,
        }
        _ROOMS[safe_id] = room
    return room


def _push_feed(room: dict[str, Any], item: dict[str, Any]) -> None:
    if any(existing.get("id") == item.get("id") for existing in room["feed"]):
        return
    room["feed"].append(item)
    if len(room["feed"]) > 100:
        room["feed"] = room["feed"][-100:]


def _serialize_room(room: dict[str, Any]) -> dict[str, Any]:
    return {
        "roomId": room["roomId"],
        "peers": list(room["peers"].values()),
        "claims": dict(room["claims"]),
        "sharedNotes": dict(room["sharedNotes"]),
        "archiveManifest": room["archiveManifest"],
        "feed": list(room["feed"][-100:]),
        "lastFocus": room.get("lastFocus"),
    }


def list_swarm_rooms() -> dict[str, Any]:
    with _LOCK:
        summary = [
            {
                "roomId": r["roomId"],
                "peerCount": len(r["peers"]),
                "claimCount": len(r["claims"]),
                "hasArchive": bool(r["archiveManifest"]),
            }
            for r in _ROOMS.values()
            if r["peers"]
        ]
    return {"rooms": summary}


def get_swarm_room(room_id: str) -> dict[str, Any]:
    with _LOCK:
        room = _get_or_create_room(room_id)
        return _serialize_room(room)


def handle_swarm_event(room_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object for swarm event")
    ev_type = str(payload.get("type") or "").strip()
    if not ev_type:
        raise ValueError("Missing swarm event type")

    now_ms = int(time.time() * 1000)
    with _LOCK:
        room = _get_or_create_room(room_id)
        session_id = str(payload.get("sessionId") or "").strip()[:64]
        handle = str(payload.get("handle") or "operator").strip()[:40] or "operator"
        role = str(payload.get("role") or "player").strip().lower()
        if role not in _VALID_ROLES:
            role = "player"

        if ev_type == "room:join":
            if not session_id:
                session_id = f"sess-{uuid.uuid4().hex[:8]}"
            peer = {
                "sessionId": session_id,
                "uid": str(payload.get("uid") or session_id)[:64],
                "handle": handle,
                "role": role,
                "activeView": str(payload.get("activeView") or "curriculum")[:32],
                "activeChallengeId": payload.get("activeChallengeId"),
                "joinedAt": now_ms,
            }
            already_present = session_id in room["peers"]
            room["peers"][session_id] = peer
            if not already_present:
                _push_feed(room, {
                    "id": _make_event_id(),
                    "type": "join",
                    "handle": handle,
                    "role": role,
                    "text": f"joined room #{room['roomId']}",
                    "timestamp": now_ms,
                })

        elif ev_type == "room:leave":
            peer = room["peers"].pop(session_id, None)
            for cid in [k for k, v in room["claims"].items() if v.get("sessionId") == session_id]:
                room["claims"].pop(cid, None)
            if peer:
                _push_feed(room, {
                    "id": _make_event_id(),
                    "type": "leave",
                    "handle": peer["handle"],
                    "role": peer["role"],
                    "text": f"left room #{room['roomId']}",
                    "timestamp": now_ms,
                })

        elif ev_type == "presence:update":
            peer = room["peers"].get(session_id)
            if peer:
                if "activeView" in payload:
                    peer["activeView"] = str(payload.get("activeView") or peer["activeView"])[:32]
                if "activeChallengeId" in payload:
                    peer["activeChallengeId"] = payload.get("activeChallengeId")

        elif ev_type == "claim:toggle":
            cid = str(payload.get("challengeId") or "").strip()[:80]
            if cid:
                existing = room["claims"].get(cid)
                if existing and existing.get("sessionId") == session_id:
                    room["claims"].pop(cid, None)
                    _push_feed(room, {
                        "id": _make_event_id(),
                        "type": "claim",
                        "handle": handle,
                        "role": role,
                        "challengeId": cid,
                        "text": f"released claim on {cid}",
                        "timestamp": now_ms,
                    })
                else:
                    room["claims"][cid] = {
                        "challengeId": cid,
                        "sessionId": session_id or handle,
                        "handle": handle,
                        "claimedAt": now_ms,
                    }
                    _push_feed(room, {
                        "id": _make_event_id(),
                        "type": "claim",
                        "handle": handle,
                        "role": role,
                        "challengeId": cid,
                        "text": f"claimed target {cid}",
                        "timestamp": now_ms,
                    })

        elif ev_type == "note:sync":
            cid = str(payload.get("challengeId") or "").strip()[:80]
            content = str(payload.get("content") or "")[:12000]
            if cid:
                room["sharedNotes"][cid] = {
                    "challengeId": cid,
                    "content": content,
                    "updatedBy": handle,
                    "updatedAt": now_ms,
                }

        elif ev_type == "archive:share":
            file_name = str(payload.get("fileName") or "Nightmare.zip")[:120]
            paths = [str(p)[:240] for p in (payload.get("paths") or [])[:500]]
            file_count = int(payload.get("fileCount") or len(paths))
            room["archiveManifest"] = {
                "fileName": file_name,
                "fileCount": file_count,
                "sharedBy": handle,
                "paths": paths,
                "sharedAt": now_ms,
            }
            _push_feed(room, {
                "id": _make_event_id(),
                "type": "archive",
                "handle": handle,
                "role": role,
                "text": f"synced archive manifest {file_name} ({file_count} files)",
                "timestamp": now_ms,
            })

        elif ev_type == "flag:announce":
            cid = str(payload.get("challengeId") or "").strip()[:80]
            title = str(payload.get("title") or cid)[:120]
            pts = int(payload.get("points") or 0)
            _push_feed(room, {
                "id": _make_event_id(),
                "type": "flag",
                "handle": handle,
                "role": role,
                "challengeId": cid,
                "text": f"verified flag for {title} (+{pts} pts)",
                "timestamp": now_ms,
            })

        elif ev_type == "focus:broadcast":
            cid = str(payload.get("challengeId") or "").strip()[:80]
            if cid:
                room["lastFocus"] = {
                    "id": _make_event_id(),
                    "challengeId": cid,
                    "handle": handle,
                    "sessionId": session_id,
                    "timestamp": now_ms,
                }
                _push_feed(room, {
                    "id": _make_event_id(),
                    "type": "focus",
                    "handle": handle,
                    "role": role,
                    "challengeId": cid,
                    "text": f"focused swarm on {cid}",
                    "timestamp": now_ms,
                })

        elif ev_type == "feed:post":
            text = str(payload.get("text") or "").strip()[:2000]
            if text:
                _push_feed(room, {
                    "id": _make_event_id(),
                    "type": "message",
                    "handle": handle,
                    "role": role,
                    "text": text,
                    "challengeId": payload.get("challengeId"),
                    "timestamp": now_ms,
                })
        else:
            raise ValueError(f"Unsupported swarm event type: {ev_type}")

        return _serialize_room(room)


def reset_swarm_rooms_for_tests() -> None:
    with _LOCK:
        _ROOMS.clear()


# --- Conduit State & DEVLOG.md persistence ---

def _conduit_state_path(data_dir: str | Path) -> Path:
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "conduit-orchestrator-state.json"


def _devlog_path(data_dir: str | Path) -> Path:
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "DEVLOG.md"


def conduit_health() -> dict[str, Any]:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    return {
        "ok": True,
        "project": "atlas-chat",
        "orchestrator": "Conduit",
        "geminiConfigured": bool(key and key != "MY_GEMINI_API_KEY"),
    }


def read_conduit_state(data_dir: str | Path) -> dict[str, Any]:
    path = _conduit_state_path(data_dir)
    if not path.exists():
        return {"state": None}
    try:
        return {"state": json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return {"state": None}


def write_conduit_state(data_dir: str | Path, state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("Invalid orchestrator state payload")
    path = _conduit_state_path(data_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return {"ok": True}


def reset_conduit_state(data_dir: str | Path) -> dict[str, Any]:
    path = _conduit_state_path(data_dir)
    if path.exists():
        path.unlink()
    return {"ok": True}


def read_devlog(data_dir: str | Path) -> dict[str, Any]:
    path = _devlog_path(data_dir)
    if not path.exists():
        # Seed from repo DEVLOG.md if available next to resources, else header
        default_text = "# Atlas Chat — Conduit Orchestration Devlog\n\nNo entries yet.\n"
        return {"filePath": str(path), "content": default_text}
    return {"filePath": str(path), "content": path.read_text(encoding="utf-8")}


def append_devlog(data_dir: str | Path, entry: dict[str, Any]) -> dict[str, Any]:
    title = str(entry.get("title") or "").strip()
    summary = str(entry.get("summary") or "").strip()
    if not title or not summary:
        raise ValueError("Title and summary are required to append to DEVLOG.md")
    author = str(entry.get("authorHandle") or "@release-lead").strip()
    target = str(entry.get("targetHandle") or "@all-agents").strip()
    branch = str(entry.get("branch") or "").strip()
    files = entry.get("files") if isinstance(entry.get("files"), list) else []

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "",
        f"## {stamp} · {title}",
        f"- **Author**: `{author}` -> `{target}`",
    ]
    if branch:
        lines.append(f"- **Branch**: `{branch}`")
    lines.append(f"- **Summary**: {summary}")
    if files:
        lines.append("- **Files**:")
        for f in files[:40]:
            lines.append(f"  - `{f}`")
    lines.append("")

    path = _devlog_path(data_dir)
    if not path.exists():
        path.write_text("# Atlas Chat — Conduit Orchestration Devlog\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return {"ok": True, "filePath": str(path), "content": path.read_text(encoding="utf-8")}
