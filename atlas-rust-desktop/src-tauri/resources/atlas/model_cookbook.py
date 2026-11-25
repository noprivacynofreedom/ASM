"""Hardware-aware Model Cookbook for Atlas Chat (Phase 1C).

Inspects local GPU VRAM, system RAM, already-discovered ``.gguf`` models (via
``model_discovery``), and configured LAN compute peers (via ``compute_peers``)
to recommend quantized models mapped directly to Atlas role aliases
(``coder``, ``mentor``, ``assist``, ``tasks``, ``vision``).

Standard library only. Never emits personal filesystem paths in commands or
catalog entries (uses the ``{models}`` placeholder resolved at runtime).
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import Any, Callable

import compute_peers
import model_discovery

COOKBOOK_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "qwen2.5-coder-7b-q4",
        "name": "Qwen 2.5 Coder 7B (Q4_K_M)",
        "alias": "coder",
        "min_vram_gb": 6.0,
        "min_ram_gb": 12.0,
        "size_gb": 4.7,
        "quant": "Q4_K_M",
        "context": 32768,
        "ollama_tag": "qwen2.5-coder:7b",
        "hf_repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "gguf_file": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "notes": "Fast, accurate local coding model for 6–8 GB GPUs.",
    },
    {
        "id": "qwen3-coder-30b-a3b-q4",
        "name": "Qwen 3 Coder 30B-A3B MoE (Q4_K_M)",
        "alias": "coder",
        "min_vram_gb": 12.0,
        "min_ram_gb": 24.0,
        "size_gb": 18.5,
        "quant": "Q4_K_M",
        "context": 32768,
        "ollama_tag": "qwen3-coder:30b",
        "hf_repo": "Qwen/Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "gguf_file": "qwen3-coder-30b-a3b-instruct-q4_k_m.gguf",
        "notes": "Sparse MoE coding powerhouse; runs fast on 12–16 GB GPU with CPU expert offload.",
    },
    {
        "id": "gemma3-12b-q4",
        "name": "Gemma 3 12B Instruct (Q4_K_M)",
        "alias": "mentor",
        "min_vram_gb": 10.0,
        "min_ram_gb": 16.0,
        "size_gb": 7.4,
        "quant": "Q4_K_M",
        "context": 32768,
        "ollama_tag": "gemma3:12b",
        "hf_repo": "bartowski/google_gemma-3-12b-it-GGUF",
        "gguf_file": "google_gemma-3-12b-it-Q4_K_M.gguf",
        "notes": "Strong reasoning, writing, and architecture review for mid-range GPUs.",
    },
    {
        "id": "gemma3-27b-q4",
        "name": "Gemma 3 27B Instruct (Q4_K_M)",
        "alias": "mentor",
        "min_vram_gb": 20.0,
        "min_ram_gb": 32.0,
        "size_gb": 16.8,
        "quant": "Q4_K_M",
        "context": 32768,
        "ollama_tag": "gemma3:27b",
        "hf_repo": "bartowski/google_gemma-3-27b-it-GGUF",
        "gguf_file": "google_gemma-3-27b-it-Q4_K_M.gguf",
        "notes": "High-depth mentor & reviewer for 24 GB GPUs or 16 GB GPU + 32 GB RAM hybrid.",
    },
    {
        "id": "qwen3-14b-q4",
        "name": "Qwen 3 14B Instruct (Q4_K_M)",
        "alias": "assist",
        "min_vram_gb": 10.0,
        "min_ram_gb": 16.0,
        "size_gb": 9.0,
        "quant": "Q4_K_M",
        "context": 32768,
        "ollama_tag": "qwen3:14b",
        "hf_repo": "Qwen/Qwen3-14B-GGUF",
        "gguf_file": "qwen3-14b-q4_k_m.gguf",
        "notes": "Balanced everyday general assistant with strong tool-calling reliability.",
    },
    {
        "id": "llama3.2-3b-q8",
        "name": "Llama 3.2 3B Instruct (Q8_0)",
        "alias": "tasks",
        "min_vram_gb": 4.0,
        "min_ram_gb": 8.0,
        "size_gb": 3.4,
        "quant": "Q8_0",
        "context": 32768,
        "ollama_tag": "llama3.2:3b",
        "hf_repo": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "gguf_file": "Llama-3.2-3B-Instruct-Q8_0.gguf",
        "notes": "Ultra-fast lightweight model for summarization, titles, and background tasks.",
    },
    {
        "id": "qwen2.5-vl-7b-q4",
        "name": "Qwen 2.5 VL 7B (Vision, Q4_K_M)",
        "alias": "vision",
        "min_vram_gb": 8.0,
        "min_ram_gb": 16.0,
        "size_gb": 5.2,
        "quant": "Q4_K_M",
        "context": 16384,
        "ollama_tag": "qwen2.5vl:7b",
        "hf_repo": "bartowski/Qwen2.5-VL-7B-Instruct-GGUF",
        "gguf_file": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        "notes": "Multimodal vision model for screenshots, diagrams, and image inputs.",
    },
)


def _detect_ram_gb() -> float:
    if sys.platform == "win32":
        try:
            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_size > 0:
                return round((pages * page_size) / (1024 ** 3), 1)
    except Exception:
        pass
    return 16.0


def _detect_gpu() -> tuple[str, float]:
    try:
        run = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if run.returncode == 0 and run.stdout.strip():
            first = run.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            if len(parts) >= 2:
                return parts[0], round(float(parts[1]) / 1024.0, 1)
    except Exception:
        pass
    return "CPU / Unknown GPU", 0.0


def detect_hardware() -> dict[str, Any]:
    """Return local hardware profile ``{gpu_name, vram_gb, ram_gb, cpu_count}``."""
    gpu_name, vram_gb = _detect_gpu()
    return {
        "gpu_name": gpu_name,
        "vram_gb": vram_gb,
        "ram_gb": _detect_ram_gb(),
        "cpu_count": os.cpu_count() or 4,
    }


def evaluate_fit(
    recipe: dict[str, Any],
    hardware: dict[str, Any],
    peer_models: set[str] | None = None,
) -> tuple[str, str]:
    """Classify how well ``recipe`` fits the local hardware or LAN peers."""
    vram = float(hardware.get("vram_gb") or 0.0)
    ram = float(hardware.get("ram_gb") or 0.0)
    size = float(recipe.get("size_gb") or 0.0)
    min_vram = float(recipe.get("min_vram_gb") or 0.0)
    min_ram = float(recipe.get("min_ram_gb") or 0.0)

    if peer_models and (recipe["alias"] in peer_models or recipe["id"] in peer_models):
        return "lan_peer", "Available via LAN compute peer"
    if vram >= min_vram and (vram - 1.5) >= size:
        return "fits_vram", "Fits in GPU VRAM (fastest)"
    if (vram + ram * 0.65) >= (size + 2.0) and ram >= min_ram:
        return "hybrid_ram", "Fits via GPU + System RAM offload"
    return "too_large", f"Needs ~{min_vram:.0f} GB VRAM or {min_ram:.0f} GB RAM"


def recommendations(
    runtime_dir: str,
    data_dir: str,
    *,
    hardware: dict[str, Any] | None = None,
    installed_names: list[str] | None = None,
    peers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build hardware-aware Cookbook recommendations mapped to Atlas aliases."""
    hw = hardware or detect_hardware()

    if installed_names is None:
        try:
            dirs = model_discovery.search_dirs(runtime_dir, data_dir, [])
            found = model_discovery.find_models(dirs)
            installed_names = [p.name for p, _size in found]
        except Exception:
            installed_names = []
    installed_lower = [n.lower() for n in installed_names]

    if peers is None:
        try:
            peers = list(compute_peers.list_peers()) if hasattr(compute_peers, "list_peers") else []
        except Exception:
            peers = []
    peer_models: set[str] = set()
    for p in peers:
        for m in (p.get("models") or []):
            peer_models.add(str(m).strip().lower())

    items: list[dict[str, Any]] = []
    for recipe in COOKBOOK_CATALOG:
        fit_code, fit_label = evaluate_fit(recipe, hw, peer_models=peer_models)
        gguf = recipe["gguf_file"].lower()
        installed = any(gguf in name or recipe["id"].split("-")[0] in name and recipe["alias"] in name for name in installed_lower)
        items.append(
            {
                **recipe,
                "fit": fit_code,
                "fit_label": fit_label,
                "installed": installed,
                "ollama_cmd": f"ollama pull {recipe['ollama_tag']}",
                "hf_cmd": f"huggingface-cli download {recipe['hf_repo']} {recipe['gguf_file']} --local-dir {{models}}",
            }
        )

    fit_rank = {"fits_vram": 0, "lan_peer": 1, "hybrid_ram": 2, "too_large": 3}
    items.sort(key=lambda r: (fit_rank.get(r["fit"], 9), r["alias"], r["size_gb"]))
    return {
        "ok": True,
        "hardware": hw,
        "installed_count": len(installed_names),
        "peer_count": len(peers),
        "recipes": items,
    }
