"""Safe, repeatable local Build/Test/Diagnose cycle for Atlas.

Only fixed, project-local validation commands are executable. No model-provided
shell commands are accepted. Results and user feedback live under .atlas/.
"""
from __future__ import annotations
import json, os, subprocess, sys, threading, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get('ATLAS_DATA_DIR', ROOT))
STATE_DIR = DATA_ROOT / '.atlas'
STATE_FILE = STATE_DIR / 'dev_cycles.json'
_LOCK = threading.RLock()
_CURRENT = None


def _load_history():
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_history(items):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(items[-50:], indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, STATE_FILE)


def _run_step(name, args, timeout=180):
    started = time.time()
    try:
        p = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                           errors='replace', timeout=timeout, shell=False)
        return {'name': name, 'status': 'passed' if p.returncode == 0 else 'failed',
                'returncode': p.returncode, 'stdout': p.stdout[-12000:],
                'stderr': p.stderr[-12000:], 'duration_seconds': round(time.time()-started, 2)}
    except subprocess.TimeoutExpired as e:
        return {'name': name, 'status': 'failed', 'returncode': None,
                'stdout': (e.stdout or '')[-12000:] if isinstance(e.stdout, str) else '',
                'stderr': 'Timed out after %s seconds' % timeout,
                'duration_seconds': round(time.time()-started, 2)}
    except OSError as e:
        return {'name': name, 'status': 'failed', 'returncode': None,
                'stdout': '', 'stderr': str(e), 'duration_seconds': round(time.time()-started, 2)}


def _execute(cycle_id):
    global _CURRENT
    started = time.time()
    py = sys.executable
    steps = []

    def run_step(name, args):
        with _LOCK:
            if _CURRENT and _CURRENT.get('id') == cycle_id:
                _CURRENT['current_step'] = name
        try:
            result = _run_step(name, args)
        except Exception as e:
            result = {'name':name, 'status':'failed', 'returncode':None,
                      'stdout':'', 'stderr':str(e),
                      'duration_seconds':round(time.time()-started,2)}
        steps.append(result)
        with _LOCK:
            if _CURRENT and _CURRENT.get('id') == cycle_id:
                _CURRENT['steps'] = list(steps)
                _CURRENT['current_step'] = None
        return result
    tests_dir = ROOT / 'tests'
    # unittest discovery only counts TestCase methods. A standalone smoke-test
    # script can exist without containing discoverable tests, so keep discovery
    # recursive and let the runner report the real count and failures.
    if tests_dir.is_dir() and any(t.name.startswith('test_') and t.suffix == '.py' for t in tests_dir.rglob('*.py')):
        run_step('Python automated tests', [py, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v'])
    else:
        steps.append({'name':'Python automated tests','status':'skipped','returncode':None,
                      'stdout':'No tests/test_*.py files found. Add unittest.TestCase tests to enable this stage.',
                      'stderr':'','duration_seconds':0})
    compile_files = ['server.py', 'docsearch.py', 'knowledge_engine.py', 'mcp_monitor.py', 'mcp_chat.py', 'dev_cycle.py', 'src/mcp_commander.py']
    existing = [f for f in compile_files if (ROOT / f).is_file()]
    run_step('Python syntax validation', [py, '-m', 'py_compile', *existing])
    failed = [s for s in steps if s['status'] == 'failed']
    skipped = [s for s in steps if s['status'] == 'skipped']
    status = 'failed' if failed else ('passed_with_skips' if skipped else 'passed')
    cycle = {'id':cycle_id, 'status':status, 'started_at':started,
             'finished_at':time.time(), 'duration_seconds':round(time.time()-started,2),
             'steps':steps, 'survey':None}
    with _LOCK:
        history = _load_history(); history.append(cycle); _save_history(history)
        _CURRENT = cycle
    return cycle


def start_cycle():
    global _CURRENT
    with _LOCK:
        if _CURRENT and _CURRENT.get('status') == 'running':
            return {'ok':False, 'error':'A validation cycle is already running', 'cycle':_CURRENT}
        cid = uuid.uuid4().hex[:12]
        _CURRENT = {'id':cid, 'status':'running', 'started_at':time.time(),
                    'steps':[], 'current_step':None, 'survey':None}
        thread = threading.Thread(target=_execute, args=(cid,), daemon=True, name='atlas-dev-cycle')
        thread.start()
        return {'ok':True, 'cycle':_CURRENT}


def get_status():
    with _LOCK:
        if _CURRENT:
            return {'ok':True, 'cycle':_CURRENT, 'history':_load_history()[-10:]}
        history = _load_history()
        return {'ok':True, 'cycle':history[-1] if history else None, 'history':history[-10:]}


def submit_feedback(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('cycle_id'), str):
        return {'ok':False, 'error':'cycle_id is required'}
    with _LOCK:
        history = _load_history()
        for item in reversed(history):
            if item.get('id') == payload['cycle_id']:
                feedback = {'experience':str(payload.get('experience',''))[:2000],
                            'observed_issue':str(payload.get('observed_issue',''))[:4000],
                            'next_action':str(payload.get('next_action',''))[:1000],
                            'submitted_at':time.time()}
                item['survey'] = feedback
                _save_history(history)
                if _CURRENT and _CURRENT.get('id') == item['id']:
                    _CURRENT['survey'] = feedback
                return {'ok':True, 'cycle_id':item['id'], 'survey':feedback}
    return {'ok':False, 'error':'Cycle not found'}


def get_agent_context(max_items=3):
    """Return recent user validation feedback for the next agent iteration."""
    rows = [item for item in _load_history() if isinstance(item, dict) and isinstance(item.get('survey'), dict)]
    context = []
    for item in rows[-max(1, min(int(max_items), 5)):]:
        survey = item.get('survey') or {}
        context.append({
            'cycle_id': str(item.get('id', '')),
            'test_status': str(item.get('status', 'unknown')),
            'experience': str(survey.get('experience', ''))[:300],
            'observed_issue': str(survey.get('observed_issue', ''))[:800],
            'next_action': str(survey.get('next_action', ''))[:300],
        })
    if not context:
        return ''
    return 'RECENT ATLAS DEVELOPMENT-CYCLE USER FEEDBACK (treat as requirements for the next relevant iteration):\n' + json.dumps(context, ensure_ascii=False, indent=2)
