"""Run from F:\\APP-DEV\\projects\\atlas-chat to test the REAL local model."""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config
import llm

def main():
    host=config.SETTINGS.get("upstream_host","127.0.0.1")
    port=config.SETTINGS.get("upstream_port",8080)
    model=config.SETTINGS.get("llm_model","coder")
    print("ATLAS CHAT LOCAL MODEL TEST")
    print(f"Project:  {HERE}")
    print(f"Endpoint: http://{host}:{port}")
    print(f"Model:    {model}")
    print()

    print("[1/3] Checking llama-swap /v1/models ...")
    try:
        models=llm.list_models()
    except Exception as exc:
        print("FAIL: model gateway is unreachable.")
        print(f"       {exc}")
        print("\nCheck that llama-swap is listening on the configured port.")
        return 2

    ids=[str(m.get("id","")) for m in models if isinstance(m,dict)]
    print(f"PASS: endpoint returned {len(ids)} model(s):")
    for mid in ids: print(f"  - {mid}")
    if ids and model not in ids:
        print(f"WARNING: configured model '{model}' is not an exact listed ID.")
        print("         The completion request below will still test the alias.")

    print("\n[2/3] Sending a tiny real chat-completion request ...")
    start=time.perf_counter()
    try:
        reply=llm.call_llm(
            "Reply with exactly: ATLAS_LOCAL_MODEL_OK",
            temperature=0,
            max_tokens=40,
            timeout=120,
        )
    except Exception as exc:
        print("FAIL: completion request failed.")
        print(f"       {exc}")
        return 3
    elapsed=time.perf_counter()-start
    print(f"PASS: model replied in {elapsed:.2f}s")
    print("Reply:", reply[:500].replace("\n"," "))

    print("\n[3/3] Testing the structured-output path used by agents.py ...")
    schema={
        "type":"object",
        "properties":{
            "thought":{"type":"string"},
            "tool":{"type":"string","enum":["finish"]},
            "args":{"type":"object","additionalProperties":False}
        },
        "required":["thought","tool","args"],
        "additionalProperties":False
    }
    try:
        raw=llm.call_llm(
            'Return one action only. The task is complete. Use tool "finish".',
            temperature=0,
            max_tokens=100,
            json_schema=schema,
            timeout=120,
        )
        parsed=json.loads(raw)
        if parsed.get("tool")!="finish" or not isinstance(parsed.get("args"),dict):
            raise ValueError("JSON response did not match the expected agent action")
    except Exception as exc:
        print("FAIL: agent structured-output request failed.")
        print(f"       {type(exc).__name__}: {exc}")
        print("The basic model request passed, but agent tool-planning format is not verified.")
        return 4
    print("PASS: valid agent action JSON returned:")
    print(json.dumps(parsed,indent=2))
    print("\nALL TESTS PASSED — local model and agents.py request format are responding.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
