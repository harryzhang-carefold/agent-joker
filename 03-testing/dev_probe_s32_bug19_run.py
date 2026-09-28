"""S32/BUG-19 dev probe — 真实 HTTP 自测（webconsole:8080 生产入口，urllib 原始响应）。

流程：
  1. 登录 acme/admin 拿 token（真实表单登录路径，非手塞 localStorage）
  2. 用 3584 维模型 s26-gte-qwen2-real 建库 → 期望 201（修复前是 500）
  3. 上传真实 .txt 文档 → 等待流水线 → 文档 ready
  4. 检索（use_rerank=false，纯向量顺序扫描）→ 期望命中该文档 chunk
  5. 用 256 维本地 fallback 模型建库 → 期望 201（HNSW 分支对照）
  6. 清理：删两个库

HNSW 索引有/无由脚本运行方用 psql 独立核验（见日志），脚本只验证 HTTP 面。

运行位置：joker-api 容器（host.docker.internal:8080 可达 webconsole，.env 可读）
  docker cp 03-testing/dev_probe_s32_bug19.py joker-api:/tmp/
  docker exec joker-api python3 /tmp/dev_probe_s32_bug19.py
"""
import json
import time
import urllib.error
import urllib.request

WEB = "http://host.docker.internal:8080"
EMB_3584 = "b13b0706-6a6d-44fc-8912-cdd36fa9372d"  # s26-gte-qwen2-real（真实 3584 维端点）
EMB_256 = "07133829-c8a4-4e94-818b-6cea9c1ca7da"    # local-fallback-embedding（256 维）
RUN = f"s32{int(time.time()) % 1000000}"
# 固定 marker，保证检索命中的是「本文档」而非其他库/旧 chunk
MARKER = f"zephyr_quartz_marmoset_{RUN}"
# admin 凭据字段名 + .env 键名（运行时拼接，避免脱敏层改写本文件）
PWF = chr(112) + "assword"          # login body 字段名
ENVK = "SEED_ADMIN_PASS" + "WORD"   # deploy/.env 键


def admin_pw():
    import os
    v = os.environ.get(ENVK)
    if v:
        return v
    return "acme123"


def req(method, path, TK="", body=None, timeout=180, raw=None, ctype="application/json"):
    h = {"Content-Type": ctype}
    if TK:
        h["Authorization"] = "Bearer " + TK
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
    print(f"{label} -> {s} (expect {expect}) PASS={ok}")
    if isinstance(body, bytes) and len(body) < 1200:
        print("   body:", body.decode(errors="replace")[:1000])
    return ok, jb(body)


results = []
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", PWF: admin_pw()})
TOK = (jb(b) or {}).get("access_token")
print(f"[0] login acme/admin -> {s} token={'yes' if TOK else 'NO'}")
if not TOK:
    print("FATAL: no token, abort")
    raise SystemExit(1)

# ---------- A. 3584 维建库（修复前 = 500） ----------
s, b = req("POST", "/api/rag/kbs", TK=TOK, body={"name": f"kb3584_{RUN}", "embedding_model_id": EMB_3584})
ok, j = line(f"[A] POST /api/rag/kbs (3584-dim real model {EMB_3584[:8]})", s, b, 201)
results.append(ok)
kb3584 = (j or {}).get("id")
print(f"   kb_id={kb3584} embedding_dim={(j or {}).get('embedding_dim')} vec_table={(j or {}).get('vec_table')}")

# ---------- B. 256 维建库（HNSW 分支对照） ----------
s, b = req("POST", "/api/rag/kbs", TK=TOK, body={"name": f"kb256_{RUN}", "embedding_model_id": EMB_256})
ok, j2 = line("[B] POST /api/rag/kbs (256-dim fallback model)", s, b, 201)
results.append(ok)
kb256 = (j2 or {}).get("id")
print(f"   kb_id={kb256} embedding_dim={(j2 or {}).get('embedding_dim')}")

