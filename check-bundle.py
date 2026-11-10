"""Pre-build check: can the Python backend that ships in the installer start?
Run by build-release.ps1 with the bundled interpreter, before anything is built.

Added 2026-11-09: server.py imported mcp_audit, which was never copied into
resources/atlas. It only worked while an old dev server held port 8090.
Exit code 0 = fine, 1 = the build must stop.
"""
import ast
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
BUNDLE = ROOT / "atlas-rust-desktop" / "src-tauri" / "resources" / "atlas"


def local_modules(folder):
    names = {p.stem for p in folder.glob("*.py")}
    names |= {p.name for p in folder.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    return names


def imported(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module.split(".")[0]


def main():
    problems = []

    # 1. Every project module the bundle imports must be in the bundle: copy in
    #    any that are missing, repeating because a copied file can import more.
    #    Sees imports inside functions too, which step 2 cannot reach.
    project = local_modules(ROOT)
    while True:
        have = local_modules(BUNDLE) | {p.name for p in BUNDLE.iterdir() if p.is_dir()}
        missing = set()
        for path in list(BUNDLE.glob("*.py")) + list((BUNDLE / "agents").glob("*.py")):
            missing |= {n for n in imported(path) if n in project and n not in have}
        if not missing:
            break
        for name in sorted(missing):
            source = ROOT / name
            if source.is_dir():
                shutil.copytree(source, BUNDLE / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(ROOT / f"{name}.py", BUNDLE / f"{name}.py")
            print(f"Copied missing project module into the bundle: {name}")

    # 2. Really import the server, with the interpreter that ships. Data goes
    #    to a throwaway folder so the check cannot touch real chats.
    with tempfile.TemporaryDirectory(prefix="atlas-bundle-check-") as tmp:
        env = dict(os.environ, ATLAS_RUNTIME_ROOT=str(BUNDLE), ATLAS_DATA_DIR=tmp,
                   ATLAS_OBSERVABILITY_DB=str(pathlib.Path(tmp) / "observability.sqlite3"),
                   PYTHONDONTWRITEBYTECODE="1")
        run = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.'); import server"],
                             cwd=BUNDLE, env=env, capture_output=True, text=True, timeout=120)
        if run.returncode != 0:
            problems.append("importing server.py failed:\n" + run.stderr.strip()[-1500:])

    if problems:
        print("BUNDLE CHECK FAILED:")
        for p in problems:
            print(" - " + p)
        return 1
    print("Bundle check passed: the backend imports with the bundled Python.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
