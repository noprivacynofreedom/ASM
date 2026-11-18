"""Import this FIRST in any test that touches swarm_run or cloud_llm.

A developer PC can have real GEMINI_API_KEY / OPENROUTER_API_KEY in its environment. Without this, the swarm tests
send real cloud calls, take longer than their 5-second waits, and fail only on such a PC (2026-11-18).
Tests that need a key set their own fake one.
"""
import os
import urllib.request

_KEY_NAMES = (
    "GEMINI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
    "MISTRAL_API_KEY", "GITHUB_TOKEN", "GH_MODELS_KEY", "XAI_API_KEY", "GROK_API_KEY",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
)
for _k in list(os.environ):
    if _k in _KEY_NAMES or _k.startswith(("ATLAS_CLOUD", "ATLAS_GEMINI", "ATLAS_REVIEW_LOCAL")):
        del os.environ[_k]

# The PC also has a system proxy (127.0.0.1:7897, env AND registry). Through it, a fake host answers
# "HTTP 502" instead of "host not found". Tests that want a proxy set ATLAS_CLOUD_PROXY themselves.
urllib.request.getproxies = lambda: {}