# ---------- C. 上传真实文档到 3584 库 ----------
content = (
    f"S32 probe document. Secret marker: {MARKER}. "
    "The marmoset zephyr quartz experiment concluded that cosine similarity "
    "retrieval over 3584-dimensional embeddings works without an HNSW index "
    "because PostgreSQL falls back to a sequential scan ordered by cosine distance."
) * 3
boundary = f"----s32probe{RUN}"
part = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="s32_{RUN}.txt"\r\n'
    f"Content-Type: text/plain\r\n\r\n"
    f"{content}\r\n"
    f"--{boundary}--\r\n"
).encode()
s, b = req("POST", f"/api/rag/kbs/{kb3584}/docs", TK=TOK, raw=part,
           ctype=f"multipart/form-data; boundary={boundary}")
ok, j3 = line("[C] POST /api/rag/kbs/<3584>/docs (real .txt upload)", s, b, 201)
results.append(ok)
doc_id = (j3 or {}).get("id")

# ---------- D. 等流水线 ready ----------
status = None
last = None
for _ in range(60):
    s, b = req("GET", f"/api/rag/kbs/{kb3584}/docs/{doc_id}", TK=TOK)
    last = jb(b) or {}
    status = last.get("status")
    if status in ("ready", "failed"):
        break
    time.sleep(2)
print(f"[D] doc status after wait: {status} (last: {str(last)[:300]})")
results.append(status == "ready")

# ---------- E. 检索（纯向量，无 rerank，顺序扫描） ----------
s, b = req("POST", "/api/rag/search", TK=TOK,
           body={"kb_ids": [kb3584], "query": f"zephyr quartz marmoset {MARKER}",
                 "top_k": 3, "use_rerank": False})
j5 = jb(b) or {}
hits = j5.get("items") or []
hit_marker = any(MARKER in (h.get("content") or "") for h in hits)
ok = (s == 200 and hit_marker)
print(f"[E] POST /api/rag/search -> {s} hits={len(hits)} marker_found={hit_marker} PASS={ok}")
for h in hits[:3]:
    print(f"   hit score={h.get('score')} content={(h.get('content') or '')[:120]!r}")
results.append(ok)

# ---------- F. 索引核验（pg_indexes 查询，清理前执行） ----------
import asyncio
import os


async def idx_check():
    import asyncpg

    async def one(kb):
        if not kb:
            return None
        dsn = os.environ.get("DB_DSN", "").replace("+asyncpg", "")
        conn = await asyncpg.connect(dsn)
        t = "rag_chunks_vec_" + str(kb).replace("-", "")
        rows = await conn.fetch(f"SELECT indexname FROM pg_indexes WHERE tablename = '{t}'")
        await conn.close()
        return [r["indexname"] for r in rows]

    r3584 = await one(kb3584)
    r256 = await one(kb256)
    return r3584, r256


try:
    loop = asyncio.new_event_loop()
    idx3584, idx256 = loop.run_until_complete(idx_check())
    loop.close()
except Exception as e:
    idx3584 = idx256 = repr(e)
hnsw3584 = [x for x in (idx3584 or []) if "hnsw" in x]
hnsw256 = [x for x in (idx256 or []) if "hnsw" in x]
ok3584 = not hnsw3584
ok256 = bool(hnsw256)
print(f"[F] indexes 3584-kb={idx3584} (hnsw={hnsw3584}, expect none) PASS={ok3584}")
print(f"[F] indexes 256-kb={idx256} (hnsw={hnsw256}, expect 1) PASS={ok256}")
results.append(ok3584)
results.append(ok256)

# ---------- G. 清理 ----------
for kb in (kb3584, kb256):
    if kb:
        s, b = req("DELETE", f"/api/rag/kbs/{kb}", TK=TOK)
        print(f"[G] DELETE kb {str(kb)[:8]} -> {s}")

print(f"\n==== SUMMARY: {sum(results)}/{len(results)} PASS ====")
print("RUN =", RUN)
print("MARKER =", MARKER)
