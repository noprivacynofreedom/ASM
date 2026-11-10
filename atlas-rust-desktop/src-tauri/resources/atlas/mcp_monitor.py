"""Thread-safe MCP stdio host for Atlas Chat.

Uses a dedicated stdout reader and request-id queue so protocol timeouts are real
and do not block on TextIO.readline(). Tool results are recorded as execution
 evidence; verification is a separate, explicit state.
"""
from __future__ import annotations
import json
import os
import queue
import subprocess
import threading
import time
import uuid


def build_mcp_specs(raw, project, python_executable, workspace=""):
    """Normalize persisted MCP settings into safe argv-based host specs.

    The handshake timeout is deliberately passed through to MCPConnection;
    otherwise per-server settings silently fall back to the default.
    """
    specs = []
    rows = raw if isinstance(raw, list) else []
    for item in rows:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        command = item.get("command", [])
        if not isinstance(command, list):
            continue
        cmd = [
            str(value).replace("{python}", python_executable).replace("{project}", project).replace("{workspace}", workspace or project)
            for value in command
        ]
        if not cmd or not cmd[0].strip():
            continue
        cwd = str(item.get("cwd", project)).replace("{project}", project).replace("{workspace}", workspace or project)
        raw_env = item.get("env", {})
        env = {
            str(key): os.path.expandvars(str(value))
            for key, value in raw_env.items()
        } if isinstance(raw_env, dict) else {}
        env = {key: value.replace("{workspace}", workspace or project) for key, value in env.items()}
        if workspace:
            # The user-chosen working directory reaches every MCP server (mcp_commander reads this).
            env.setdefault("ATLAS_WORKSPACE", workspace)
        try:
            handshake_timeout = float(item.get("handshake_timeout", 20))
            if not (handshake_timeout == handshake_timeout and abs(handshake_timeout) < float("inf")):
                raise ValueError("timeout must be finite")
        except (TypeError, ValueError, OverflowError):
            handshake_timeout = 20.0
        handshake_timeout = max(1.0, min(60.0, handshake_timeout))
        name = str(item.get("name") or cmd[-1])
        taken = {spec["name"] for spec in specs}
        if name in taken:  # two servers with one name would silently replace each other in the monitor
            counter = 2
            while f"{name}-{counter}" in taken:
                counter += 1
            name = f"{name}-{counter}"
        specs.append({
            "name": name,
            "command": cmd,
            "cwd": cwd,
            "env": env,
            "handshake_timeout": handshake_timeout,
        })
    return specs


