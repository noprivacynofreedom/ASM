"""Real /swarm execution: one queued task and one plain-language log per bot.

Each subtask becomes an Atlas Ops task (so it shows in Operations and /swarm stop
can cancel it). Bots run ONE AT A TIME because one GPU holds one model; llama-swap
would otherwise unload and reload models for each parallel call.
Every log line is written for a person, not for a developer.
"""
from __future__ import annotations
import threading
import uuid

import atlas_observability as OPS

# Same model aliases as the 10x bots in index.html.
BOT_MODELS = {"10x: CTO": "mentor", "10x: Principal Architect": "mentor", "10x: Product Manager": "tasks",
              "10x: Engineering Manager": "tasks"}
MAX_REPLY_CHARS = 1700  # events are capped at 2000 characters


def _say(aid, tok, task, text, kind="swarm.log", level="info"):
    """Write one human-readable line to this bot's chat log."""
    OPS.ingest_event(aid, tok, {"kind": kind, "message": text[:2000], "level": level,
                                "task_id": task["task_id"], "trace_id": task.get("trace_id")})


def _words(n):
    return f"{n} word{'s' if n != 1 else ''}"


def _run_step(step, goal, call_llm):
    agent, job, task_type = step["agent"], step["task"], step["task_type"]
    reg = OPS.register({"name": agent, "model": BOT_MODELS.get(agent, "coder"),
                        "metadata": {"capability": "swarm-step"}})
    aid, tok = reg["agent_id"], reg["token"]
    try:
        got = OPS.claim_task(aid, tok, 600, [task_type])
        task = got and got.get("task")
        if not task:  # cancelled by /swarm stop, or already taken
            return False
        OPS.heartbeat(aid, tok, {"status": "busy", "task_id": task["task_id"], "task_stage": "thinking"})
        _say(aid, tok, task, f"I am {agent}. It is my turn now.")
        _say(aid, tok, task, f"My job: {job}")
        _say(aid, tok, task, "I am asking the AI model to think about this. It can take a minute or two.")
        prompt = (f"You are {agent} on a small software team. The team goal is: {goal}\n"
                  f"Your job: {job}\nAnswer in plain English, in under 250 words. Be concrete. No preamble.")
        try:
            reply = (call_llm(prompt, temperature=0.3, max_tokens=900, model=BOT_MODELS.get(agent, "coder")) or "").strip()
            if not reply:
                raise RuntimeError("the model sent back an empty answer")
        except Exception as exc:
            if OPS.finish_task(aid, tok, task["task_id"], {"status": "failed", "error": str(exc)[:500], "result": {}}):
                _say(aid, tok, task, f"Something went wrong, so I stopped. Reason: {str(exc)[:300]}", "swarm.failed", "error")
            return False  # if finish_task refused, the task was cancelled and the stop message is already logged
        _say(aid, tok, task, f"I got an answer back ({_words(len(reply.split()))}). Saving it.")
        if OPS.finish_task(aid, tok, task["task_id"], {"status": "completed", "result": {"answer": reply}}):
            shown = reply if len(reply) <= MAX_REPLY_CHARS else reply[:MAX_REPLY_CHARS] + " ..."
            _say(aid, tok, task, "Done. This is what I came up with:\n\n" + shown, "swarm.done")
        return True
    finally:
        OPS.heartbeat(aid, tok, {"status": "offline"})


def start(goal, subtasks, call_llm=None):
    """Queue one task per subtask and run them in the background. Returns what the UI needs to make chats."""
    if call_llm is None:
        import llm
        call_llm = llm.call_llm
    run_id = "sw" + uuid.uuid4().hex[:8]
    steps = []
    for i, st in enumerate(subtasks, 1):
        conv = f"{run_id}-{i}"
        step = {"conversation_id": conv, "agent": st["agent"], "task": st["task"], "task_type": f"swarm_{conv}"}
        sub = OPS.submit_task({"type": step["task_type"], "conversation_id": conv, "bot_id": st["agent"],
                               "payload": {"goal": goal, "task": st["task"]}})
        _say_queued(sub["task_id"], sub["trace_id"], conv, st)
        steps.append(step)

    def worker():
        for step in steps:
            try:
                _run_step(step, goal, call_llm)
            except Exception:  # one broken bot must not stop the rest of the team
                pass

    threading.Thread(target=worker, name=f"swarm-{run_id}", daemon=True).start()
    return {"run_id": run_id, "goal": goal,
            "steps": [{"conversation_id": s["conversation_id"], "agent": s["agent"], "task": s["task"]} for s in steps]}


def _say_queued(task_id, trace_id, conv, st):
    """The first line each chat shows, before the bot starts."""
    with OPS.LOCK, OPS._db() as c:
        OPS._event(c, None, task_id, "info", "swarm.log",
                   f"Waiting in line. {st['agent']} will start when the bots before it are finished.",
                   None, trace_id, conversation_id=conv, bot_id=st["agent"])
