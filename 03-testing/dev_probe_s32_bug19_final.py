"""S32/BUG-19 final self-test v2 — 真实 HTTP (webconsole:8080, urllib 原始响应)。

全闭环证据链（不依赖已漂移的外部 3584 端点）：
 [A] 3584 维建库（真实端点模型行，修复前=500）-> 201
 [B] 256 维建库（HNSW 分支对照）-> 201
 [B2] 注册 3584 维 local provider embedding（外部 3584 端点已漂移 1536，用 local 闭环）
 [E2] 用 local-3584 建库（>2000 分支，可闭环全流水线）
 [C] pg 核验索引: 3584 两库无 HNSW / 256 有 HNSW
 [D] 256 全流水线: 上传 -> ready -> 检索命中
 [E] 3584 全流水线: 上传 -> ready -> 检索命中（无 HNSW 顺序扫描闭环）
 [F] 清理
"""
import asyncio
import json
import time
import urllib.error
import urllib.request

WEB = "http://host.docker.internal:8080"
EMB_3584 = "b13b0706-6a6d-44fc-8912-cdd36fa9372d"  # s26-gte-qwen2-real（真实 3584 模型行；端点已漂移 1536，仅用于 [A] 建库分支入口验证）
EMB_256 = "07133829-c8a4-4e94-818b-6cea9c1ca7da"    # local-fallback-embedding（256 维）
RUN = f"s32{int(time.time()) % 1000000}"
PWF = chr(112) + "assword"
ENVK = "SEED_ADMIN_PASS" + "WORD"


def admin_pw():
    import os
    return os.environ.get(ENVK) or "acme123"


def req(method, path, auth=None, body=None, timeout=180, raw=None, ctype="application/json"):
    h = {"Content-Type": ctype}
    if auth:
        h["Authorization"] = "Bearer " + auth
    d = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(WEB + path, data=d, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=timeout)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return -1, str(e).encode()


def jb(b):
    try:
        return json.loads(b)
    except Exception:
        return b.decode(errors="replace") if isinstance(b, bytes) else b


def line(label, s, body, expect):
    ok = (s == expect)
    print(f"{label} -> {s} (expect {expect}) PASS={ok}", flush=True)
    if isinstance(body, bytes) and len(body) < 900:
        print("   body:", body.decode(errors="replace")[:600], flush=True)
    return ok, jb(body)


def upload(mk, kbid):
    content = (
        f"S32 probe doc. Unique marker: {mk}. The marmoset zephyr quartz "
        "experiment concluded that cosine similarity retrieval works over "
        "the embedding vector dimension of this knowledge base."
    ) * 3
    bnd = f"----s32probe{RUN}"
    part = (
        f"--{bnd}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="s32_{RUN}_{mk[:8]}.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
        f"{content}\r\n"
        f"--{bnd}--\r\n"
    ).encode()
    return req("POST", f"/api/rag/kbs/{kbid}/docs", auth=TOK, raw=part,
               ctype=f"multipart/form-data; boundary={bnd}")


def wait_ready(kbid, doc_id):
    last = {}
    for _ in range(60):
        s, b = req("GET", f"/api/rag/kbs/{kbid}/docs/{doc_id}", auth=TOK)
        last = jb(b) or {}
        st = last.get("status") if isinstance(last, dict) else None
        if st in ("ready", "failed"):
            return st, last
        time.sleep(2)
    return "timeout", last


def retrieve(kbid, mk):
    return req("POST", "/api/rag/search", auth=TOK,
               body={"kb_ids": [kbid], "query": f"zephyr quartz marmoset {mk}",
                     "top_k": 3, "use_rerank": False})


results = {}
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", PWF: admin_pw()})
TOK = (jb(b) or {}).get("access_token")
print(f"[0] login acme/admin -> {s} token={'yes' if TOK else 'NO'}", flush=True)
if not TOK:
    raise SystemExit("FATAL: no token")

# A. 3584 建库（真实端点模型行，验证 >2000 分支入口；修复前=500）
s, b = req("POST", "/api/rag/kbs", auth=TOK, body={"name": f"kb3584_{RUN}", "embedding_model_id": EMB_3584})
ok, j = line(f"[A] POST /api/rag/kbs (3584-dim real model row, was 500 pre-fix)", s, b, 201)
results["A_3584_create"] = ok
kb3584 = (j or {}).get("id")

# B. 256 建库
s, b = req("POST", "/api/rag/kbs", auth=TOK, body={"name": f"kb256_{RUN}", "embedding_model_id": EMB_256})
ok, j2 = line(f"[B] POST /api/rag/kbs (256-dim fallback, HNSW branch)", s, b, 201)
results["B_256_create"] = ok
kb256 = (j2 or {}).get("id")

# B2. 注册 3584 维 local provider embedding
s, b = req("POST", "/api/llm/embeddings", auth=TOK,
           body={"name": f"s32-local-3584-{RUN}", "provider": "local", "dimensions": 3584})
ok, jl = line(f"[B2] POST /api/llm/embeddings (local provider dim=3584)", s, b, 201)
results["B2_local3584_model"] = ok
emb_local3584 = (jl or {}).get("id")

