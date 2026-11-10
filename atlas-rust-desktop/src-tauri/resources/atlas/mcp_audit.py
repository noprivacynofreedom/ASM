"""Canonical, bounded-lifecycle audit recording for Atlas MCP tool calls."""
from __future__ import annotations

import time
import uuid


def build_event(event, context=None):
    """Return a consistent MCP audit event while retaining execution evidence."""
    if not isinstance(event, dict):
        raise TypeError("MCP audit event must be an object")

    context = context if isinstance(context, dict) else {}
    row = dict(event)
    row.setdefault("event_id", uuid.uuid4().hex)
    row["event_type"] = "mcp.tool"
    row["event_version"] = 1

    status = str(row.get("status") or "UNKNOWN").upper()
    row["status"] = status
    row["verification"] = row.get("verification") or "not_performed"
    row.setdefault("timestamp", time.time())
    row.setdefault("duration_ms", None)
    row.setdefault("adapter_duration_ms", None)
    row.setdefault("server", None)
    row.setdefault("tool", None)

    conversation_id = context.get("conversation_id") or row.get("conversation_id")
    bot_id = context.get("bot_id") or row.get("bot_id")
    trace_id = context.get("request_id") or context.get("trace_id") or row.get("trace_id")
    queue_job_id = context.get("queue_job_id")
    if queue_job_id is None:
        queue_job_id = row.get("queue_job_id")
    row["conversation_id"] = str(conversation_id or "")[:128] or None
    row["bot_id"] = str(bot_id or "")[:128] or None
    row["trace_id"] = str(trace_id or "")[:128] or None
    row["queue_job_id"] = str(queue_job_id)[:128] if queue_job_id is not None else None
    return row


class MCPAuditRecorder:
    """Append canonical events before optional OPS delivery; sink failures are non-fatal."""

    def __init__(self, events, lock, ops_record=None):
        self.events = events
        self.lock = lock
        self.ops_record = ops_record

    def record(self, event, context=None):
        row = build_event(event, context)
        with self.lock:
            self.events.appendleft(row)

        conversation_id = row.get("conversation_id")
        if conversation_id and self.ops_record:
            level = "error" if row["status"] == "FAILED" else "info"
            label = f"{row.get('server') or 'MCP'} / {row.get('tool') or 'tool'}: {row['status']}"
            try:
                self.ops_record(
                    conversation_id,
                    row.get("bot_id") or "",
                    "mcp.tool",
                    label,
                    row,
                    level,
                    row.get("trace_id"),
                )
            except Exception as exc:
                # The local MCP audit must survive optional observability failures.
                row["audit_sink_error"] = f"{type(exc).__name__}: {exc}"
        return row
