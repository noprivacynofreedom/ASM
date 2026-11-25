"""Atlas GitHub MCP server (stdio, newline-delimited JSON-RPC). Standard library only.

Run:  python github_mcp.py

Token: GITHUB_TOKEN or GH_TOKEN, else the output of `gh auth token` (GitHub CLI login).
The token is only sent to api.github.com (or ATLAS_GITHUB_API for GitHub Enterprise / tests).
It is never returned in a tool result.

Tools (repo = "owner/name"):
  read:  github_list_repos, github_list_issues, github_get_issue, github_list_prs, github_get_pr,
         github_get_file, github_list_branches
  write: github_create_issue, github_comment, github_create_branch, github_put_file, github_create_pr
Approval tiers live in mcp_chat.TOOL_TIERS (reads = read, writes = consequential: they post on GitHub).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

API = os.environ.get("ATLAS_GITHUB_API", "https://api.github.com").rstrip("/")
MAX_TEXT = 20000
REPO_RE = re.compile(r"(?!\.+/)[A-Za-z0-9_.-]{1,100}/(?!\.+$)[A-Za-z0-9_.-]{1,100}")  # no "." / ".." parts
_TOKEN = None


def log(msg):
    sys.stderr.write(f"[github_mcp] {msg}\n")
    sys.stderr.flush()


def token():
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        if not _TOKEN and shutil.which("gh"):
            try:
                _TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                _TOKEN = ""
    if not _TOKEN:
        raise RuntimeError("No GitHub token: set GITHUB_TOKEN, or run `gh auth login` on this PC.")
    return _TOKEN


def api(method, path, body=None, query=None):
    url = API + path + ("?" + urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token(), "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "atlas-chat", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("message", "")
        except (ValueError, AttributeError):
            msg = ""
        raise RuntimeError(f"GitHub {e.code}: {msg or e.reason}") from None
    return json.loads(raw) if raw else {}


def repo(a):
    r = str(a.get("repo") or "").strip()
    if not REPO_RE.fullmatch(r):
        raise ValueError('repo must be "owner/name"')
    return "/repos/" + r


def num(a, key="number"):
    try:
        n = int(a.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number") from None
    if n < 1:
        raise ValueError(f"{key} must be 1 or more")
    return n


def need(a, key):
    v = str(a.get(key) or "").strip()
    if not v:
        raise ValueError(f"{key} is required")
    return v


def file_path(a):
    p = need(a, "path").strip("/")
    if any(part in ("", ".", "..") for part in p.split("/")):
        raise ValueError("path must be a plain repo path, no '.' or '..' parts")
    return quote(p)


def lim(a):
    try:
        return max(1, min(100, int(a.get("limit") or 30)))
    except (TypeError, ValueError):
        return 30


def lines(items, fmt):
    return "\n".join(fmt(x) for x in items) or "(none)"


def cut(text):
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n...[truncated]"


# ---- read tools ----
def github_list_repos(a):
    owner = str(a.get("owner") or "").strip()
    q = {"per_page": lim(a), "sort": "updated"}
    rows = api("GET", f"/users/{quote(owner, safe='')}/repos" if owner else "/user/repos", query=q)
    return lines(rows, lambda r: f"{r['full_name']}{' (private)' if r.get('private') else ''} - {r.get('description') or ''}")


def github_list_issues(a):
    q = {"state": a.get("state") or "open", "per_page": lim(a)}
    rows = [r for r in api("GET", repo(a) + "/issues", query=q) if "pull_request" not in r]
    return lines(rows, lambda r: f"#{r['number']} [{r['state']}] {r['title']} ({r['user']['login']})")


def github_get_issue(a):
    base = repo(a) + f"/issues/{num(a)}"
    i = api("GET", base)
    comments = api("GET", base + "/comments", query={"per_page": 50})
    out = f"#{i['number']} [{i['state']}] {i['title']}\nby {i['user']['login']}\n\n{i.get('body') or ''}"
    for c in comments:
        out += f"\n\n--- {c['user']['login']}:\n{c.get('body') or ''}"
    return cut(out)


def github_list_prs(a):
    rows = api("GET", repo(a) + "/pulls", query={"state": a.get("state") or "open", "per_page": lim(a)})
    return lines(rows, lambda r: f"#{r['number']} [{r['state']}] {r['title']} ({r['head']['ref']} -> {r['base']['ref']})")


def github_get_pr(a):
    base = repo(a) + f"/pulls/{num(a)}"
    p = api("GET", base)
    files = api("GET", base + "/files", query={"per_page": 100})
    out = (f"#{p['number']} [{p['state']}{', merged' if p.get('merged') else ''}] {p['title']}\n"
           f"{p['head']['ref']} -> {p['base']['ref']} by {p['user']['login']}\n\n{p.get('body') or ''}\n\nFiles:\n")
    out += lines(files, lambda f: f"{f['status']} {f['filename']} (+{f['additions']} -{f['deletions']})")
    return cut(out)


def github_get_file(a):
    q = {"ref": a["ref"]} if a.get("ref") else None
    f = api("GET", repo(a) + "/contents/" + file_path(a), query=q)
    if isinstance(f, list):
        return lines(f, lambda x: f"{x['type']} {x['path']}")
    text = base64.b64decode(f.get("content") or "").decode("utf-8", "replace")
    return cut(f"{f['path']} (sha {f['sha']})\n\n{text}")


def github_list_branches(a):
    rows = api("GET", repo(a) + "/branches", query={"per_page": lim(a)})
    return lines(rows, lambda b: f"{b['name']} {b['commit']['sha'][:8]}{' (protected)' if b.get('protected') else ''}")


# ---- write tools (approval: consequential) ----
def github_create_issue(a):
    i = api("POST", repo(a) + "/issues", {"title": need(a, "title"), "body": str(a.get("body") or "")})
    return f"Created issue #{i['number']}: {i['html_url']}"


def github_comment(a):
    c = api("POST", repo(a) + f"/issues/{num(a)}/comments", {"body": need(a, "body")})
    return f"Commented: {c['html_url']}"


def github_create_branch(a):
    r = repo(a)
    src = str(a.get("from") or "").strip() or api("GET", r)["default_branch"]
    sha = api("GET", r + "/git/ref/heads/" + quote(src))["object"]["sha"]
    api("POST", r + "/git/refs", {"ref": "refs/heads/" + need(a, "branch"), "sha": sha})
    return f"Created branch {a['branch']} from {src} ({sha[:8]})"


def github_put_file(a):
    body = {"message": need(a, "message"), "branch": need(a, "branch"),
            "content": base64.b64encode(str(a.get("content", "")).encode("utf-8")).decode()}
    if a.get("sha"):
        body["sha"] = str(a["sha"])  # needed to update an existing file (from github_get_file)
    out = api("PUT", repo(a) + "/contents/" + file_path(a), body)
    return f"Committed {a['path']} to {a['branch']}: {out['commit']['sha'][:8]}"


def github_create_pr(a):
    p = api("POST", repo(a) + "/pulls", {"title": need(a, "title"), "head": need(a, "head"),
                                          "base": need(a, "base"), "body": str(a.get("body") or "")})
    return f"Opened PR #{p['number']}: {p['html_url']}"


def _s(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


_STR, _INT = {"type": "string"}, {"type": "integer"}
_R = {"repo": {"type": "string", "description": 'owner/name, e.g. "octocat/hello-world"'}}
_STATE = {"type": "string", "enum": ["open", "closed", "all"]}
TOOLS = [
    ("github_list_repos", "List repositories of the signed-in user, or of an owner.", _s({"owner": _STR, "limit": _INT})),
    ("github_list_issues", "List issues (not PRs) of a repo.", _s({**_R, "state": _STATE, "limit": _INT}, ["repo"])),
    ("github_get_issue", "Read one issue with its comments.", _s({**_R, "number": _INT}, ["repo", "number"])),
    ("github_list_prs", "List pull requests of a repo.", _s({**_R, "state": _STATE, "limit": _INT}, ["repo"])),
    ("github_get_pr", "Read one pull request with its changed files.", _s({**_R, "number": _INT}, ["repo", "number"])),
    ("github_get_file", "Read a file (or list a folder) at a branch, tag or commit.", _s({**_R, "path": _STR, "ref": _STR}, ["repo", "path"])),
    ("github_list_branches", "List branches of a repo.", _s({**_R, "limit": _INT}, ["repo"])),
    ("github_create_issue", "Open a new issue.", _s({**_R, "title": _STR, "body": _STR}, ["repo", "title"])),
    ("github_comment", "Comment on an issue or pull request.", _s({**_R, "number": _INT, "body": _STR}, ["repo", "number", "body"])),
    ("github_create_branch", "Create a branch from another branch (default: the repo's default branch).", _s({**_R, "branch": _STR, "from": _STR}, ["repo", "branch"])),
    ("github_put_file", "Create or update one file with a commit on a branch. Pass sha to update an existing file.", _s({**_R, "path": _STR, "content": _STR, "message": _STR, "branch": _STR, "sha": _STR}, ["repo", "path", "content", "message", "branch"])),
    ("github_create_pr", "Open a pull request from head into base.", _s({**_R, "title": _STR, "head": _STR, "base": _STR, "body": _STR}, ["repo", "title", "head", "base"])),
]
_FN = {name: globals()[name] for name, _, _ in TOOLS}


def handle(msg):
    """Return a response dict, or None for notifications."""
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or "2024-11-05",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "atlas-github", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        fn = _FN.get(params.get("name"))
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
        try:
            result = {"content": [{"type": "text", "text": str(fn(params.get("arguments") or {}))}]}
        except Exception as exc:  # noqa: BLE001
            result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict):
            resp = handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
