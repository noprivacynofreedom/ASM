"""Reverse proxy in front of llama-swap that fills the hardware fields llama-swap leaves empty on Windows
(device, GPU architecture, environment, NVIDIA power limit). Everything else passes through unchanged.
The Operations > llama-swap tab loads http://127.0.0.1:8091/ui/ instead of :8080. Standard library only.
ponytail: no websocket upgrade (llama-swap's Realtime playground tab only); SSE and normal requests stream fine.
"""
import http.client, json, re, subprocess, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PROXY_PORT = 8091
_cache = {}

def _ps(cmd):
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             timeout=15, creationflags=0x08000000).stdout
        return json.loads(out) if out.strip() else None
    except Exception:
        return None

def _one(x):
    return x[0] if isinstance(x, list) and x else (x if isinstance(x, dict) else {})

NV_ARCH = [("12.", "Blackwell"), ("10.", "Blackwell"), ("9.", "Hopper"), ("8.9", "Ada Lovelace"), ("8.", "Ampere"),
           ("7.5", "Turing"), ("7.", "Volta"), ("6.", "Pascal"), ("5.", "Maxwell"), ("3.", "Kepler")]

def amd_arch(model, cpu):
    m = re.search(r"\b(?:RX|PRO W|Radeon PRO W)\s*(\d)(\d{3})", model or "")
    if m:
        gen, n = m.group(1), m.group(2)
        if gen == "9": return "RDNA 4"
        if gen == "7": return "RDNA 3"
        if gen == "6": return "RDNA 2"
        if gen == "5": return "RDNA 1"
    if re.search(r"Vega|Radeon VII", model or ""): return "GCN 5 (Vega)"
    if re.search(r"Radeon\W*(TM)?\W*Graphics", model or ""):  # integrated GPU: take the generation from the Ryzen model
        c = re.search(r"Ryzen \d+ (\d)\d{3}", cpu or "")
        if c: return {"7": "RDNA 2", "8": "RDNA 3", "9": "RDNA 3.5"}.get(c.group(1))
    return None

def nvidia():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,compute_cap,power.limit", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8, creationflags=0x08000000).stdout
    except Exception:
        return []
    rows = []
    for line in out.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 4:
            arch = next((n for pre, n in NV_ARCH if p[2].startswith(pre)), None)
            try: watts = float(p[3])
            except ValueError: watts = None
            rows.append({"name": p[1], "arch": arch, "watts": watts})
    return rows

def probe():
    if _cache: return _cache
    cs = _one(_ps("Get-CimInstance Win32_ComputerSystem | Select Manufacturer,Model,SystemFamily | ConvertTo-Json"))
    bb = _one(_ps("Get-CimInstance Win32_BaseBoard | Select Manufacturer,Product | ConvertTo-Json"))
    generic = re.compile(r"system (product )?name|to be filled|default string|^$", re.I)
    vendor, model = cs.get("Manufacturer"), cs.get("Model")
    if not model or generic.search(model):  # home-built PC: use the motherboard
        vendor, model = bb.get("Manufacturer") or vendor, bb.get("Product")
    virt = bool(re.search(r"virtual|vmware|kvm|qemu|hyper-v", f"{cs.get('Manufacturer')} {cs.get('Model')}", re.I))
    _cache.update(system={"vendor": vendor, "model": model, "family": None if generic.search(cs.get("SystemFamily") or "") or re.search(r"default string", cs.get("SystemFamily") or "", re.I) else cs.get("SystemFamily")},
                  env={"kind": "virtual_machine" if virt else "native", "name": "Virtual machine" if virt else "Windows"},
                  nv=nvidia())
    return _cache

def patch(raw):
    hw = json.loads(raw)
    info = probe()
    sysd = hw.get("system") or {}
    for k, v in info["system"].items():
        if not sysd.get(k) and v: sysd[k] = v
    hw["system"] = sysd
    env = hw.get("environment") or {}
    if env.get("kind") in (None, "unknown"): env.update(info["env"])
    hw["environment"] = env
    cpu = (hw.get("cpu") or {}).get("model") or ""
    nv = list(info["nv"])
    for acc in hw.get("accelerators") or []:
        model = acc.get("model") or ""
        if (acc.get("vendor") or "").upper().startswith("NVIDIA") or "NVIDIA" in model.upper():
            hit = next((n for n in nv if n["name"] in model or model in n["name"]), None)
            if hit:
                if not acc.get("architecture"): acc["architecture"] = hit["arch"]
                if acc.get("power_limit_watts") is None: acc["power_limit_watts"] = hit["watts"]
        elif not acc.get("architecture"):
            acc["architecture"] = amd_arch(model, cpu)
    return json.dumps(hw).encode()

def _handler(host, port):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def _go(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else None
            hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "accept-encoding")}
            try:
                c = http.client.HTTPConnection(host, port, timeout=900)
                c.request(self.command, self.path, body, hdrs)
                r = c.getresponse()
            except Exception as e:
                msg = json.dumps({"error": f"llama-swap not reachable: {e}"}).encode()
                self.send_response(502); self.send_header("Content-Length", str(len(msg))); self.end_headers(); self.wfile.write(msg); return
            if self.path.split("?")[0] == "/api/hardware" and r.status == 200:
                try:
                    data = patch(r.read())
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
                except Exception:
                    pass  # fall through: unpatched data is still better than an error
                c.close(); c = http.client.HTTPConnection(host, port, timeout=30); c.request("GET", self.path, None, hdrs); r = c.getresponse()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in ("transfer-encoding", "connection", "content-length"): self.send_header(k, v)
            self.send_header("Connection", "close"); self.end_headers()
            try:
                while True:
                    chunk = r.read1(8192) if hasattr(r, "read1") else r.read(8192)
                    if not chunk: break
                    self.wfile.write(chunk); self.wfile.flush()
            except Exception:
                pass
            self.close_connection = True
        do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = _go
    return H

def start(host, port, listen=PROXY_PORT):
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", listen), _handler(host, port))
    except OSError:
        return None  # port taken: the tab falls back to :8080 directly
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=probe, daemon=True).start()  # warm the cache so the Hardware page opens instantly
    return srv

if __name__ == "__main__":  # self-check
    sample = json.dumps({"system": {"vendor": None, "model": None, "family": None}, "environment": {"kind": "unknown"},
        "cpu": {"model": "AMD Ryzen 7 7800X3D"}, "accelerators": [
        {"vendor": "AMD", "model": "AMD Radeon RX 9070 XT", "architecture": None},
        {"vendor": "AMD", "model": "AMD Radeon(TM) Graphics", "architecture": None}]})
    out = json.loads(patch(sample.encode()))
    assert out["accelerators"][0]["architecture"] == "RDNA 4", out
    assert out["accelerators"][1]["architecture"] == "RDNA 2", out
    assert out["environment"]["kind"] in ("native", "virtual_machine"), out
    print("ok", out["system"], out["environment"])
