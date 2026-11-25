"""Find .gguf model files and choose the llama-swap config to use. Standard library only.

Run by the Rust supervisor before llama-swap starts:
  python model_discovery.py --runtime <resources\\atlas> --data <data folder> [--models <folder> ...]
It prints one JSON line: {"config": <path>, "mode": "bundled"|"generated"|"none", "models": [...]}.
Rule: if the bundled config.yaml points only at files that exist, use it (nothing changes).
Otherwise write <data>/llama-swap.generated.yaml from the models found.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROLES = ("coder", "mentor", "assist", "tasks")
# Names the Models screen lets the user map to a .gguf file.
ALIASES = ("coder", "mentor", "tasks", "assist", "reviewer", "vision")
# Words in a file name that suggest a role. First match wins. Other files fill the rest by size.
HINTS = {
    "coder": ("coder", "code", "devstral", "qwen3.6", "qwen3-coder"),
    "mentor": ("gemma", "mistral", "llama", "mentor"),
    "assist": ("qwen3-14b", "qwen3", "phi", "assist"),
    "tasks": ("gpt-oss", "granite", "smol", "tasks"),
}
SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
MODEL_ARG = re.compile(r"(?:^|\s)(?:-m|--mmproj)\s+(\"[^\"]+\"|\S+)")
TEMPLATE_ARG = re.compile(r"((?:-m|--mmproj)\s+)(\S*\{models\}\S*)")
_MODEL_KEY_RE = re.compile(r'^  (["\']?[A-Za-z0-9._-]+["\']?)\s*:\s*(?:#.*)?$')


def search_dirs(runtime, data, extra):
    runtime, data = Path(runtime), Path(data)
    dirs = [Path(p) for p in extra if p]
    env = os.environ.get("ATLAS_MODELS_DIR")
    if env:
        dirs.append(Path(env))
    # next to the install, inside the install, and in the data folder
    dirs += [data / "models", runtime / "models", runtime / "runtime" / "models", runtime.parent / "models", runtime.parent.parent / "models"]
    # a "models" folder at the root of the drive the app or its data is on (for example X:\models)
    for anchor in (data.anchor, runtime.anchor):
        if anchor:
            dirs.append(Path(anchor) / "models")
    seen, out = set(), []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_models(dirs, max_depth=3):
    """Return [(path, size)] for usable .gguf files. Skips mmproj files and split shards after the first."""
    found = {}
    for base in dirs:
        if not base.is_dir():
            continue
        base_depth = len(base.parts)
        for root, subdirs, files in os.walk(base):
            if len(Path(root).parts) - base_depth >= max_depth:
                subdirs[:] = []
            for name in files:
                low = name.lower()
                if not low.endswith(".gguf") or "mmproj" in low:
                    continue
                m = SHARD.search(name)
                if m and m.group(1) != "00001":
                    continue
                p = Path(root) / name
                try:
                    found[str(p.resolve())] = p.stat().st_size
                except OSError:
                    continue
    return sorted(((Path(k), v) for k, v in found.items()), key=lambda kv: -kv[1])


_NOISE = re.compile(r"^(mmproj|gguf|f16|f32|bf16|fp16|fp32|i1|imatrix|q\d.*|iq\d.*|\d{5}|of|ud)$")


def _identity(name):
    """Lower-case name tokens without quantisation and projector words: 'mmproj-gemma-4-12b-f16' -> {gemma,4,12b}."""
    return {t for t in re.split(r"[-_.\s]+", name.lower()) if t and not _NOISE.match(t)}


def find_mmproj(model_path):
    """The vision projector (mmproj .gguf) that belongs to a model, or None.
    Without --mmproj llama-server loads the text part only and every image is ignored or rejected.
    A projector is used when its name tokens all appear in the model name, or when the folder holds
    exactly one model and one projector."""
    folder = Path(model_path).parent
    try:
        files = [f for f in folder.iterdir() if f.is_file() and f.name.lower().endswith(".gguf")]
    except OSError:
        return None
    projectors = sorted(f for f in files if "mmproj" in f.name.lower())
    if not projectors:
        return None
    mine = _identity(Path(model_path).name)
    best, best_score = None, 0
    for f in projectors:
        ident = _identity(f.name)
        if ident and ident <= mine and len(ident) > best_score:
            best, best_score = f, len(ident)
    if best:
        return best
    models = [f for f in files if "mmproj" not in f.name.lower()]
    if len(models) == 1 and len(projectors) == 1:
        return projectors[0]
    return None


def assign_roles(models):
    """Map each role to one model file. Few models: roles share them. Returns {role: path}."""
    if not models:
        return {}
    left = list(models)
    roles = {}
    for role in ROLES:
        for item in left:
            if any(h in item[0].name.lower() for h in HINTS[role]):
                roles[role] = item[0]
                left.remove(item)
                break
    pool = left or list(models)  # biggest first
    i = 0
    for role in ROLES:
        if role not in roles:
            roles[role] = pool[i % len(pool)][0]
            i += 1
    return roles


def server_exe(runtime):
    for sub in ("llama-vulkan", "llama", "llama-cpu"):
        p = Path(runtime) / "runtime" / sub / "llama-server.exe"
        if p.is_file():
            return p
    return None


def arg(p):
    """A path as a command-line argument. Forward slashes (no escape problems in the command parser),
    double quotes only when the path has a space. llama-server accepts forward slashes on Windows."""
    p = str(p).replace("\\", "/")
    return f'"{p}"' if " " in p else p


def exe_arg(runtime, exe):
    """The llama-server path as an ABSOLUTE command-line argument.
    A relative path (..\\llama-vulkan\\llama-server.exe) only works when llama-swap starts with the right
    working directory. The generated config lives in the data folder, so never depend on that."""
    return arg(Path(exe).resolve() if Path(exe).exists() else Path(exe))


_EXE_TOKEN = re.compile(r"(?m)^(\s+)(\"[^\"]*llama-server(?:\.exe)?\"|\S*llama-server(?:\.exe)?)(\s+--port)")


def absolutize_exe(text, runtime):
    """Make every relative llama-server path in a config absolute. Relative paths are read from
    <runtime>/runtime/llama-swap, the folder the bundled config was written for. Returns (text, changed)."""
    base = Path(runtime) / "runtime" / "llama-swap"
    changed = []

    def fix(m):
        raw = m.group(2).strip('"').replace("\\", "/")
        if re.match(r"^([A-Za-z]:/|/|\$)", raw):
            return m.group(0)
        changed.append(raw)
        path = os.path.normpath(str(base / raw))
        return m.group(1) + arg(path) + m.group(3)
    out = _EXE_TOKEN.sub(fix, text)
    return out, bool(changed)


def _context_for(size_bytes):
    """Pick a llama-server context length (-c) for a model from its .gguf file size.

    Bigger weights leave less VRAM for the KV cache, so a big model gets a smaller context.
    This shapes only the GENERATED fallback config: the hand-tuned bundled config still wins
    when its models are present (see choose()), so a new PC no longer gets a blind -c 16384
    that spills a 16-20 GB model to shared memory and collapses tok/s.
    ATLAS_LLAMA_CTX overrides every model with one exact value (the manual knob).
    Do NOT add --fit / --fit-target here: HANDOFF.md 2026-11-06 found them wrong on Vulkan/Windows.
    """
    # ponytail: file-size heuristic, not a VRAM/KV-cache measurement. Upgrade to a real estimate
    # (VRAM minus weight bytes, divided by per-token KV cost) if a real PC still spills.
    override = os.environ.get("ATLAS_LLAMA_CTX", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    gb = size_bytes / (1024 ** 3)
    if gb <= 0:
        return 8192       # size unknown: safe middle, not the biggest
    if gb >= 14:
        return 4096       # does not fully fit a 16 GB card: keep the KV cache small
    if gb >= 8:
        return 8192       # 14B-class at Q4 (about 9 GB)
    if gb >= 4:
        return 16384
    return 32768          # 7B-class: room to spare


def build_config(runtime, roles):
    exe = server_exe(runtime)
    if exe is None or not roles:
        return None
    by_file = {}
    for role, path in roles.items():
        by_file.setdefault(path, []).append(role)
    lines = [
        "# Generated by model_discovery.py from the .gguf files found on this PC. Do not edit: it is rewritten at start.",
        "# -c (context) is sized per model from its file size (see _context_for). Set ATLAS_LLAMA_CTX to force one value.",
        "healthCheckTimeout: 300",
        "",
        "models:",
    ]
    for path, names in by_file.items():
        first, rest = names[0], names[1:]
        try:
            size = Path(path).stat().st_size
        except OSError:
            size = 0
        ctx = _context_for(size)
        lines += [
            f'  "{first}":',
            "    cmd: >",
            f"      {exe_arg(runtime, exe)} --port ${{PORT}}",
            f"      -m {arg(path)}",
            f"      -ngl 99 -c {ctx} -fa on -np 1 --jinja",
        ]
        proj = find_mmproj(path)
        if proj:
            lines.append(f"      --mmproj {arg(proj)}")
        if rest:
            lines.append("    aliases: [" + ", ".join(f'"{r}"' for r in rest) + "]")
        lines.append("    ttl: 900")
        lines.append("")
    return "\n".join(lines)


def bundled_ok(config_path):
    """True when the config exists and every -m file in it exists."""
    try:
        text = Path(config_path).read_text(encoding="utf-8")
    except OSError:
        return False
    files = [m.strip('"') for m in MODEL_ARG.findall(text)]
    return bool(files) and all(Path(f).is_file() for f in files)


def render_template(text, models_dir):
    """Replace {models} in the -m arguments with a real folder."""
    base = str(models_dir).replace("\\", "/").rstrip("/")
    return TEMPLATE_ARG.sub(lambda m: m.group(1) + arg(m.group(2).replace("{models}", base)), text)


def template_files(text):
    return [m.group(2) for m in TEMPLATE_ARG.finditer(text)]


def _referenced_basenames(config_text):
    """Lower-case .gguf file names a config already names with -m (template or real path)."""
    out = set()
    for m in MODEL_ARG.findall(config_text):
        p = m.strip('"').replace("\\", "/")
        out.add(p.rsplit("/", 1)[-1].lower())
    return out


def _config_names(config_text):
    """Model keys AND aliases already used in a config, so a discovered model gets a fresh name."""
    names = set(re.findall(r'(?m)^\s*"([^"]+)"\s*:', config_text))
    for group in re.findall(r"aliases:\s*\[([^\]]*)\]", config_text):
        names |= {a.strip().strip('"').strip("'").lower() for a in group.split(",") if a.strip()}
    return {n.lower() for n in names}


def _model_name_from_path(path, taken):
    """A unique, yaml-safe model name from a .gguf path (prefer the parent folder name)."""
    base = (Path(path).parent.name or Path(path).stem).lower()
    base = re.sub(r"[^a-z0-9._-]+", "-", base).strip("-") or "model"
    name, i = base, 2
    while name in taken:
        name, i = f"{base}-{i}", i + 1
    taken.add(name)
    return name


def extra_model_blocks(runtime, config_text, dirs):
    """YAML entries for .gguf files on this PC that `config_text` does not already name.

    This is what lets a model the user downloads later show up in the list on the next
    launch: the tuned/bundled entries are kept as-is and newly found models are appended.
    Returns "" when nothing new is found.
    """
    exe = server_exe(runtime)
    if exe is None:
        return ""
    referenced = _referenced_basenames(config_text)
    taken = _config_names(config_text)
    lines = []
    for path, size in find_models(dirs):
        if Path(path).name.lower() in referenced:
            continue
        name = _model_name_from_path(path, taken)
        ctx = _context_for(size)
        lines += [
            f'  "{name}":',
            "    cmd: >",
            f"      {exe_arg(runtime, exe)} --port ${{PORT}}",
            f"      -m {arg(path)}",
            f"      -ngl 99 -c {ctx} -fa on -np 1 --jinja --load-mode none",
        ]
        proj = find_mmproj(path)
        if proj:
            lines.append(f"      --mmproj {arg(proj)}")
        lines += ["    ttl: 900", ""]
    return "\n".join(lines)


def _augment(config_text, runtime, dirs, data, base_mode, models_dir=None):
    """Append newly discovered models to config_text; write + return a result dict.

    When nothing new is found, the caller keeps using the original config untouched
    (returns None so the caller can return the plain bundled/template result).
    """
    extras = extra_model_blocks(runtime, config_text, dirs)
    if not extras.strip():
        return None
    out = Path(data) / "llama-swap.generated.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(config_text.rstrip() + "\n\n" + extras, encoding="utf-8")
    result = {"config": str(out), "mode": base_mode + "+discovered", "models": []}
    if models_dir is not None:
        result["models_dir"] = str(models_dir)
    return result


def prune_missing_models(yaml_text):
    """Drop model blocks under 'models:' whose -m or --mmproj file does not exist on disk.

    Returns (cleaned_yaml, kept_count, dropped_names). Prevents a stale or personal-path
    entry (for example a removed Downloads/*.gguf) from lingering in llama-swap.generated.yaml
    and causing llama-swap HTTP 500 'upstream command exited prematurely'.
    """
    lines = yaml_text.splitlines(keepends=True)
    out = []
    in_models = False
    kept = 0
    dropped = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not in_models:
            out.append(line)
            if stripped == "models:":
                in_models = True
            i += 1
            continue
        # Top-level non-indented key ends the models: section.
        if stripped and not line[0].isspace() and not stripped.startswith("#"):
            in_models = False
            out.append(line)
            i += 1
            continue
        m = _MODEL_KEY_RE.match(line.rstrip("\r\n"))
        if not m:
            out.append(line)
            i += 1
            continue
        name = m.group(1).strip("\"'")
        block = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            nxt_stripped = nxt.strip()
            if nxt_stripped and not nxt[0].isspace() and not nxt_stripped.startswith("#"):
                break
            if _MODEL_KEY_RE.match(nxt.rstrip("\r\n")):
                break
            block.append(nxt)
            i += 1
        block_text = "".join(block)
        paths = [p.strip('"') for p in MODEL_ARG.findall(block_text)]
        if paths and not all(Path(p).is_file() for p in paths):
            dropped.append(name)
        else:
            out.extend(block)
            kept += 1
    return "".join(out), kept, dropped


def try_template(runtime, bundled, dirs, data):
    """The bundled config names models as {models}/sub/file.gguf. Use the first folder that holds all of them."""
    try:
        text = Path(bundled).read_text(encoding="utf-8")
    except OSError:
        return None
    files = template_files(text)
    if not files:
        return None
    for d in dirs:
        if all((d / f.replace("{models}", "").lstrip("/\\")).is_file() for f in files):
            rendered = render_template(text, d)
            # Drop stale entries whose .gguf vanished so llama-swap won't fail to start,
            # then keep the tuned entries and add any models the user downloaded later.
            cleaned, kept, dropped = prune_missing_models(rendered)
            if kept <= 0:
                continue
            augmented = _augment(cleaned, runtime, dirs, data, "bundled-template", models_dir=d)
            if augmented:
                if dropped:
                    augmented["dropped_missing"] = dropped
                return augmented
            out = Path(data) / "llama-swap.generated.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(cleaned, encoding="utf-8")
            result = {"config": str(out), "mode": "bundled-template", "models": [], "models_dir": str(d)}
            if dropped:
                result["dropped_missing"] = dropped
            return result
    return None


def overrides_path(data):
    return Path(data) / "model-map.json"


def load_overrides(data):
    """{alias: absolute .gguf path} the user chose on the Models screen. Bad entries are dropped."""
    try:
        raw = json.loads(overrides_path(data).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in ALIASES and isinstance(v, str) and v.lower().endswith(".gguf")}


def save_overrides(data, mapping):
    clean = {k: v for k, v in mapping.items() if k in ALIASES and isinstance(v, str) and v.strip()}
    overrides_path(data).parent.mkdir(parents=True, exist_ok=True)
    overrides_path(data).write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean


_BLOCK_START = re.compile(r'(?m)^  ("?)([^"\s:#][^":]*)\1\s*:\s*$')
_ALIAS_LINE = re.compile(r"(?m)^(\s+aliases:\s*)\[([^\]]*)\]\s*$")


def _split_blocks(text):
    """(header, [(name, block_text)]). A block starts at '  name:' under 'models:' and runs to the next one."""
    start = text.find("\nmodels:")
    if start < 0:
        return text, []
    start = text.find("\n", start + 1) + 1
    head, body = text[:start], text[start:]
    marks = [(m.start(), m.group(2)) for m in _BLOCK_START.finditer(body)]
    blocks = []
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        blocks.append((name, body[pos:end]))
    return head + body[:marks[0][0]] if marks else head, blocks


def _block_aliases(block):
    m = _ALIAS_LINE.search(block)
    return [a.strip().strip('"').strip("'") for a in m.group(2).split(",") if a.strip()] if m else []


def _set_model(block, path):
    """Replace the -m file (and the --mmproj file) of one block. Everything else stays as tuned."""
    block = re.sub(r"(-m\s+)(\"[^\"]+\"|\S+)", lambda m: m.group(1) + arg(path), block, count=1)
    block = re.sub(r"\n\s+--mmproj\s+(\"[^\"]+\"|\S+)", "", block)
    proj = find_mmproj(path)
    if proj:
        block = re.sub(r"(-m\s+(?:\"[^\"]+\"|\S+)[^\n]*)", lambda m: m.group(1) + f"\n      --mmproj {arg(proj)}", block, count=1)
    return block


def apply_overrides(text, runtime, overrides):
    """Point each aliased model at the file the user chose. Tuned flags (--n-cpu-moe, -c, MTP) are kept.
    A name that shares a block with other aliases gets its own copy of the block."""
    if not overrides:
        return text
    head, blocks = _split_blocks(text)
    blocks = list(blocks)
    extra = []
    for alias, path in overrides.items():
        hit = next((i for i, (n, b) in enumerate(blocks) if n == alias), None)
        if hit is not None:
            blocks[hit] = (alias, _set_model(blocks[hit][1], path))
            continue
        owner = next((i for i, (n, b) in enumerate(blocks) if alias in _block_aliases(b)), None)
        if owner is not None:  # leave the shared block; this name gets its own block below
            name, block = blocks[owner]
            left = [a for a in _block_aliases(block) if a != alias]
            repl = (lambda m: m.group(1) + "[" + ", ".join(f'"{a}"' for a in left) + "]") if left else ""
            blocks[owner] = (name, _ALIAS_LINE.sub(repl, block))
        exe = server_exe(runtime)
        if exe is None:
            continue
        # Safe default flags: the tuned flags of another model (--n-cpu-moe, MTP) may not fit this file.
        size = Path(path).stat().st_size if Path(path).is_file() else 0
        tmp = (f'  "{alias}":\n    cmd: >\n      {exe_arg(runtime, exe)} --port ${{PORT}}\n      -m {arg(path)}\n'
               f"      -ngl 99 -c {_context_for(size)} -fa on -np 1 --jinja --load-mode none\n    ttl: 900\n")
        extra.append((alias, _set_model(tmp, path)))
    out = head + "".join(b if b.endswith("\n") else b + "\n" for _, b in blocks + extra)
    return out


def _with_overrides(result, runtime, data):
    """If the user mapped models on the Models screen, write the config with that mapping applied."""
    ov = load_overrides(data)
    if not ov or result.get("mode") == "none":
        return result
    try:
        text = Path(result["config"]).read_text(encoding="utf-8")
    except OSError:
        return result
    out = Path(data) / "llama-swap.generated.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(apply_overrides(text, runtime, ov), encoding="utf-8")
    return {**result, "config": str(out), "mode": result["mode"] + "+custom"}


def choose(runtime, data, bundled, extra=()):
    result = _with_overrides(_choose(runtime, data, bundled, extra), runtime, data)
    return _absolute_exe(result, runtime, data)


def add_batch_flags(text):
    """Add -ub 2048 -b 2048 to every command that keeps MoE weights on the CPU (--n-cpu-moe) and sets neither.
    Measured 2026-11-18 (docs/FAST-INFERENCE-2026-11-18.md): much faster prompt reading. Returns (text, changed)."""
    changed = False
    out = []
    for line in text.splitlines(keepends=True):
        if "--n-cpu-moe" in line and not re.search(r"(^|\s)(-ub|--ubatch-size|-b|--batch-size)\s", line):
            nl = "\n" if line.endswith("\n") else ""
            line = line.rstrip("\r\n") + " -ub 2048 -b 2048" + nl
            changed = True
        out.append(line)
    return "".join(out), changed


def _absolute_exe(result, runtime, data):
    """Write the chosen config with absolute llama-server paths when it holds relative ones."""
    if result.get("mode") == "none" or not result.get("config"):
        return result
    try:
        text = Path(result["config"]).read_text(encoding="utf-8")
    except OSError:
        return result
    fixed, changed = absolutize_exe(text, runtime)
    fixed, batch_changed = add_batch_flags(fixed)
    changed = changed or batch_changed
    if not changed:
        return result
    out = Path(data) / "llama-swap.generated.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(fixed, encoding="utf-8")
    return {**result, "config": str(out), "mode": result["mode"] + "+abs"}


def list_models(runtime, data, extra=()):
    """For the Models screen: every usable .gguf found, and which file each alias uses today."""
    dirs = search_dirs(runtime, data, extra)
    files = [{"path": str(p), "name": p.name, "gb": round(sz / 1024 ** 3, 1)} for p, sz in find_models(dirs)]
    return {"dirs": [str(d) for d in dirs if d.is_dir()], "files": files, "overrides": load_overrides(data)}


def current_assignments(config_text):
    """{alias: file name} read from a config text (for display only)."""
    _, blocks = _split_blocks(config_text)
    out = {}
    for name, b in blocks:
        m = MODEL_ARG.search(b)
        if not m:
            continue
        fname = m.group(1).strip('"').replace("\\", "/").rsplit("/", 1)[-1]
        for n in [name] + _block_aliases(b):
            out[n] = fname
    return out


def _choose(runtime, data, bundled, extra=()):
    dirs = search_dirs(runtime, data, extra)
    if bundled and bundled_ok(bundled):
        # The tuned config's own models all exist; still append anything downloaded since,
        # so a new model shows up in the list on the next launch.
        try:
            bundled_text = Path(bundled).read_text(encoding="utf-8")
        except OSError:
            bundled_text = ""
        augmented = _augment(bundled_text, runtime, dirs, data, "bundled") if bundled_text else None
        if augmented:
            return augmented
        return {"config": str(bundled), "mode": "bundled", "models": []}
    if bundled:
        hit = try_template(runtime, bundled, dirs, data)
        if hit:
            return hit
    models = find_models(dirs)
    roles = assign_roles(models)
    generated = build_config(runtime, roles)
    if generated is None:
        return {"config": str(bundled or ""), "mode": "none", "models": [str(m[0]) for m in models]}
    out = Path(data) / "llama-swap.generated.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generated, encoding="utf-8")
    return {"config": str(out), "mode": "generated", "models": [str(m[0]) for m in models], "roles": {k: str(v) for k, v in roles.items()}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--config", default="")
    ap.add_argument("--models", action="append", default=[])
    a = ap.parse_args(argv)
    print(json.dumps(choose(a.runtime, a.data, a.config or None, a.models)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
