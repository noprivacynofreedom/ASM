"""Compute sharing on the home network: send a whole-model request to ONE other machine.

A "peer" is another PC that runs llama-swap (or llama-server) with an OpenAI-compatible
/v1 endpoint. A model alias listed under a peer goes to that peer. Every other alias
stays on this PC. One request goes to one machine. Models are never split.

settings.json:
  "compute_peers": [{"name": "Laptop", "url": "http://192.168.1.50:8080",
                     "models": ["laptop-7b"], "api_key": ""}],
  "compute_allow_public": false      (set true by hand to allow non-LAN addresses)

Only the model endpoint of a peer is used. The Atlas Chat API is never exposed.
Standard library only.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import tempfile
import threading
import time
from urllib.parse import urlparse

import upstream_auth

_HERE = os.path.dirname(os.path.abspath(__file__))
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$")
_WRITE_LOCK = threading.Lock()
MAX_PEERS = 8


def _data_dir():
    return os.environ.get("ATLAS_DATA_DIR") or _HERE


def _settings_path():
    return os.path.join(_data_dir(), "settings.json")


def _read_settings():
    try:
        with open(_settings_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def allow_public():
    return _read_settings().get("compute_allow_public") is True


# ---------------------------------------------------------------- validation

def _is_lan_address(ip):
    return ip.is_private or ip.is_loopback or ip.is_link_local


def check_host(host, public_ok=False):
    """Return "" when the host is allowed, else a plain reason. LAN addresses only by default."""
    if not host:
        return "The address has no host name."
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return f"Cannot find the address {host} on this network."
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0].split("%")[0]))
            except ValueError:
                continue
        if not addresses:
            return f"Cannot find the address {host} on this network."
    if public_ok:
        return ""
    if all(_is_lan_address(ip) for ip in addresses):
        return ""
    return (f"{host} is not a home-network address. Atlas only shares with machines on your LAN. "
            'To allow other addresses, set "compute_allow_public": true in settings.json.')


def parse_url(url, public_ok=None):
    """Return (host, port, error). Accepts http://host[:port] only."""
    if public_ok is None:
        public_ok = allow_public()
    text = str(url or "").strip()
    if not text:
        return None, None, "Enter the laptop address, for example http://192.168.1.50:8080"
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlparse(text)
        port = parts.port or 8080
    except ValueError:
        return None, None, "That address is not valid."
    if parts.scheme != "http":
        return None, None, "Use an http:// address on your home network."
    if parts.username or parts.password:
        return None, None, "Do not put a user name or password in the address."
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None, None, "Enter only the machine address and port, for example http://192.168.1.50:8080"
    reason = check_host(parts.hostname or "", public_ok)
    if reason:
        return None, None, reason
    return parts.hostname, port, ""


def _clean_models(value):
    out = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and 0 < len(item.strip()) <= 100 and item.strip() not in out:
                out.append(item.strip())
    return out[:64]


# ---------------------------------------------------------------- peer list

def load_peers():
    """Return (valid_peers, problems). A bad entry is skipped and reported, never trusted."""
    raw = _read_settings().get("compute_peers", [])
    public_ok = allow_public()
    peers, problems = [], []
    if not isinstance(raw, list):
        return [], ["compute_peers in settings.json must be a list."]
    for entry in raw[:MAX_PEERS]:
        if not isinstance(entry, dict):
            problems.append("A compute_peers entry is not an object.")
            continue
        name = str(entry.get("name") or "").strip()
        if not _NAME_RE.match(name):
            problems.append(f"Peer name {name!r} is not valid (letters, digits, space, - and _, up to 40).")
            continue
        host, port, error = parse_url(entry.get("url"), public_ok)
        if error:
            problems.append(f"{name}: {error}")
            continue
        key = entry.get("api_key")
        peers.append({"name": name, "url": f"http://{host}:{port}", "host": host, "port": port,
                      "models": _clean_models(entry.get("models")),
                      "api_key": key.strip() if isinstance(key, str) else ""})
    return peers, problems


def route(model):
    """Where should this model alias go? Returns (host, port, peer_or_None).

    The caller passes its own local host and port as the default."""
    if isinstance(model, str) and model:
        for peer in load_peers()[0]:
            if model in peer["models"]:
                return peer["host"], peer["port"], peer
    return None, None, None


def headers_for(host, port, base=None):
    """Request headers for an upstream. A peer never receives this PC's llama-swap key."""
    for peer in load_peers()[0]:
        if peer["host"] == host and peer["port"] == port:
            merged = dict(base or {})
            if peer["api_key"]:
                merged["Authorization"] = "Bearer " + peer["api_key"]
            return merged
    return upstream_auth.headers(base)


