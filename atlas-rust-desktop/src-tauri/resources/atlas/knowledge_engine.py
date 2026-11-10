"""Atlas local knowledge indexing and retrieval. Embeddings are optional but preferred.
Uses llama-swap's OpenAI-compatible /v1/embeddings when embedding_model is configured;
otherwise uses deterministic lexical retrieval so the library remains useful offline.
"""
import hashlib, json, math, os, re, time, urllib.request
from collections import Counter
import upstream_auth

TOKEN_RE = re.compile(r"[\w.-]{2,}", re.UNICODE)
_FASTEMBED_CACHE = {}

def chunks(text, size=1800, overlap=220):
    text = str(text or "")
    if not text.strip(): return []
    out=[]; pos=0
    while pos < len(text):
        end=min(len(text), pos+size)
        if end < len(text):
            cut=max(text.rfind("\n", pos+size//2, end), text.rfind(". ", pos+size//2, end))
            if cut > pos: end=cut+1
        part=text[pos:end].strip()
        if part: out.append(part)
        if end >= len(text): break
        pos=max(pos+1, end-overlap)
    return out

def _tokens(text): return [x.lower() for x in TOKEN_RE.findall(str(text or ""))]
def _norm(v):
    n=math.sqrt(sum(float(x)*float(x) for x in v))
    return [float(x)/n for x in v] if n else []
def _cos(a,b): return sum(x*y for x,y in zip(a,b)) if a and b and len(a)==len(b) else 0.0

def embed(texts, host, port, model, timeout=90):
    if not model: return None
    if str(model).startswith("fastembed:"):
        model_name=str(model).split(":",1)[1] or "BAAI/bge-small-en-v1.5"
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("Install local embedding support with: py -3 -m pip install -r requirements-knowledge.txt") from exc
        encoder=_FASTEMBED_CACHE.get(model_name)
        if encoder is None:
            encoder=TextEmbedding(model_name=model_name)
            _FASTEMBED_CACHE[model_name]=encoder
        return [_norm(v.tolist() if hasattr(v,"tolist") else list(v)) for v in encoder.embed(texts)]
    payload=json.dumps({"model":model,"input":texts}).encode()
    req=urllib.request.Request(f"http://{host}:{port}/v1/embeddings", data=payload, headers=upstream_auth.headers({"Content-Type":"application/json"}))
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data=json.loads(response.read().decode())
    rows=sorted(data.get("data",[]), key=lambda x:x.get("index",0))
    if len(rows)!=len(texts): raise RuntimeError("Embedding endpoint returned an unexpected vector count")
    return [_norm(x.get("embedding",[])) for x in rows]

def build_records(items, distillations, read_source, host, port, embedding_model):
    records=[]
    for item in items:
        try: body=read_source(item["id"])
        except Exception: continue
        for n,part in enumerate(chunks(body)):
            records.append({"id":f"src:{item['id']}:{n}","kind":"source","source_id":item["id"],"title":item.get("name","Source"),"chunk":n,"text":part})
    for capsule in distillations:
        body=capsule.get("content","")
        for n,part in enumerate(chunks(body)):
            records.append({"id":f"distill:{capsule['id']}:{n}","kind":"distillation","distillation_id":capsule["id"],"source_ids":capsule.get("source_ids",[]),"title":capsule.get("title","Study capsule"),"chunk":n,"text":part})
    if embedding_model and records:
        vectors=[]
        for i in range(0,len(records),32):
            vectors.extend(embed([r["text"] for r in records[i:i+32]],host,port,embedding_model))
        for rec,vec in zip(records,vectors): rec["vector"]=vec
    return records

def search(records, query, host, port, embedding_model, limit=8):
    qtokens=Counter(_tokens(query)); scored=[]
    qvec=None
    if embedding_model and any(r.get("vector") for r in records):
        try: qvec=embed([query],host,port,embedding_model)[0]
        except Exception: qvec=None
    docs=[Counter(_tokens(r.get("text",""))) for r in records]
    df=Counter(t for doc in docs for t in doc)
    n=max(1,len(records))
    for rec,tf in zip(records,docs):
        lexical=0.0
        for term,count in qtokens.items():
            if count and tf.get(term): lexical += (1+math.log(tf[term]))*(math.log(1+(n-df[term]+0.5)/(df[term]+0.5)))
        semantic=_cos(qvec,rec.get("vector",[])) if qvec else 0.0
        score=(semantic*0.78)+(lexical*0.22/(1+lexical)) if qvec else lexical
        if score>0: scored.append((score,rec))
    scored.sort(key=lambda x:x[0],reverse=True)
    return [{k:v for k,v in r.items() if k!="vector"}|{"score":round(s,5)} for s,r in scored[:max(1,min(int(limit),30))]]

def graph_from_capsules(distillations):
    nodes={}; edges=[]
    for capsule in distillations:
        for concept in capsule.get("concepts",[]) if isinstance(capsule.get("concepts"),list) else []:
            if isinstance(concept,str): concept={"name":concept}
            if not isinstance(concept,dict) or not concept.get("name"): continue
            name=str(concept["name"]).strip()[:160]
            key=name.casefold(); nodes.setdefault(key,{"id":key,"name":name,"type":concept.get("type","concept"),"sources":[]})
            nodes[key]["sources"].extend(capsule.get("source_ids",[]))
        for edge in capsule.get("relationships",[]) if isinstance(capsule.get("relationships"),list) else []:
            if not isinstance(edge,dict): continue
            a=str(edge.get("from","")).strip(); b=str(edge.get("to","")).strip()
            if not a or not b: continue
            for name in (a,b): nodes.setdefault(name.casefold(),{"id":name.casefold(),"name":name,"type":"concept","sources":list(capsule.get("source_ids",[]))})
            edges.append({"from":a,"to":b,"relation":str(edge.get("relation","related to"))[:120],"source_ids":capsule.get("source_ids",[])})
    for node in nodes.values(): node["sources"]=sorted(set(node["sources"]))
    return {"nodes":list(nodes.values()),"edges":edges}
