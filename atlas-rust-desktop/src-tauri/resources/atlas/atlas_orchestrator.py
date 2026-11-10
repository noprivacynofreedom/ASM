"""Shared Atlas chat-to-Swarm orchestration and conversation correlation."""
from __future__ import annotations
import re
import uuid
import atlas_observability as OPS

def submit_programming_task(conversation_id, description, files, project_name="atlas-project", priority=0):
    conversation_id = str(conversation_id or "").strip()
    description = str(description or "").strip()
    if not conversation_id or len(conversation_id) > 200:
        raise ValueError("A valid conversation_id (1-200 characters) is required")
    if not description or len(description) > 20000:
        raise ValueError("description must contain 1-20000 characters")
    if not isinstance(files, (dict, list)) or not files:
        raise ValueError("files must be a non-empty object or list of file entries")
    if not re.fullmatch(r"[A-Za-z0-9._ -]{1,80}", str(project_name or "")):
        raise ValueError("project_name contains unsupported characters")
    trace_id = "trc_" + uuid.uuid4().hex
    return OPS.submit_task({
        "type": "programming",
        "priority": priority,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "payload": {
            "conversation_id": conversation_id,
            "project_name": project_name,
            "description": description,
            "files": files,
        },
    })

def conversation_tasks(conversation_id, limit=50):
    return OPS.tasks_for_conversation(conversation_id, limit)
