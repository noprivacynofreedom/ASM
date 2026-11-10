"""Atlas Swarm worker SDK: authenticated registration, task polling and result reporting.
Agents provide an execute(task) callback; this module owns only its own HTTP loop.
"""
from __future__ import annotations
import json, platform, socket, threading, time, urllib.error, urllib.request, uuid

class AtlasAgent:
    def __init__(self, base_url: str, name: str, execute, model: str = "", metadata=None,
                 poll_interval: float = 2.0, heartbeat_interval: float = 10.0,
                 accepted_task_types=None):
        self.base_url=base_url.rstrip("/"); self.name=name; self.execute=execute
        self.model=model; self.metadata=metadata or {}; self.poll_interval=max(.5,float(poll_interval))
        self.heartbeat_interval=max(3.0,float(heartbeat_interval)); self.agent_id=None; self.token=None
        if accepted_task_types is not None and (not isinstance(accepted_task_types,list) or not accepted_task_types or any(not isinstance(x,str) or not x.strip() or len(x)>80 for x in accepted_task_types)):
            raise ValueError("accepted_task_types must be a non-empty list of strings (1-80 characters)")
        self.accepted_task_types=list(dict.fromkeys(x.strip() for x in accepted_task_types)) if accepted_task_types is not None else None
        self._stop=threading.Event(); self._thread=None; self._last_heartbeat=0.0
    def _request(self,path,payload=None,auth=False):
        data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
        headers={"Content-Type":"application/json"}
        if auth and self.token: headers["Authorization"]="Bearer "+self.token
        req=urllib.request.Request(self.base_url+path,data=data,headers=headers,method="GET" if payload is None else "POST")
        with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read().decode("utf-8"))
    def register(self):
        result=self._request("/api/ops/agents/register",{"name":self.name,"host":socket.gethostname(),"platform":platform.platform(),"pid":__import__('os').getpid(),"model":self.model,"metadata":self.metadata})
        self.agent_id=result["agent_id"]; self.token=result["token"]; return result
    def heartbeat(self,status="online",task_id=None,stage=None):
        if not self.agent_id: raise RuntimeError("Agent is not registered")
        return self._request(f"/api/ops/agents/{self.agent_id}/heartbeat",{"status":status,"task_id":task_id,"task_stage":stage,"metrics":{}},True)
    def event(self,kind,message,details=None,task_id=None,level="info",trace_id=None):
        return self._request(f"/api/ops/agents/{self.agent_id}/events",{"kind":kind,"message":message,"details":details or {},"task_id":task_id,"level":level,"trace_id":trace_id},True)
    def _run(self):
        while not self._stop.is_set():
            try:
                now=time.monotonic()
                if now-self._last_heartbeat>=self.heartbeat_interval:
                    self.heartbeat(); self._last_heartbeat=now
                claim_payload={"lease_seconds":120}
                if self.accepted_task_types is not None:
                    claim_payload["task_types"]=self.accepted_task_types
                claimed=self._request(f"/api/ops/agents/{self.agent_id}/tasks/claim",claim_payload,True)
                task=claimed.get("task")
                if not task: self._stop.wait(self.poll_interval); continue
                tid=task["task_id"]
                trace_id=task.get("trace_id")
                try:
                    self.heartbeat("busy",tid,"executing")
                    result=self.execute(task)
                    body={"status":"completed","result":result if isinstance(result,dict) else {"value":result}}
                except Exception as exc:
                    body={"status":"failed","error":f"{type(exc).__name__}: {exc}","result":{}}
                body["trace_id"] = trace_id
                self._request(f"/api/ops/agents/{self.agent_id}/tasks/{tid}/result",body,True)
                self.heartbeat("online")
            except Exception as exc:
                try: self.event("agent.worker_error",str(exc),level="error")
                except Exception: pass
                self._stop.wait(min(10,self.poll_interval*2))
    def start(self):
        if self._thread and self._thread.is_alive(): return self
        if not self.agent_id: self.register()
        self._stop.clear(); self._thread=threading.Thread(target=self._run,name=f"atlas-agent-{self.name}",daemon=True); self._thread.start(); return self
    def stop(self,timeout=5):
        self._stop.set()
        if self._thread: self._thread.join(timeout)
        try: self.heartbeat("offline")
        except Exception: pass