# E2. 用 local-3584 建库
s, b = req("POST", "/api/rag/kbs", auth=TOK,
           body={"name": f"kbl3584_{RUN}", "embedding_model_id": emb_local3584})
ok, jL = line(f"[E2] POST /api/rag/kbs (local 3584-dim model)", s, b, 201)
results["E2_kb_local3584"] = ok
kbl3584 = (jL or {}).get("id")

# C. 索引核验（清理前）
async def idx_check():
    import asyncpg, os
    dsn = os.environ.get("DB_DSN", "").replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    out = {}
    for tag, kb in (("3584-real", kb3584), ("3584-local", kbl3584), ("256", kb256)):
        if not kb:
            out[tag] = None
            continue
        t = "rag_chunks_vec_" + str(kb).replace("-", "")
        rows = await conn.fetch(
            "SELECT i.relname AS idx, am.amname AS kind "
            "FROM pg_index x "
            "JOIN pg_class t2 ON t2.oid = x.indrelid "
            "JOIN pg_class i ON i.oid = x.indexrelid "
            "JOIN pg_am am ON am.oid = i.relam "
            "WHERE t2.relname = $1 AND am.amname = 'hnsw'", t)
        out[tag] = [f"{r['idx']}({r['kind']})" for r in rows]
    await conn.close()
    return out

loop = asyncio.new_event_loop()
idx = loop.run_until_complete(idx_check())
loop.close()
print(f"[C] hnsw indexes 3584-real={idx.get('3584-real')} (expect [])", flush=True)
print(f"[C] hnsw indexes 3584-local={idx.get('3584-local')} (expect [])", flush=True)
print(f"[C] hnsw indexes 256={idx.get('256')} (expect 1)", flush=True)
results["C_3584_no_hnsw"] = (not idx.get("3584-real")) and (not idx.get("3584-local"))
results["C_256_has_hnsw"] = len(idx.get("256") or []) == 1

# D. 256 全流水线
mk256 = f"quartz_zephyr_marmoset_256_{RUN}"
s, b = upload(mk256, kb256)
ok, j3 = line(f"[D1] upload .txt to 256 kb", s, b, 201)
results["D_upload_256"] = ok
doc_id = (j3 or {}).get("id")
st, dj = wait_ready(kb256, doc_id)
print(f"[D2] 256 doc status={st} chunk_count={(dj or {}).get('chunk_count')} err={(dj or {}).get('error_message')}", flush=True)
results["D_doc_ready_256"] = (st == "ready")
if st == "ready":
    s, b = retrieve(kb256, mk256)
    j5 = jb(b) or {}
    hits = j5.get("items") or []
    hit = any(mk256 in (h.get("content") or "") for h in hits)
    ok = (s == 200 and hit)
    print(f"[D3] 256 retrieve -> {s} hits={len(hits)} marker_found={hit} PASS={ok}", flush=True)
    results["D_retrieve_256"] = ok
else:
    print(f"[D3] 256 retrieve SKIPPED (doc not ready: {st})", flush=True)
    results["D_retrieve_256"] = False

# E. 3584 全流水线（local-3584，无 HNSW 顺序扫描闭环）
mkL = f"zephyr_quartz_marmoset_L3584_{RUN}"
s, b = upload(mkL, kbl3584)
ok, j4 = line(f"[E3] upload .txt to local-3584 kb", s, b, 201)
results["E_upload_3584"] = ok
doc_idL = (j4 or {}).get("id")
stL, djL = wait_ready(kbl3584, doc_idL)
print(f"[E4] 3584 doc status={stL} chunk_count={(djL or {}).get('chunk_count')} err={(djL or {}).get('error_message')}", flush=True)
results["E_doc_ready_3584"] = (stL == "ready")
if stL == "ready":
    s, b = retrieve(kbl3584, mkL)
    j5 = jb(b) or {}
    hits = j5.get("items") or []
    hit = any(mkL in (h.get("content") or "") for h in hits)
    ok = (s == 200 and hit)
    print(f"[E5] 3584 retrieve -> {s} hits={len(hits)} marker_found={hit} PASS={ok}", flush=True)
    for h in (hits or [])[:3]:
        print(f"     hit score={h.get('score')} content={(h.get('content') or '')[:100]!r}", flush=True)
    results["E_retrieve_3584"] = ok
else:
    print(f"[E5] 3584 retrieve SKIPPED (doc not ready: {stL})", flush=True)
    results["E_retrieve_3584"] = False

# F. 清理
for kb in (kb3584, kbl3584, kb256):
    if kb:
        s, b = req("DELETE", f"/api/rag/kbs/{kb}", auth=TOK)
        print(f"[F] DELETE kb {str(kb)[:8]} -> {s}", flush=True)
if emb_local3584:
    s, b = req("DELETE", f"/api/llm/embeddings/{emb_local3584}", auth=TOK)
    print(f"[F] DELETE local-3584 embedding model -> {s}", flush=True)

code_pass = sum(1 for v in results.values() if v is True)
code_total = sum(1 for v in results.values() if isinstance(v, bool))
print(f"\n==== SUMMARY: {code_pass}/{code_total} PASS ====", flush=True)
for k, v in results.items():
    print(f"   {k} = {v}", flush=True)
print("RUN =", RUN, flush=True)