class MCPConnection:
    def __init__(self, spec):
        self.spec = spec
        self.proc = None
        self.lock = threading.RLock()
        self.tools = []
        self.state = "stopped"
        self.error = None
        self.last_check = None
        self.started_at = None
        self.latency_ms = None
        self.stderr_tail = ""
        self.responses = {}
        self.pending_lock = threading.Lock()
        self.reader_thread = None
        self.stderr_thread = None
        self.last_execution = None

    def _read_stdout(self, proc):
        """Continuously dispatch JSON-RPC replies without blocking callers."""
        try:
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except (ValueError, TypeError):
                    self.stderr_tail = (self.stderr_tail + "[stdout non-JSON] " + line)[-4000:]
                    continue
                if not isinstance(msg, dict):
                    # A bare number/array/string line is not JSON-RPC. It used to raise here and kill
                    # the reader, which made every later call time out.
                    self.stderr_tail = (self.stderr_tail + "[stdout non-object] " + line)[-4000:]
                    continue
                request_id = msg.get("id")
                if request_id is not None and "method" not in msg:
                    # "method" present = a request FROM the server (ping, sampling, roots); it is not a reply.
                    with self.pending_lock:
                        waiter = self.responses.get(str(request_id))
                    if waiter is not None:
                        try:
                            waiter.put_nowait(msg)
                        except queue.Full:  # duplicate reply for one id: drop it, do not block the reader
                            pass
        except Exception as exc:
            self.stderr_tail = (self.stderr_tail + f"[stdout reader] {exc}\n")[-4000:]
        finally:
            with self.pending_lock:
                waiters = list(self.responses.values())
            for waiter in waiters:
                try:
                    waiter.put_nowait({"_reader_closed": True})
                except queue.Full:
                    pass

    def _drain_stderr(self, proc):
        try:
            for line in proc.stderr:
                self.stderr_tail = (self.stderr_tail + line)[-4000:]
        except Exception:
            pass

    def _request(self, method, params=None, timeout=8):
        proc = self.proc
        if not proc or proc.poll() is not None:
            raise RuntimeError("MCP process is not running")
        request_id = uuid.uuid4().hex
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        waiter = queue.Queue(maxsize=1)
        with self.pending_lock:
            self.responses[request_id] = waiter
        try:
            proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            proc.stdin.flush()
            try:
                response = waiter.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"MCP {method} timed out after {timeout}s")
            if response.get("_reader_closed"):
                raise RuntimeError("MCP process closed stdout before replying")
            if "error" in response:
                error = response["error"]
                if isinstance(error, dict):
                    code = error.get("code")
                    text = str(error.get("message") or "MCP JSON-RPC error")
                    raise RuntimeError(f"{text} (code {code})" if code is not None else text)
                raise RuntimeError(str(error) or "MCP JSON-RPC error")
            result = response.get("result", {})
            return result if isinstance(result, dict) else {}
        finally:
            with self.pending_lock:
                self.responses.pop(request_id, None)

    def _notify(self, method, params=None):
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError("MCP process is not running")
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def _start(self):
        cmd = self.spec["command"]
        self.proc = subprocess.Popen(
            cmd, cwd=self.spec.get("cwd"), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, **self.spec.get("env", {})}, text=True,
            encoding="utf-8", errors="replace", bufsize=1, shell=False,
        )
        proc = self.proc
        self.started_at = time.time()
        self.reader_thread = threading.Thread(target=self._read_stdout, args=(proc,), daemon=True)
        self.stderr_thread = threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True)
        self.reader_thread.start()
        self.stderr_thread.start()

    def _list_tools(self, timeout, max_pages=20):
        """Read every page of tools/list (the spec pages with nextCursor) into normalized dicts."""
        tools, cursor = [], None
        for _page in range(max_pages):
            listed = self._request("tools/list", {"cursor": cursor} if cursor else {}, timeout=timeout)
            for t in listed.get("tools", []) if isinstance(listed.get("tools", []), list) else []:
                if not isinstance(t, dict) or not str(t.get("name") or "").strip():
                    continue
                schema = t.get("inputSchema")
                tools.append({"name": str(t["name"]), "description": str(t.get("description") or ""),
                              "inputSchema": schema if isinstance(schema, dict) else {"type": "object", "properties": {}}})
            cursor = listed.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        return tools

    def connect_and_check(self):
        started = time.monotonic()
        with self.lock:
            try:
                if not self.proc or self.proc.poll() is not None:
                    self._start()
                # MCP servers may need time to initialize (for example, when
                # importing a tool runtime). Keep the timeout bounded and
                # configurable per server rather than hard-coding a short limit.
                handshake_timeout = max(
                    1, min(60, float(self.spec.get("handshake_timeout", 20)))
                )
                if self.state == "online" and self.proc and self.proc.poll() is None:
                    # Already initialized. Sending "initialize" twice is a protocol violation and some
                    # servers answer with an error, which used to make this check kill a healthy server.
                    self.tools = self._list_tools(handshake_timeout)
                else:
                    self._request("initialize", {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "atlas-chat", "version": "1.1"},
                    }, timeout=handshake_timeout)
                    self._notify("notifications/initialized")
                    self.tools = self._list_tools(handshake_timeout)
                self.state, self.error = "online", None
            except Exception as exc:
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                # A failed initialize/list handshake must not leave an owned
                # child alive. stop() closes only this connection's Popen.
                self.stop()
                self.state = "error"
            self.last_check = time.time()
            self.latency_ms = round((time.monotonic() - started) * 1000, 1)
            return self.snapshot()

    def call_tool(self, name, arguments=None, timeout=30):
        with self.lock:
            if self.state != "online" or not self.proc or self.proc.poll() is not None:
                raise RuntimeError(f"MCP server '{self.spec.get('name')}' is not online; refresh status first")
            advertised = next((t for t in self.tools if t["name"] == name), None)
            if advertised is None:
                raise ValueError(f"Tool '{name}' is not in the server's live tools/list response")
            started_ns = time.perf_counter_ns()
            try:
                result = self._request("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)
                is_error = bool(result.get("isError"))
                proof = result.get("structuredContent")
                explicit_verification = (
                    isinstance(proof, dict) and isinstance(proof.get("verified"), bool)
                )
                verified = bool(explicit_verification and proof.get("verified") is True and not is_error)
                verification = (
                    "not_performed" if is_error
                    else ("passed" if verified
                          else ("failed" if explicit_verification and proof.get("verified") is False
                                else "not_performed"))
                )
                evidence = {
                    "server": self.spec.get("name"), "tool": name,
                    "status": "FAILED" if is_error else ("VERIFIED" if verified else "EXECUTED_UNVERIFIED"),
                    "verification": verification,
                    "duration_ms": round((time.perf_counter_ns() - started_ns) / 1_000_000, 3),
                    "result": result,
                    "timestamp": time.time(),
                }
                self.last_execution = evidence
                return evidence
            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                evidence = {
                    "server": self.spec.get("name"), "tool": name,
                    "status": "FAILED", "verification": "not_performed",
                    "duration_ms": round((time.perf_counter_ns() - started_ns) / 1_000_000, 3),
                    "error": error_text,
                    "result": {"content": [{"type": "text", "text": error_text}], "isError": True},
                    "timestamp": time.time(),
                }
                self.last_execution = evidence
                return evidence

    def snapshot(self):
        running = bool(self.proc and self.proc.poll() is None)
        return {
            "name": self.spec.get("name"),
            "state": self.state if running else ("error" if self.error else "stopped"),
            "process_running": running,
            "pid": self.proc.pid if running else None,
            "tools": list(self.tools), "tool_count": len(self.tools),
            "latency_ms": self.latency_ms, "last_check": self.last_check,
            "started_at": self.started_at, "error": self.error,
            "stderr_tail": self.stderr_tail[-1000:],
            "last_execution": self.last_execution,
        }

    def stop(self):
        """Stop only this connection's child, without racing its pipe readers."""
        with self.lock:
            proc = self.proc
            if proc is None:
                self.state = "stopped"
                return

            # Closing stdin first gives a cooperative stdio server a chance to
            # observe EOF and exit. Do not close stdout/stderr while their
            # reader threads are using TextIOWrapper.readline().
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except (OSError, ValueError):
                pass

            if proc.poll() is None:
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            proc.kill()
                        except OSError:
                            pass
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            # Keep the handle and reader state intact if the OS
                            # has not confirmed process termination.
                            self.state = "error"
                            self.error = "MCP child did not exit after kill"
                            return

            # Process exit closes its pipe writers, allowing both reader loops
            # to receive EOF. Join them before closing their TextIOWrapper.
            current = threading.current_thread()
            for thread in (self.reader_thread, self.stderr_thread):
                if thread and thread is not current:
                    thread.join(timeout=1.0)

            for thread, stream in (
                (self.reader_thread, proc.stdout),
                (self.stderr_thread, proc.stderr),
            ):
                if thread is None or not thread.is_alive():
                    try:
                        if stream and not stream.closed:
                            stream.close()
                    except (OSError, ValueError):
                        pass

            self.proc = None
            self.reader_thread = None
            self.stderr_thread = None
            self.state = "stopped"


class MCPMonitor:
    def __init__(self, specs):
        self.connections = {s["name"]: MCPConnection(s) for s in specs}

    def check_all(self):
        rows = [c.connect_and_check() for c in self.connections.values()]
        return {"checked_at": time.time(), "configured": len(rows),
                "online": sum(r["state"] == "online" and r["process_running"] for r in rows),
                "servers": rows}

    def ensure_online(self, min_interval=30.0):
        """Start or repair servers that are not online, but at most once per `min_interval` seconds
        for each one. A server that cannot start must not make every chat request wait for it."""
        now = time.time()
        for connection in self.connections.values():
            snap = connection.snapshot()
            if snap["state"] == "online" and snap["process_running"]:
                continue
            if snap["last_check"] is not None and now - snap["last_check"] < min_interval:
                continue
            connection.connect_and_check()
        return self.status()

    def status(self):
        rows = [c.snapshot() for c in self.connections.values()]
        return {"checked_at": time.time(), "configured": len(rows),
                "online": sum(r["state"] == "online" and r["process_running"] for r in rows),
                "servers": rows}

    def call_tool(self, server_name, tool_name, arguments=None, timeout=30):
        connection = self.connections.get(server_name)
        if connection is None:
            raise KeyError(f"Unknown MCP server: {server_name}")
        return connection.call_tool(tool_name, arguments, timeout)

    def stop_all(self):
        for connection in self.connections.values():
            connection.stop()
