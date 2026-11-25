"""Governed Skills Registry for Atlas Chat (Phase 2A).

Stores declarative reusable agent skills under ``<DATA_DIR>/.atlas/skills/`` as
``<skill_id>/SKILL.md`` files with lightweight YAML frontmatter.

Governance invariant:
  A skill declares ``tier`` (``read`` or ``write``) and ``allowed_tools``.
  When cross-checked against ``mcp_chat.TOOL_TIERS`` (or known write-tool
  prefixes), any skill that references a write/mutating/shell tool is
  automatically promoted to ``effective_tier = "write"`` so skills can NEVER
  bypass Atlas's interactive write-approval gate or ``mcp_audit.py``.
"""
from __future__ import annotations

import difflib
import os
import re
import time
import uuid
from typing import Any, Callable

import cloud_llm
import llm

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_WRITE_TOOL_HINTS = ("write", "delete", "remove", "shell", "exec", "run_command", "commit", "push", "send", "create", "edit", "patch")


def _skills_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, ".atlas", "skills")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_id(skill_id: str) -> str:
    cleaned = str(skill_id or "").strip().lower()
    if not _ID_RE.fullmatch(cleaned):
        raise ValueError("Skill id must be lowercase letters, numbers, hyphens, or underscores (1–64 chars)")
    return cleaned


def _skill_path(data_dir: str, skill_id: str) -> str:
    return os.path.join(_skills_dir(data_dir), _safe_id(skill_id), "SKILL.md")


def _tool_tiers_map() -> dict[str, str]:
    try:
        import mcp_chat  # type: ignore
        tiers = getattr(mcp_chat, "TOOL_TIERS", None)
        if isinstance(tiers, dict):
            return {str(k): str(v) for k, v in tiers.items()}
    except Exception:
        pass
    return {}


def evaluate_governance(
    declared_tier: str,
    allowed_tools: list[str],
    *,
    tool_tiers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compute effective tier and approval requirement for a skill."""
    decl = str(declared_tier or "read").strip().lower()
    if decl not in ("read", "write"):
        decl = "write"
    tiers = tool_tiers if tool_tiers is not None else _tool_tiers_map()

    write_triggers: list[str] = []
    for tool in allowed_tools:
        t = str(tool or "").strip()
        if not t:
            continue
        known = tiers.get(t)
        if known == "write":
            write_triggers.append(t)
        elif known is None and any(h in t.lower() for h in _WRITE_TOOL_HINTS):
            write_triggers.append(t)

    effective = "write" if (decl == "write" or write_triggers) else "read"
    return {
        "declared_tier": decl,
        "effective_tier": effective,
        "requires_approval": effective == "write",
        "promoted_by_tools": write_triggers,
    }


def _render_skill_md(meta: dict[str, Any], body: str) -> str:
    tools_csv = ", ".join(meta.get("allowed_tools") or [])
    lines = [
        "---",
        f"name: {meta.get('name', meta.get('id', 'Skill'))}",
        f"description: {meta.get('description', '')}",
        f"tier: {meta.get('tier', 'read')}",
        f"enabled: {'true' if meta.get('enabled', True) else 'false'}",
        f"allowed_tools: {tools_csv}",
        "---",
        "",
        str(body or "").strip(),
        "",
    ]
    return "\n".join(lines)


def _parse_skill_md(skill_id: str, raw: str, tool_tiers: dict[str, str] | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "id": skill_id,
        "name": skill_id,
        "description": "",
        "tier": "read",
        "enabled": True,
        "allowed_tools": [],
    }
    body = str(raw or "")
    m = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$", body)
    if m:
        front, body = m.group(1), m.group(2)
        for line in front.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            key, val = k.strip().lower(), v.strip()
            if key == "name" and val:
                meta["name"] = val
            elif key == "description":
                meta["description"] = val
            elif key == "tier" and val.lower() in ("read", "write"):
                meta["tier"] = val.lower()
            elif key == "enabled":
                meta["enabled"] = val.lower() in ("true", "1", "yes")
            elif key == "allowed_tools":
                meta["allowed_tools"] = [x.strip() for x in val.split(",") if x.strip()]

    gov = evaluate_governance(meta["tier"], meta["allowed_tools"], tool_tiers=tool_tiers)
    return {
        **meta,
        "body": body.strip(),
        "governance": gov,
        "effective_tier": gov["effective_tier"],
        "requires_approval": gov["requires_approval"],
    }


def list_skills(data_dir: str, *, tool_tiers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """List all skills in ``<DATA_DIR>/.atlas/skills/`` with governance metadata."""
    root = _skills_dir(data_dir)
    rows: list[dict[str, Any]] = []
    for entry in sorted(os.listdir(root)):
        if not _ID_RE.fullmatch(entry):
            continue
        md_path = os.path.join(root, entry, "SKILL.md")
        if not os.path.isfile(md_path):
            continue
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                raw = f.read()
            skill = _parse_skill_md(entry, raw, tool_tiers=tool_tiers)
            skill["updated_at"] = os.path.getmtime(md_path)
            rows.append(skill)
        except OSError:
            continue
    return rows


def get_skill(data_dir: str, skill_id: str, *, tool_tiers: dict[str, str] | None = None) -> dict[str, Any]:
    sid = _safe_id(skill_id)
    md_path = _skill_path(data_dir, sid)
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"Skill not found: {sid}")
    with open(md_path, "r", encoding="utf-8") as f:
        raw = f.read()
    skill = _parse_skill_md(sid, raw, tool_tiers=tool_tiers)
    skill["updated_at"] = os.path.getmtime(md_path)
    return skill


def save_skill(
    data_dir: str,
    skill_id: str,
    *,
    name: str,
    description: str = "",
    body: str = "",
    tier: str = "read",
    enabled: bool = True,
    allowed_tools: list[str] | None = None,
    tool_tiers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create or atomically update a governed ``SKILL.md``."""
    sid = _safe_id(skill_id)
    clean_name = str(name or "").strip() or sid
    clean_tier = str(tier or "read").strip().lower()
    if clean_tier not in ("read", "write"):
        raise ValueError("tier must be 'read' or 'write'")
    tools = [str(t).strip() for t in (allowed_tools or []) if str(t).strip()]
    md_path = _skill_path(data_dir, sid)
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    rendered = _render_skill_md(
        {
            "id": sid,
            "name": clean_name,
            "description": str(description or "").strip(),
            "tier": clean_tier,
            "enabled": bool(enabled),
            "allowed_tools": tools,
        },
        body,
    )
    tmp = md_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(rendered)
    os.replace(tmp, md_path)
    return get_skill(data_dir, sid, tool_tiers=tool_tiers)


def delete_skill(data_dir: str, skill_id: str) -> dict[str, Any]:
    sid = _safe_id(skill_id)
    md_path = _skill_path(data_dir, sid)
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"Skill not found: {sid}")
    os.remove(md_path)
    try:
        os.rmdir(os.path.dirname(md_path))
    except OSError:
        pass
    return {"ok": True, "deleted": sid}