# ---------------------------------------------------------------- probing

def probe(host, port, api_key="", timeout=3.0):
    """Ask a peer for /v1/models. Returns online, latency_ms, models, error (plain text)."""
    started = time.monotonic()
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        conn.request("GET", "/v1/models", headers=headers)
        resp = conn.getresponse()
        raw = resp.read(1_000_000)
        latency = int((time.monotonic() - started) * 1000)
        if resp.status in (401, 403):
            return {"online": False, "latency_ms": latency, "models": [], "error": "The machine answered but refused the key."}
        if resp.status != 200:
            return {"online": False, "latency_ms": latency, "models": [], "error": f"The machine answered with HTTP {resp.status}."}
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
            models = [str(m.get("id")) for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        except (ValueError, AttributeError):
            return {"online": False, "latency_ms": latency, "models": [], "error": "The machine did not answer like a model server."}
        return {"online": True, "latency_ms": latency, "models": models, "error": ""}
    except (OSError, http.client.HTTPException) as exc:
        return {"online": False, "latency_ms": None, "models": [], "error": f"Cannot connect: {exc}"}
    finally:
        conn.close()


def _message(name, result):
    if result["online"]:
        count = len(result["models"])
        return f"{name} is online. It has {count} model{'s' if count != 1 else ''}."
    return f"{name} is offline. {result['error']}"


def peers_status():
    peers, problems = load_peers()
    rows = []
    for peer in peers:
        result = probe(peer["host"], peer["port"], peer["api_key"])
        rows.append({"name": peer["name"], "url": peer["url"], "routed_models": peer["models"],
                     "online": result["online"], "latency_ms": result["latency_ms"],
                     "models": result["models"], "message": _message(peer["name"], result)})
    return {"ok": True, "allow_public": allow_public(), "peers": rows, "problems": problems}


def test_url(url, name="Laptop", api_key=""):
    host, port, error = parse_url(url)
    if error:
        return {"ok": False, "online": False, "message": error, "models": [], "latency_ms": None}
    result = probe(host, port, api_key if isinstance(api_key, str) else "")
    return {"ok": True, "online": result["online"], "message": _message(name or "Laptop", result),
            "models": result["models"], "latency_ms": result["latency_ms"], "url": f"http://{host}:{port}"}


# ---------------------------------------------------------------- saving

def _write_settings(data):
    folder = _data_dir()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, _settings_path())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_peer(name, url, models=None, api_key=None):
    """Add or update one peer. With no models given, the models the peer reports are used."""
    name = str(name or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError("Give the machine a short name, for example Laptop.")
    host, port, error = parse_url(url)
    if error:
        raise ValueError(error)
    with _WRITE_LOCK:
        data = _read_settings()
        peers = data.get("compute_peers")
        peers = [p for p in peers if isinstance(p, dict)] if isinstance(peers, list) else []
        existing = next((p for p in peers if p.get("name") == name), None)
        key = api_key if isinstance(api_key, str) else (existing or {}).get("api_key", "")
        chosen = _clean_models(models)
        if not chosen:
            chosen = _clean_models((existing or {}).get("models")) or probe(host, port, key)["models"]
        entry = {"name": name, "url": f"http://{host}:{port}", "models": chosen}
        if key:
            entry["api_key"] = key
        if existing is not None:
            peers[peers.index(existing)] = entry
        elif len(peers) >= MAX_PEERS:
            raise ValueError(f"At most {MAX_PEERS} machines can be saved.")
        else:
            peers.append(entry)
        data["compute_peers"] = peers
        _write_settings(data)
    return {"ok": True, "name": name, "url": entry["url"], "models": chosen}


def remove_peer(name):
    with _WRITE_LOCK:
        data = _read_settings()
        peers = data.get("compute_peers")
        peers = [p for p in peers if isinstance(p, dict)] if isinstance(peers, list) else []
        kept = [p for p in peers if p.get("name") != name]
        removed = len(kept) != len(peers)
        data["compute_peers"] = kept
        _write_settings(data)
    return {"ok": True, "removed": removed}


def unload_all(timeout=5.0):
    """Ask every peer to unload its models (used by /swarm stop). Returns how many answered."""
    done = 0
    for peer in load_peers()[0]:
        conn = http.client.HTTPConnection(peer["host"], peer["port"], timeout=timeout)
        try:
            headers = {"Authorization": "Bearer " + peer["api_key"]} if peer["api_key"] else {}
            conn.request("GET", "/unload", headers=headers)
            if conn.getresponse().status < 300:
                done += 1
        except (OSError, http.client.HTTPException):
            pass
        finally:
            conn.close()
    return done
