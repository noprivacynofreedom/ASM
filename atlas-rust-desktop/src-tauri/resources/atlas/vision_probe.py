"""Ask a running llama-server whether it can read images.

llama-server reports {"modalities": {"vision": true}} on /props when it was started with a vision
projector (--mmproj). llama-swap forwards /upstream/<model>/props to that model and starts it if needed.
"""
import http.client
import json
from urllib.parse import quote


def parse_vision(props):
    """True / False from a /props answer, None when the server does not say (old build)."""
    if not isinstance(props, dict):
        return None
    modalities = props.get("modalities")
    if isinstance(modalities, dict) and "vision" in modalities:
        return bool(modalities["vision"])
    return None


def probe_vision(host, port, model, timeout=300):
    """Returns True, False or None (unknown: server unreachable, model failed to start, old build)."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", "/upstream/" + quote(str(model), safe="") + "/props")
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        if resp.status != 200:
            return None
        return parse_vision(json.loads(data.decode("utf-8", "replace")))
    except (OSError, http.client.HTTPException, ValueError):
        return None
