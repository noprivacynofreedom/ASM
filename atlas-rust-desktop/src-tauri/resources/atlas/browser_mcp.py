"""Atlas browser MCP server (stdio, newline-delimited JSON-RPC) driving Playwright.

Run:  python browser_mcp.py        (needs: pip install playwright && playwright install chromium)

Tools: browser_open, browser_click, browser_type, browser_press, browser_screenshot,
       browser_get_text, browser_eval, browser_wait, browser_tabs, browser_close.

Env:
  ATLAS_BROWSER_MODE         'auto' (default) | 'sandbox' | 'host'
      sandbox: headless, throwaway temp profile (deleted on close), no host cookies.
      host:    headed (visible to the user), persistent profile under the Atlas data dir
               (ATLAS_DATA_DIR/browser_profile, else <this folder>/data/browser_profile).
      auto:    host if a display is available (Windows/macOS, or DISPLAY/WAYLAND_DISPLAY on
               Linux), otherwise sandbox.
  ATLAS_BROWSER_ALLOW_LOCAL  1 = allow file:// and localhost/private-network URLs. Default 0:
                             file:, chrome:, about: (except about:blank), localhost, loopback,
                             link-local and private IPs are blocked (checked on every request).
  ATLAS_BROWSER_CHANNEL      optional Playwright channel (e.g. 'chrome', 'msedge').
Approval tiers live in mcp_chat.TOOL_TIERS (get_text/screenshot/tabs/wait = read, rest = write).
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
MAX_TEXT = 20000
DEFAULT_TIMEOUT_MS = 15000


def log(msg):
    sys.stderr.write(f"[browser_mcp] {msg}\n")
    sys.stderr.flush()


def resolve_mode(env=None):
    env = os.environ if env is None else env
    mode = str(env.get("ATLAS_BROWSER_MODE", "auto") or "auto").strip().lower()
    if mode not in ("auto", "sandbox", "host"):
        log(f"unknown ATLAS_BROWSER_MODE {mode!r}, using auto")
        mode = "auto"
    if mode == "auto":
        if sys.platform in ("win32", "darwin") or env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
            return "host"
        return "sandbox"
    return mode


def allow_local(env=None):
    env = os.environ if env is None else env
    return str(env.get("ATLAS_BROWSER_ALLOW_LOCAL", "")).strip() in ("1", "true", "yes")


def url_blocked(url, local_ok=False):
    """Return a reason string if the URL must not be loaded, else ''."""
    try:
        p = urlparse(str(url))
    except ValueError:
        return "invalid URL"
    scheme = (p.scheme or "").lower()
    if scheme in ("http", "https"):
        if local_ok:
            return ""
        host = (p.hostname or "").lower().rstrip(".")
        if not host:
            return "missing host"
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
            return "localhost URLs are blocked (set ATLAS_BROWSER_ALLOW_LOCAL=1)"
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            # Decimal/hex/octal/short forms (127.1, 0177.0.0.1) are normalised by browsers.
            # Known limit: hostnames that DNS-resolve to private IPs are not checked.
            if re.fullmatch(r"[0-9a-fx.]+", host) and re.search(r"\d", host):
                return "numeric host blocked"
            return ""
        if re.search(r"(^|\.)0\d", host):
            return "numeric host blocked"
        if getattr(ip, "ipv4_mapped", None) and (ip.ipv4_mapped.is_loopback or ip.ipv4_mapped.is_private):
            return "local/private network address blocked"
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved:
            return "local/private network address blocked (set ATLAS_BROWSER_ALLOW_LOCAL=1)"
        return ""
    if scheme in ("data", "blob") or url == "about:blank":
        return ""
    if local_ok and scheme == "file":
        return ""
    return f"scheme {scheme or '(none)'!r} is blocked"


class Browser:
    def __init__(self):
        self.mode = resolve_mode()
        self.local_ok = allow_local()
        self.pw = None
        self.ctx = None
        self.page = None
        self.tmp = None

    # ---- lifecycle ----
    def _guard(self, route):
        reason = url_blocked(route.request.url, self.local_ok)
        if reason:
            log(f"blocked {route.request.url}: {reason}")
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def ensure(self):
        if self.ctx is not None:
            if not self.ctx.pages:
                self.page = self.ctx.new_page()
            elif self.page is None or self.page.is_closed():
                self.page = self.ctx.pages[-1]
            return self.page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed: pip install playwright && playwright install chromium") from exc
        self.pw = sync_playwright().start()
        kwargs = {"accept_downloads": False, "viewport": {"width": 1280, "height": 800}}
        channel = os.environ.get("ATLAS_BROWSER_CHANNEL", "").strip()
        if channel:
            kwargs["channel"] = channel
        if self.mode == "host":
            data = Path(os.environ.get("ATLAS_DATA_DIR") or (HERE / "data"))
            profile = data / "browser_profile"
            profile.mkdir(parents=True, exist_ok=True)
            self.ctx = self.pw.chromium.launch_persistent_context(str(profile), headless=False, **kwargs)
        else:
            self.tmp = tempfile.mkdtemp(prefix="atlas_browser_")
            kwargs["service_workers"] = "block"
            self.ctx = self.pw.chromium.launch_persistent_context(self.tmp, headless=True, **kwargs)
        self.ctx.set_default_timeout(DEFAULT_TIMEOUT_MS)
        self.ctx.route("**/*", self._guard)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self.page

    def close(self):
        for fn in (lambda: self.ctx and self.ctx.close(), lambda: self.pw and self.pw.stop()):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                log(f"close: {exc}")
        self.ctx = self.pw = self.page = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None

    # ---- tools ----
    def _target(self, page, a):
        if a.get("selector"):
            return page.locator(str(a["selector"])).first
        if a.get("text"):
            return page.get_by_text(str(a["text"])).first
        raise ValueError("selector or text is required")

    def browser_open(self, a):
        url = str(a.get("url") or "").strip()
        if "://" not in url and not url.startswith(("about:", "data:")):
            url = "https://" + url
        reason = url_blocked(url, self.local_ok)
        if reason:
            raise ValueError(f"URL blocked: {reason}")
        page = self.ensure()
        page.goto(url, wait_until="domcontentloaded")
        return f"Opened {page.url} (title: {page.title()!r}, mode: {self.mode})"

    def browser_click(self, a):
        page = self.ensure()
        self._target(page, a).click()
        return f"Clicked. Now at {page.url}"

    def browser_type(self, a):
        page = self.ensure()
        el = page.locator(str(a.get("selector") or "")).first
        el.fill(str(a.get("text", "")))
        return "Typed."

    def browser_press(self, a):
        page = self.ensure()
        page.keyboard.press(str(a.get("key") or "Enter"))
        return f"Pressed {a.get('key')}."

    def browser_screenshot(self, a):
        page = self.ensure()
        data = page.screenshot(full_page=bool(a.get("full_page")))
        return [{"type": "image", "data": base64.b64encode(data).decode(), "mimeType": "image/png"}]

    def browser_get_text(self, a):
        page = self.ensure()
        sel = a.get("selector")
        text = page.locator(str(sel)).first.inner_text() if sel else page.inner_text("body")
        return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n...[truncated]"

    def browser_eval(self, a):
        page = self.ensure()
        out = page.evaluate(str(a.get("js") or ""))
        text = json.dumps(out, default=str, ensure_ascii=False)
        return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "...[truncated]"

    def browser_wait(self, a):
        page = self.ensure()
        if a.get("selector"):
            page.wait_for_selector(str(a["selector"]), timeout=int(a.get("timeout_ms") or DEFAULT_TIMEOUT_MS))
            return "Selector found."
        ms = max(0, min(int(a.get("ms") or 1000), 30000))
        page.wait_for_timeout(ms)
        return f"Waited {ms} ms."

    def browser_tabs(self, a):
        self.ensure()
        rows = []
        for i, p in enumerate(self.ctx.pages):
            mark = "*" if p == self.page else " "
            rows.append(f"{mark}{i}: {p.url} - {p.title()}")
        return "\n".join(rows)

    def browser_close(self, a):
        self.close()
        return "Browser closed."


def _s(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


_STR = {"type": "string"}
TOOLS = [
    ("browser_open", "Open a URL in the browser.", _s({"url": _STR}, ["url"])),
    ("browser_click", "Click an element by CSS selector or visible text.", _s({"selector": _STR, "text": _STR})),
    ("browser_type", "Type text into an input (selector).", _s({"selector": _STR, "text": _STR}, ["selector", "text"])),
    ("browser_press", "Press a key, e.g. Enter, Tab, Control+A.", _s({"key": _STR}, ["key"])),
    ("browser_screenshot", "Screenshot the current page (PNG).", _s({"full_page": {"type": "boolean"}})),
    ("browser_get_text", "Get visible text of an element (selector) or the whole page.", _s({"selector": _STR})),
    ("browser_eval", "Evaluate a JavaScript expression in the page and return the JSON result.", _s({"js": _STR}, ["js"])),
    ("browser_wait", "Wait for a selector or a number of milliseconds.", _s({"selector": _STR, "ms": {"type": "integer"}})),
    ("browser_tabs", "List open tabs.", _s()),
    ("browser_close", "Close the browser and discard sandbox state.", _s()),
]


def handle(browser, msg):
    """Return a response dict, or None for notifications."""
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or "2024-11-05",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "atlas-browser", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        fn = getattr(browser, name, None) if name in {t[0] for t in TOOLS} else None
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        try:
            out = fn(args)
            content = out if isinstance(out, list) else [{"type": "text", "text": str(out)}]
            result = {"content": content}
        except Exception as exc:  # noqa: BLE001
            result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main():
    browser = Browser()
    log(f"mode={browser.mode} allow_local={browser.local_ok}")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            resp = handle(browser, msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
                sys.stdout.flush()
    finally:
        browser.close()


if __name__ == "__main__":
    main()
