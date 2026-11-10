"""Atlas Chat Windows launcher. Owns and cleans up only services it starts."""
from __future__ import annotations
import os, socket, subprocess, sys, threading, time
from pathlib import Path
import webview

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", str(HERE)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HERE))
import server

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
owned_swap = None
owned_server = None
server_thread = None
cleanup_lock = threading.Lock()
cleaned = False

def port_up(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, int(port)), timeout=.4): return True
    except OSError: return False

def wait_port(port, timeout, process=None):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if port_up(port): return True
        if process is not None and process.poll() is not None: return False
        time.sleep(.25)
    return port_up(port)

def start_services():
    global owned_swap, owned_server, server_thread
    if not port_up(server.UPSTREAM_PORT):
        exe=server.SETTINGS["llama_swap_exe"]; cfg=server.SETTINGS["llama_swap_config"]
        if not exe or not cfg: raise FileNotFoundError("llama-swap is not set up: set llama_swap_exe and llama_swap_config in settings.local.json, or start llama-swap yourself on port %s" % server.UPSTREAM_PORT)
        if not os.path.isfile(exe): raise FileNotFoundError(f"llama-swap executable not found: {exe}")
        if not os.path.isfile(cfg): raise FileNotFoundError(f"llama-swap config not found: {cfg}")
        logs=DATA_DIR/"logs"; logs.mkdir(exist_ok=True)
        log=open(logs/"llama-swap.log","a",encoding="utf-8")
        owned_swap=subprocess.Popen([exe,"--config",cfg,"--listen",f"127.0.0.1:{server.UPSTREAM_PORT}"],
            cwd=os.path.dirname(exe),stdout=log,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
        # Keep the log handle alive for the child.
        owned_swap._atlas_log_handle=log
        if not wait_port(server.UPSTREAM_PORT,45,owned_swap):
            raise RuntimeError(f"llama-swap failed to become ready on port {server.UPSTREAM_PORT}; see logs/llama-swap.log")
    if not port_up(server.PORT):
        owned_server=server.create_server()
        server_thread=threading.Thread(target=owned_server.serve_forever,name="atlas-http-server",daemon=True)
        server_thread.start()
        if not wait_port(server.PORT,10):
            raise RuntimeError(f"Atlas server failed to start on port {server.PORT}")
    else:
        # Do not silently attach to an unrelated/stale server. Verify its health endpoint.
        import urllib.request, json
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.PORT}/api/health",timeout=2) as r:
                health=json.loads(r.read().decode())
            if health.get("upstream_port") != server.UPSTREAM_PORT:
                raise RuntimeError(f"Port {server.PORT} is occupied by an Atlas server configured for upstream port {health.get('upstream_port')}, expected {server.UPSTREAM_PORT}. Close that specific old Atlas instance and relaunch.")
        except RuntimeError: raise
        except Exception as e:
            raise RuntimeError(f"Port {server.PORT} is already occupied by a service that did not identify as this Atlas instance: {e}")

def stop_owned():
    global cleaned, owned_swap, owned_server
    with cleanup_lock:
        if cleaned: return
        cleaned=True
    if owned_server is not None:
        try: owned_server.shutdown()
        except Exception: pass
        try: owned_server.server_close()
        except Exception: pass
        owned_server=None
    if owned_swap is not None:
        p=owned_swap
        if p.poll() is None:
            try: p.terminate(); p.wait(timeout=6)
            except subprocess.TimeoutExpired:
                # Windows: terminate this exact owned process tree only.
                try: subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True,timeout=8)
                except Exception: pass
            except Exception: pass
        try:
            if getattr(p,"_atlas_log_handle",None): p._atlas_log_handle.close()
        except Exception: pass
        owned_swap=None

def main():
    start_services()
    win=webview.create_window("Atlas Chat",f"http://127.0.0.1:{server.PORT}",width=1380,height=900,
        min_size=(760,560),background_color="#17131f")
    win.events.closed += stop_owned
    try: webview.start(private_mode=False,storage_path=str(DATA_DIR/".webview"))
    finally: stop_owned()

if __name__=="__main__":
    try: main()
    except Exception as exc:
        (DATA_DIR/"logs").mkdir(exist_ok=True)
        with open(DATA_DIR/"logs"/"startup-error.log","a",encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {type(exc).__name__}: {exc}\n")
        raise
