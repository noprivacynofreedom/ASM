"""Build step: make a staging copy of the shipped backend with the private core compiled by Nuitka.
Run by build-release.ps1 with the bundled Python, after check-bundle.py.

Run by hand:  <bundled python> <project folder>\\compile_core.py

- The source folder (resources/atlas) is never changed. Tauri packs the staging copy instead.
- Core = core-files.txt paths under resources/atlas. Each core .py becomes a .pyd extension module.
  A script with `if __name__ == "__main__"` keeps a 4-line launcher .py that calls the compiled main().
- Core sources are deleted only after EVERY core file compiled. Any failure: exit 1, the build stops.
- Not copied to staging: runtime/ (Tauri packs it from the source folder), this PC's data
  (PERSONAL below: data.json, data/, .atlas/, logs ...), __pycache__, *.pyc, *.log,
  and tests/ folders inside the core.
Exit code 0 = staging is ready and its server.py imports, 1 = the build must stop.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import subprocess
import threading
import sys
from pathlib import Path

from export_public import matches, read_patterns

ROOT = Path(__file__).resolve().parent
TAURI = ROOT / "atlas-rust-desktop" / "src-tauri"
BUNDLE = TAURI / "resources" / "atlas"
STAGING = TAURI / "core-staging" / "atlas"
PREFIX = "atlas-rust-desktop/src-tauri/resources/atlas/"
NUITKA_VENV = ROOT / "build-tools" / "nuitka-venv"
NUITKA_CACHE = ROOT / "build-tools" / "nuitka-cache"
# Top-level names in resources/atlas that are this PC's own data, never shipped. The installed app
# reads its data from ATLAS_DATA_DIR. settings.json stays: main.rs copies it on first start.
PERSONAL = {"runtime", "data.json", "data", ".atlas", "logs", "bots", "exports", "swarm-workspaces",
            "swarm-output", "settings.local.json"}
NUITKA_VERSION = "4.3.5"  # Checked 2026-11-15 with the bundled Python 3.14.6 and MSVC cl 14.5.

LAUNCHER = '''# Launcher: runs the compiled module {name} (the .pyd next to this file). Made by compile_core.py.
import asyncio, inspect
from {name} import main
_result = main()
raise SystemExit(asyncio.run(_result) if inspect.iscoroutine(_result) else _result)
'''


def bundle_core_patterns(root=ROOT):
    """core-files.txt patterns that point inside resources/atlas, made relative to it."""
    return [p[len(PREFIX):] for p in read_patterns(root / "core-files.txt") if p.startswith(PREFIX)]


def needs_launcher(py):
    """True for a script with a __main__ guard. Raises ValueError if it has no top-level main()."""
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    guarded = any(isinstance(n, ast.If) and "__main__" in ast.unparse(n.test) for n in tree.body)
    has_main = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "main" for n in tree.body)
    if guarded and not has_main:
        raise ValueError(f"{py.name} runs as a script but has no main() function. Add one so the launcher can call it.")
    return guarded


def nuitka(py):
    """Compile one module next to itself. Returns the exit code."""
    cmd = [str(nuitka_python()), "-m", "nuitka", "--module", py.name, "--nofollow-imports",
           "--output-dir=.", "--remove-output", "--assume-yes-for-downloads", "--msvc=latest", "--quiet"]
    return subprocess.run(cmd, cwd=py.parent).returncode


_VENV_LOCK = threading.Lock()


def nuitka_python():
    """Nuitka lives in its own venv, so it never ships inside the bundled Python.
    One thread sets it up (parallel jobs raced on a fresh PC). The marker is written only after pip
    succeeds, so a half-made venv gets its install finished on the next build."""
    py = NUITKA_VENV / "Scripts" / "python.exe"
    marker = NUITKA_VENV / f"nuitka-{NUITKA_VERSION}.ok"
    with _VENV_LOCK:
        if not marker.is_file():
            if not py.is_file():
                subprocess.run([sys.executable, "-m", "venv", str(NUITKA_VENV)], check=True)
            subprocess.run([str(py), "-m", "pip", "install", "--quiet", f"nuitka=={NUITKA_VERSION}"], check=True)
            marker.write_text("ok\n", encoding="utf-8")
    return py


def _python_tag():
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _find_compiled_pyd(py):
    """Return the compiled .pyd next to `py`, or None."""
    matches_pyd = sorted(py.parent.glob(f"{py.stem}.*.pyd"))
    if matches_pyd:
        return matches_pyd[0]
    direct = py.with_suffix(".pyd")
    return direct if direct.is_file() else None


def _try_cache_hit(py, rel, src_hash, cache_dir):
    if cache_dir is None:
        return False
    mod_cache = Path(cache_dir) / rel
    meta_file = mod_cache / "meta.json"
    if not meta_file.is_file():
        return False
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (meta.get("sha256") != src_hash or meta.get("python") != _python_tag()
            or meta.get("nuitka") != NUITKA_VERSION):
        return False
    pyd_name = meta.get("pyd")
    if not pyd_name or "/" in pyd_name or "\\" in pyd_name:
        return False
    cached_pyd = mod_cache / pyd_name
    if not cached_pyd.is_file():
        return False
    shutil.copy2(cached_pyd, py.parent / pyd_name)
    return True


def _save_cache(py, rel, src_hash, cache_dir):
    if cache_dir is None:
        return
    pyd_file = _find_compiled_pyd(py)
    if pyd_file is None:
        return
    mod_cache = Path(cache_dir) / rel
    mod_cache.mkdir(parents=True, exist_ok=True)
    for old in mod_cache.glob("*.pyd"):
        old.unlink(missing_ok=True)
    shutil.copy2(pyd_file, mod_cache / pyd_file.name)
    meta = {"sha256": src_hash, "python": _python_tag(), "nuitka": NUITKA_VERSION, "pyd": pyd_file.name}
    (mod_cache / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def compile_core(bundle, staging, core, compiler=nuitka, cache_dir=None):
    """Stage bundle into staging and compile the core there. Returns a list of problems (empty = ok)."""
    bundle, staging = Path(bundle), Path(staging)
    if staging.exists():
        shutil.rmtree(staging)

    def skip(folder, names):
        rel = Path(folder).relative_to(bundle)
        return [n for n in names if n == "__pycache__" or n.endswith((".pyc", ".log"))
                or (rel == Path(".") and n in PERSONAL)
                or (n == "tests" and matches((rel / n / "x.py").as_posix(), core))]

    settings = bundle / "settings.json"
    if settings.is_file():
        rows = json.loads(settings.read_text(encoding="utf-8")).get("mcp_servers") or []
        with_env = [str(r.get("name")) for r in rows if isinstance(r, dict) and r.get("env")]
        if with_env:
            return [f"resources/atlas/settings.json ships to every user, but MCP servers {with_env} have env values "
                    "(keys or tokens?). Move them to your data folder's settings.json."]

    shutil.copytree(bundle, staging, ignore=skip)

    core_files = [p for p in sorted(staging.rglob("*.py")) if matches(p.relative_to(staging).as_posix(), core)]
    launchers, problems = {}, []
    compile_workers = min(6, max(1, (os.cpu_count() or 2) // 2))

    def compile_one(py):
        rel = py.relative_to(staging).as_posix()
        try:
            launcher = needs_launcher(py)
        except (ValueError, SyntaxError) as exc:
            return py, None, f"{rel}: {exc}"
        src_hash = hashlib.sha256(py.read_bytes()).hexdigest() if cache_dir is not None else ""
        if _try_cache_hit(py, rel, src_hash, cache_dir):
            print("Cached", rel, flush=True)
            return py, launcher, None
        print("Compiling", rel, flush=True)
        try:
            if compiler(py) != 0:
                return py, launcher, f"{rel}: Nuitka failed"
        except Exception as exc:
            return py, launcher, f"{rel}: Nuitka failed ({type(exc).__name__}: {exc})"
        _save_cache(py, rel, src_hash, cache_dir)
        return py, launcher, None

    # Each Nuitka module compiles in its own folder, so bounded parallel jobs are safe.
    with ThreadPoolExecutor(max_workers=compile_workers) as pool:
        outcomes = list(pool.map(compile_one, core_files))
    for py, launcher, problem in outcomes:
        if launcher is not None:
            launchers[py] = launcher
        if problem:
            problems.append(problem)
    if problems:
        return problems  # Nothing deleted yet: no half-compiled bundle.

    for py in core_files:
        py.unlink()
        py.with_suffix(".pyi").unlink(missing_ok=True)
        if launchers[py]:
            py.write_text(LAUNCHER.format(name=py.stem), encoding="utf-8")
    return []


def readable_core(folder, core):
    """Core .py files in folder that are not launchers. Used after the build on target/release/atlas."""
    folder = Path(folder)
    return [p.relative_to(folder).as_posix() for p in sorted(folder.rglob("*.py"))
            if matches(p.relative_to(folder).as_posix(), core)
            and not p.read_text(encoding="utf-8", errors="replace").startswith("# Launcher:")]


# Tauri merges this over tauri.conf.json (tauri build --config). null removes the source mapping.
# runtime/ is mapped on its own because compile_core.py does not copy the 1.3 GB Python.
TAURI_OVERRIDE = {"bundle": {"resources": {
    "resources/atlas": None,
    "core-staging/atlas": "atlas",
    "resources/atlas/runtime": "atlas/runtime",
}}}


def tauri_override(fast_nsis=False):
    """Config that build-release.ps1 passes to Tauri. fast_nsis: no installer compression.

    Faster NSIS step, much larger installer. tauri.conf.json keeps "zlib" for normal builds,
    and this file is written fresh every build, so a fast build never sticks.
    """
    override = json.loads(json.dumps(TAURI_OVERRIDE))
    if fast_nsis:
        override["bundle"]["windows"] = {"nsis": {"compression": "none"}}
    return override


def main(argv=sys.argv):
    core = bundle_core_patterns()
    fast_nsis = "--fast-nsis" in argv[1:]
    no_cache = "--no-cache" in argv[1:]
    argv = [a for a in argv if a not in ("--fast-nsis", "--no-cache")]
    if len(argv) == 3 and argv[1] == "--check":
        leaked = readable_core(argv[2], core)
        for rel in leaked:
            print("READABLE CORE IN BUILD OUTPUT:", rel)
        return 1 if leaked else 0

    problems = compile_core(BUNDLE, STAGING, core, cache_dir=None if no_cache else NUITKA_CACHE)
    if not problems:
        check = subprocess.run([sys.executable, str(ROOT / "check-bundle.py"), str(STAGING)])
        if check.returncode != 0:
            problems.append("the compiled staging copy does not import (see above)")
    if problems:
        print("CORE COMPILE FAILED:")
        for p in problems:
            print(" - " + p)
        return 1
    (STAGING.parent / "tauri.core.conf.json").write_text(json.dumps(tauri_override(fast_nsis), indent=2), encoding="utf-8")
    print("Core compiled. Staging copy ready:", STAGING)
    return 0


if __name__ == "__main__":
    sys.exit(main())