def refine_skill(
    data_dir: str,
    skill_id: str,
    feedback: str,
    *,
    model: str = "assist",
    caller: Callable[[str, str], str] | None = None,
    tool_tiers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Propose an improved skill body + unified diff without mutating disk."""
    fb = str(feedback or "").strip()
    if not fb:
        raise ValueError("Refinement feedback must not be empty")
    skill = get_skill(data_dir, skill_id, tool_tiers=tool_tiers)
    prompt = (
        f"You are refining a reusable AI agent skill named '{skill['name']}'. "
        "Update the Markdown instructions below based on the user's feedback. "
        "Return ONLY the updated Markdown instructions body (no YAML frontmatter).\n\n"
        f"FEEDBACK:\n{fb}\n\nCURRENT INSTRUCTIONS:\n{skill['body']}"
    )
    if caller is not None:
        proposed_body = str(caller(str(model or "assist"), prompt) or "").strip()
    elif cloud_llm.is_cloud_model(model):
        comp, _ = cloud_llm.chat_completion(
            {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 1500}
        )
        proposed_body = str((((comp.get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()
    else:
        proposed_body = str(llm.call_llm(prompt, temperature=0.3, max_tokens=1500, model=model) or "").strip()

    diff = "".join(
        difflib.unified_diff(
            skill["body"].splitlines(keepends=True),
            proposed_body.splitlines(keepends=True),
            fromfile=f"a/{skill['id']}/SKILL.md",
            tofile=f"b/{skill['id']}/SKILL.md",
            n=3,
        )
    )
    return {
        "ok": True,
        "proposal_id": f"skp-{uuid.uuid4().hex[:10]}",
        "skill_id": skill["id"],
        "original_body": skill["body"],
        "proposed_body": proposed_body,
        "diff": diff,
        "changed": proposed_body != skill["body"],
        "governance": skill["governance"],
    }


def active_skills_prompt(data_dir: str, *, tool_tiers: dict[str, str] | None = None) -> str:
    """Return a compact prompt summary of enabled governed skills."""
    enabled = [s for s in list_skills(data_dir, tool_tiers=tool_tiers) if s.get("enabled")]
    if not enabled:
        return ""
    blocks = []
    for s in enabled:
        blocks.append(f"### Skill: {s['name']} [{s['effective_tier']}]\n{s['body']}")
    return "\n\n".join(blocks)
