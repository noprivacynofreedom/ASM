"""Atlas local swarm observability: agent registry, correlated events and screenshot frames.
Loopback service only. Agents authenticate with per-agent bearer tokens returned at registration.
"""
from __future__ import annotations
import base64, hashlib, json, os, secrets, sqlite3, threading, time, uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('ATLAS_OBSERVABILITY_DB', Path(os.environ.get('ATLAS_DATA_DIR', ROOT)) / 'data' / 'observability.sqlite3'))
LOCK = threading.RLock()
MAX_EVENT_BYTES = 64 * 1024
MAX_FRAME_BYTES = 2 * 1024 * 1024

@contextmanager
def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS agents(agent_id TEXT PRIMARY KEY,name TEXT NOT NULL,host TEXT,platform TEXT,pid INTEGER,parent_pid INTEGER,model TEXT,status TEXT NOT NULL,task_id TEXT,task_stage TEXT,started_at REAL,last_heartbeat REAL,metadata TEXT NOT NULL DEFAULT '{}',token_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,ts REAL NOT NULL,trace_id TEXT,span_id TEXT,parent_span_id TEXT,agent_id TEXT,task_id TEXT,conversation_id TEXT,bot_id TEXT,level TEXT NOT NULL,kind TEXT NOT NULL,message TEXT NOT NULL,details TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id,seq);
    CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id,seq);
    CREATE TABLE IF NOT EXISTS frames(frame_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,ts REAL NOT NULL,mime TEXT NOT NULL,data BLOB NOT NULL,caption TEXT,task_id TEXT,trace_id TEXT);
    CREATE INDEX IF NOT EXISTS idx_frames_agent ON frames(agent_id,ts DESC);
    CREATE TABLE IF NOT EXISTS tasks(task_id TEXT PRIMARY KEY,created_at REAL NOT NULL,updated_at REAL NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,task_type TEXT NOT NULL,payload TEXT NOT NULL,result TEXT,assigned_agent TEXT,lease_until REAL,trace_id TEXT,conversation_id TEXT,bot_id TEXT,attempts INTEGER NOT NULL DEFAULT 0,error TEXT);
    CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks(status,priority DESC,created_at ASC);
    ''')
    # Forward-compatible migrations: correlate existing tasks/events without discarding history.
    event_columns = {row['name'] for row in c.execute('PRAGMA table_info(events)').fetchall()}
    if 'conversation_id' not in event_columns:
        c.execute('ALTER TABLE events ADD COLUMN conversation_id TEXT')
    if 'bot_id' not in event_columns:
        c.execute('ALTER TABLE events ADD COLUMN bot_id TEXT')
    task_columns = {row['name'] for row in c.execute('PRAGMA table_info(tasks)').fetchall()}
    if 'conversation_id' not in task_columns:
        c.execute('ALTER TABLE tasks ADD COLUMN conversation_id TEXT')
    if 'bot_id' not in task_columns:
        c.execute('ALTER TABLE tasks ADD COLUMN bot_id TEXT')
    c.execute('CREATE INDEX IF NOT EXISTS idx_events_conversation ON events(conversation_id,seq)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id,created_at DESC)')
    # Forward-compatible migration for databases created before task-correlated frames.
    frame_columns = {row['name'] for row in c.execute('PRAGMA table_info(frames)').fetchall()}
    if 'task_id' not in frame_columns:
        c.execute('ALTER TABLE frames ADD COLUMN task_id TEXT')
    if 'trace_id' not in frame_columns:
        c.execute('ALTER TABLE frames ADD COLUMN trace_id TEXT')
    c.execute('CREATE INDEX IF NOT EXISTS idx_frames_task ON frames(task_id,ts DESC)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_frames_trace ON frames(trace_id,ts DESC)')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def _json(row): return dict(row) if row else None

def register(payload):
    name=str(payload.get('name') or 'agent')[:100]
    agent_id=str(payload.get('agent_id') or ('agt_'+uuid.uuid4().hex))[:128]
    token=secrets.token_urlsafe(32)
    now=time.time()
    with LOCK, _db() as c:
        c.execute('''INSERT INTO agents(agent_id,name,host,platform,pid,parent_pid,model,status,task_id,task_stage,started_at,last_heartbeat,metadata,token_hash)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET name=excluded.name,host=excluded.host,platform=excluded.platform,pid=excluded.pid,parent_pid=excluded.parent_pid,model=excluded.model,status='online',last_heartbeat=excluded.last_heartbeat,metadata=excluded.metadata,token_hash=excluded.token_hash''',
        (agent_id,name,str(payload.get('host',''))[:255],str(payload.get('platform',''))[:100],_int(payload.get('pid')),_int(payload.get('parent_pid')),str(payload.get('model',''))[:200],'online',None,None,now,now,json.dumps(payload.get('metadata') if isinstance(payload.get('metadata'),dict) else {}),hashlib.sha256(token.encode()).hexdigest()))
        _event(c,agent_id,None,'info','agent.registered',f'{name} registered',{'pid':payload.get('pid')})
    return {'agent_id':agent_id,'token':token,'heartbeat_interval_seconds':10}

def _int(v):
    try: return max(0,int(v)) if v is not None else None
    except (TypeError,ValueError): return None

def _auth(c,agent_id,token):
    row=c.execute('SELECT token_hash FROM agents WHERE agent_id=?',(agent_id,)).fetchone()
    return bool(row and secrets.compare_digest(row['token_hash'],hashlib.sha256(str(token or '').encode()).hexdigest()))

def _event(c,agent_id,task_id,level,kind,message,details=None,trace_id=None,span_id=None,parent_span_id=None,conversation_id=None,bot_id=None):
    c.execute('INSERT INTO events(event_id,ts,trace_id,span_id,parent_span_id,agent_id,task_id,conversation_id,bot_id,level,kind,message,details) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
      (uuid.uuid4().hex,time.time(),trace_id,span_id,parent_span_id,agent_id,task_id,conversation_id,bot_id,level,kind,message,json.dumps(details or {},ensure_ascii=False)[:MAX_EVENT_BYTES]))

def _task_context(c, task_id):
    if not task_id:
        return (None, None)
    row = c.execute('SELECT conversation_id,bot_id FROM tasks WHERE task_id=?', (str(task_id)[:128],)).fetchone()
    return (row['conversation_id'], row['bot_id']) if row else (None, None)


def heartbeat(agent_id,token,payload):
    now=time.time()
    with LOCK, _db() as c:
        if not _auth(c,agent_id,token): return False
        c.execute('UPDATE agents SET host=?,platform=?,pid=?,parent_pid=?,model=?,status=?,task_id=?,task_stage=?,last_heartbeat=?,metadata=? WHERE agent_id=?',
          (str(payload.get('host',''))[:255],str(payload.get('platform',''))[:100],_int(payload.get('pid')),_int(payload.get('parent_pid')),str(payload.get('model',''))[:200],str(payload.get('status','online'))[:32],str(payload.get('task_id'))[:128] if payload.get('task_id') else None,str(payload.get('task_stage'))[:128] if payload.get('task_stage') else None,now,json.dumps(payload.get('metrics') if isinstance(payload.get('metrics'),dict) else {}),agent_id))
        task_id=payload.get('task_id')
        conversation_id,bot_id=_task_context(c,task_id)
        _event(c,agent_id,task_id,'debug','agent.heartbeat','Agent heartbeat',payload.get('metrics') if isinstance(payload.get('metrics'),dict) else {},conversation_id=conversation_id,bot_id=bot_id)
    return True

def ingest_event(agent_id,token,payload):
    if len(json.dumps(payload,ensure_ascii=False).encode())>MAX_EVENT_BYTES: raise ValueError('event payload exceeds 64KB')
    with LOCK, _db() as c:
        if not _auth(c,agent_id,token): return False
        task_id=payload.get('task_id')
        task_conversation,task_bot=_task_context(c,task_id)
        conversation_id=str(payload.get('conversation_id') or task_conversation or '')[:128] or None
        bot_id=str(payload.get('bot_id') or task_bot or '')[:128] or None
        _event(c,agent_id,task_id,str(payload.get('level','info'))[:16],str(payload.get('kind','agent.event'))[:100],str(payload.get('message',''))[:2000],payload.get('details') if isinstance(payload.get('details'),dict) else {},str(payload.get('trace_id') or '')[:128] or None,str(payload.get('span_id') or '')[:128] or None,str(payload.get('parent_span_id') or '')[:128] or None,conversation_id,bot_id)
    return True

def ingest_frame(agent_id,token,payload):
    mime=str(payload.get('mime','image/jpeg'))
    if mime not in ('image/jpeg','image/png','image/webp'): raise ValueError('unsupported image type')
    raw=base64.b64decode(payload.get('data',''),validate=True)
    if not raw or len(raw)>MAX_FRAME_BYTES: raise ValueError('frame must be between 1 byte and 2MB')
    # Validate actual image signature rather than trusting MIME metadata.
    valid={'image/jpeg':raw.startswith(b'\xff\xd8\xff'),'image/png':raw.startswith(b'\x89PNG\r\n\x1a\n'),'image/webp':raw.startswith(b'RIFF') and raw[8:12]==b'WEBP'}
    if not valid[mime]: raise ValueError('image bytes do not match declared MIME type')
    frame_id=uuid.uuid4().hex
    with LOCK, _db() as c:
        if not _auth(c,agent_id,token): return None
        c.execute('INSERT INTO frames(frame_id,agent_id,ts,mime,data,caption,task_id,trace_id) VALUES(?,?,?,?,?,?,?,?)',(frame_id,agent_id,time.time(),mime,raw,str(payload.get('caption',''))[:500],str(payload.get('task_id') or '')[:128] or None,str(payload.get('trace_id') or '')[:128] or None))
        c.execute('DELETE FROM frames WHERE agent_id=? AND frame_id NOT IN (SELECT frame_id FROM frames WHERE agent_id=? ORDER BY ts DESC LIMIT 20)',(agent_id,agent_id))
        task_conversation,task_bot=_task_context(c,payload.get('task_id'))
        _event(c,agent_id,payload.get('task_id'),'info','agent.screenshot','Agent screenshot captured',{'frame_id':frame_id,'mime':mime},str(payload.get('trace_id') or '')[:128] or None,conversation_id=task_conversation,bot_id=task_bot)
    return frame_id

def snapshot():
    now=time.time()
    with LOCK, _db() as c:
        rows=c.execute('SELECT * FROM agents ORDER BY last_heartbeat DESC').fetchall()
        agents=[]
        for r in rows:
            d=dict(r); d.pop('token_hash',None); d['metadata']=json.loads(d['metadata'] or '{}'); d['heartbeat_age_seconds']=round(now-(d['last_heartbeat'] or 0),1); d['status']='stale' if d['heartbeat_age_seconds']>30 else d['status'];
            f=c.execute('SELECT frame_id,ts,mime,caption FROM frames WHERE agent_id=? ORDER BY ts DESC LIMIT 1',(d['agent_id'],)).fetchone(); d['latest_frame']=dict(f) if f else None
            agents.append(d)
        return {'agents':agents,'online':sum(a['status']=='online' for a in agents),'stale':sum(a['status']=='stale' for a in agents),'timestamp':now}

def events(after=0,limit=200,agent_id=None,trace_id=None):
    q='SELECT * FROM events WHERE seq>?'; args=[max(0,int(after))]
    if agent_id: q+=' AND agent_id=?'; args.append(agent_id)
    if trace_id: q+=' AND trace_id=?'; args.append(trace_id)
    q+=' ORDER BY seq ASC LIMIT ?'; args.append(max(1,min(1000,int(limit))))
    with LOCK, _db() as c: return [dict(r) for r in c.execute(q,args).fetchall()]

def conversation_activity(conversation_id, after=0, limit=100):
    """Return only cursor, time, event kind, and severity for one conversation."""
    conversation_id = str(conversation_id or '').strip()[:128]
    if not conversation_id:
        return []
    after = max(0, int(after))
    limit = max(1, min(200, int(limit)))
    with LOCK, _db() as c:
        rows = c.execute(
            'SELECT seq,ts,kind,level FROM events '
            'WHERE conversation_id=? AND seq>? ORDER BY seq ASC LIMIT ?',
            (conversation_id, after, limit),
        ).fetchall()
        return [dict(row) for row in rows]

def frame(frame_id):
    with LOCK, _db() as c: return c.execute('SELECT mime,data FROM frames WHERE frame_id=?',(frame_id,)).fetchone()




def record_local_event(conversation_id, bot_id, kind, message, details=None, level='info', trace_id=None):
    """Persist a local chat/MCP lifecycle event without agent credentials."""
    conversation_id = str(conversation_id or '').strip()[:128]
    if not conversation_id:
        return None
    with LOCK, _db() as c:
        _event(c, None, None, str(level or 'info')[:16], str(kind or 'local.event')[:100],
               str(message or '')[:2000], details if isinstance(details, dict) else {},
               str(trace_id or '')[:128] or None, conversation_id=conversation_id,
               bot_id=str(bot_id or '')[:128] or None)
    return True


def conversation_diagnostics(conversation_id):
    """Return persisted tasks and execution events linked to one conversation."""
    conversation_id = str(conversation_id or '').strip()[:128]
    if not conversation_id:
        return {'tasks': [], 'events': []}
    with LOCK, _db() as c:
        tasks = [dict(r) for r in c.execute(
            'SELECT task_id,created_at,updated_at,status,priority,task_type,assigned_agent,attempts,error,trace_id,conversation_id,bot_id,result '
            'FROM tasks WHERE conversation_id=? ORDER BY created_at DESC LIMIT 200',
            (conversation_id,)).fetchall()]
        rows = c.execute(
            'SELECT seq,event_id,ts,trace_id,span_id,parent_span_id,agent_id,task_id,conversation_id,bot_id,level,kind,message,details '
            'FROM events WHERE conversation_id=? ORDER BY seq ASC LIMIT 1000',
            (conversation_id,)).fetchall()
        events_out = [dict(r) for r in rows]
        for row in events_out:
            try: row['details'] = json.loads(row.get('details') or '{}')
            except (TypeError, ValueError): row['details'] = {}
        return {'tasks': tasks, 'events': events_out}

def task_evidence(task_id):
    """Return metadata-only evidence correlated to a task and its trace.

    Screenshot bytes are deliberately excluded; clients retrieve them through
    the existing authenticated/loopback frame endpoint by frame_id.
    """
    task_id = str(task_id or '').strip()
    if not task_id:
        return None
    with LOCK, _db() as c:
        task = c.execute('SELECT task_id,trace_id,status,task_type,created_at,updated_at,assigned_agent,result,error,conversation_id,bot_id FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if not task:
            return None
        trace_id = task['trace_id']
        event_rows = c.execute('SELECT seq,event_id,ts,trace_id,span_id,parent_span_id,agent_id,task_id,conversation_id,bot_id,level,kind,message,details FROM events WHERE task_id=? OR (? IS NOT NULL AND trace_id=?) ORDER BY seq ASC', (task_id, trace_id, trace_id)).fetchall()
        frame_rows = c.execute('SELECT frame_id,agent_id,ts,mime,caption,task_id,trace_id FROM frames WHERE task_id=? OR (? IS NOT NULL AND trace_id=?) ORDER BY ts ASC', (task_id, trace_id, trace_id)).fetchall()
        events_out = [dict(row) for row in event_rows]
        for row in events_out:
            try: row['details'] = json.loads(row['details'] or '{}')
            except (TypeError, ValueError): row['details'] = {}
        return {'task': dict(task), 'trace_id': trace_id, 'events': events_out, 'frames': [dict(row) for row in frame_rows], 'evidence_status': 'unverified'}


def submit_task(payload):
    """Persist a task for an online Swarm agent to claim."""
    if not isinstance(payload, dict): raise ValueError("task payload must be an object")
    task_type=str(payload.get("type") or "inference")[:80]
    body=payload.get("payload", {})
    if not isinstance(body, dict): raise ValueError("task payload.payload must be an object")
    encoded=json.dumps(body,ensure_ascii=False)
    if len(encoded.encode("utf-8"))>256*1024: raise ValueError("task payload exceeds 256KB")
    task_id="tsk_"+uuid.uuid4().hex
    now=time.time(); trace=str(payload.get("trace_id") or uuid.uuid4().hex)[:128]
    conversation_id=str(payload.get("conversation_id") or body.get("conversation_id") or '')[:128] or None
    bot_id=str(payload.get("bot_id") or body.get("bot_id") or '')[:128] or None
    priority=max(-100,min(100,int(payload.get("priority",0))))
    with LOCK,_db() as c:
        c.execute("INSERT INTO tasks(task_id,created_at,updated_at,status,priority,task_type,payload,trace_id,conversation_id,bot_id) VALUES(?,?,?,?,?,?,?,?,?,?)",(task_id,now,now,"queued",priority,task_type,encoded,trace,conversation_id,bot_id))
        _event(c,None,task_id,"info","task.queued","Swarm task queued",{"type":task_type,"priority":priority},trace,conversation_id=conversation_id,bot_id=bot_id)
    return {"task_id":task_id,"status":"queued","trace_id":trace}

def claim_task(agent_id,token,lease_seconds=60,task_types=None):
    now=time.time(); lease=max(10,min(600,int(lease_seconds)))
    if task_types is not None:
        if not isinstance(task_types,list) or not task_types or any(not isinstance(x,str) or not x.strip() or len(x)>80 for x in task_types):
            raise ValueError("task_types must be a non-empty list of strings (1-80 characters)")
        task_types=list(dict.fromkeys(x.strip() for x in task_types))
    with LOCK,_db() as c:
        if not _auth(c,agent_id,token): return None
        sql="SELECT * FROM tasks WHERE (status='queued' OR (status='claimed' AND lease_until<?))"
        args=[now]
        if task_types is not None:
            sql += " AND task_type IN (" + ",".join("?" for _ in task_types) + ")"
            args.extend(task_types)
        sql += " ORDER BY priority DESC,created_at ASC LIMIT 1"
        row=c.execute(sql,args).fetchone()
        if not row: return {"task":None}
        changed=c.execute("UPDATE tasks SET status='claimed',assigned_agent=?,lease_until=?,updated_at=?,attempts=attempts+1 WHERE task_id=? AND (status='queued' OR lease_until<?)",(agent_id,now+lease,now,row['task_id'],now)).rowcount
        if not changed: return {"task":None}
        task=dict(row); task.update(status="claimed",assigned_agent=agent_id,lease_until=now+lease,attempts=task['attempts']+1,payload=json.loads(task['payload']))
        _event(c,agent_id,task['task_id'],"info","task.claimed","Agent claimed task",{"lease_seconds":lease},task['trace_id'],conversation_id=task.get('conversation_id'),bot_id=task.get('bot_id'))
        return {"task":task}

def finish_task(agent_id,token,task_id,payload):
    if not isinstance(payload,dict): raise ValueError("result must be an object")
    result=json.dumps(payload.get("result"),ensure_ascii=False)
    if len(result.encode("utf-8"))>512*1024: raise ValueError("task result exceeds 512KB")
    status=str(payload.get("status") or "completed")
    if status not in ("completed","failed"): raise ValueError("status must be completed or failed")
    now=time.time()
    with LOCK,_db() as c:
        if not _auth(c,agent_id,token): return False
        row=c.execute("SELECT trace_id,assigned_agent,status,conversation_id,bot_id FROM tasks WHERE task_id=?",(task_id,)).fetchone()
        if not row or row['assigned_agent']!=agent_id or row['status']!="claimed": return False
        c.execute("UPDATE tasks SET status=?,result=?,error=?,updated_at=?,lease_until=NULL WHERE task_id=?",(status,result,str(payload.get("error") or "")[:2000] or None,now,task_id))
        _event(c,agent_id,task_id,"info" if status=="completed" else "error","task."+status,"Agent reported task result",{"status":status},row['trace_id'],conversation_id=row['conversation_id'],bot_id=row['bot_id'])
    return True

def cancel_all_tasks(reason="Stopped by /swarm stop"):
    """Cancel every queued or claimed task. Returns how many were cancelled.

    Workers cannot claim a cancelled task, and finish_task() refuses to
    update one, so a worker that is still running cannot revive it.
    """
    now=time.time()
    with LOCK,_db() as c:
        ids=[r['task_id'] for r in c.execute("SELECT task_id FROM tasks WHERE status IN ('queued','claimed')").fetchall()]
        c.execute("UPDATE tasks SET status='cancelled',error=?,updated_at=?,lease_until=NULL WHERE status IN ('queued','claimed')",(reason,now))
        for tid in ids:
            row=c.execute("SELECT trace_id,assigned_agent,conversation_id,bot_id FROM tasks WHERE task_id=?",(tid,)).fetchone()
            _event(c,row['assigned_agent'],tid,"warn","swarm.cancelled","You stopped the swarm, so this bot stopped.",{"reason":reason},row['trace_id'],conversation_id=row['conversation_id'],bot_id=row['bot_id'])
    return len(ids)

def swarm_log(conversation_id, after=0):
    """Plain-language lines for one swarm chat, plus whether its task has finished."""
    conversation_id = str(conversation_id or '').strip()[:128]
    if not conversation_id: return {'lines': [], 'next': 0, 'done': True}
    after = max(0, int(after))
    with LOCK, _db() as c:
        rows = c.execute("SELECT seq,ts,kind,level,message FROM events WHERE conversation_id=? AND seq>? AND kind LIKE 'swarm.%' ORDER BY seq ASC LIMIT 200", (conversation_id, after)).fetchall()
        task = c.execute("SELECT status FROM tasks WHERE conversation_id=? ORDER BY created_at DESC LIMIT 1", (conversation_id,)).fetchone()
    lines = [dict(r) for r in rows]
    return {'lines': lines, 'next': lines[-1]['seq'] if lines else after,
            'done': (task is None) or task['status'] in ('completed', 'failed', 'cancelled')}

def task_snapshot(limit=100):
    with LOCK,_db() as c:
        rows=c.execute("SELECT task_id,created_at,updated_at,status,priority,task_type,assigned_agent,attempts,error,trace_id,conversation_id,bot_id FROM tasks ORDER BY created_at DESC LIMIT ?",(max(1,min(500,int(limit))),)).fetchall()
        counts={r['status']:r['n'] for r in c.execute("SELECT status,COUNT(*) n FROM tasks GROUP BY status").fetchall()}
        return {"tasks":[dict(r) for r in rows],"counts":counts}
