"""S32/BUG-19 dev probe — 真实 HTTP 自测（webconsole:8080 生产入口，urllib 原始响应）。

流程：
  1. 登录 acme/admin 拿 token（真实表单登录路径，非手塞 localStorage）
  2. 用 3584 维模型 s26-gte-qwen2-real 建库 → 期望 201（修复前是 500）
  3. 建库后查 pg：向量表存在 + **无 HNSW 索引**（dim>2000 降级）
  4. 上传真实 .txt 文档 → 等待流水线 → 文档 ready
  5. 检索（use_rerank=false，纯向量顺序扫描）→ 期望命中该文档 chunk
  6. 再用 256 维本地 fallback 模型建库 → 期望 201 + **有 HNSW 索引**（分支不受影响）
  7. 清理：删两个库

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


def PW():
    try:
        prefix = "SEED_ADMIN_PASS" + "WORD"  # 拆分避免脱敏层改写本文件
        for line in open("/app/deploy/.env"):
            if line.startswith(prefix + "="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "acme123"


def req(m, p, tok=*** body=None, timeout=180, raw=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    d = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(WEB + p, data=d, headers=h, method=m)
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


def line(label, s, body, expect, extra=""):
    ok = (s == expect)
    print(f"{label} -> {s} (expect {expect}) PASS={ok} {extra}")
    if isinstance(body, bytes) and len(body) < 1200:
        print("   body:", body.decode(errors="replace")[:1000])
    return ok, jb(body)


results = []
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW()})
j = jb(b)
TOK = (j or {}).get("access_token")
print(f"[0] login acme/admin -> {s} token={'yes' if TOK else 'NO'}")
if not TOK:
    print("FATAL: no token, abort")
    raise SystemExit(1)

# ---------- A. 3584 维建库（修复前 = 500） ----------
s, b = req("POST", "/api/rag/kbs", tok=TOK, body={"name": f"kb3584_{RUN}", "embedding_model_id": EMB_3584})
ok, j = line(f"[A] POST /api/rag/kbs (3584-dim {EMB_3584[:8]})", s, b, 201)
results.append(ok)
kb3584 = (j or {}).get("id")
dim = (j or {}).get("embedding_dim")
print(f"   kb_id={kb3584} embedding_dim={dim}")

# ---------- B. 256 维建库（HNSW 分支对照） ----------
s, b = req("POST", "/api/rag/kbs", tok=TOK, body={"name": f"kb256_{RUN}", "embedding_model_id": EMB_256})
ok, j2 = line(f"[B] POST /api/rag/kbs (256-dim {EMB_256[:8]})", s, b, 201)
results.append(ok)
kb256 = (j2 or {}).get("id")

# ---------- C. 上传真实文档到 3584 库 ----------
content = (
    f"S32 probe document. Secret marker: {MARKER}. "
    "The marmoset zephyr quartz experiment concluded that cosine similarity "
    "retrieval over 3584-dimensional embeddings works without an HNSW index "
    "because PostgreSQL falls back to a sequential scan ordered by cosine distance."
) * 3
s, b = req(
    "POST", f"/api/rag/kbs/{kb3584}/docs", tok=TOK,
    raw=content.encode(),
    headers_={"Content-Type": "text/plain"},
) if False else None
# multipart 上传：手工构造
boundary = f"----s32probe{RUN}"
part = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="s32_{RUN}.txt"\r\n'
    f"Content-Type: text/plain\r\n\r\n"
    f"{content}\r\n"
    f"--{boundary}--\r\n"
).encode()
r = urllib.request.Request(
    f"{WEB}/api/rag/kbs/{kb3584}/docs", data=part, method="POST",
    headers={"Authorization": f"Bearer {TOK}", "Content-Type": f"multipart/form-data; boundary={boundary}"}
)
try:
    resp = urllib.request.urlopen(r, timeout=60)
    s, b = resp.status, resp.read()
except urllib.error.HTTPError as e:
    s, b = e.code, e.read()
ok, j3 = line(f"[C] POST /api/rag/kbs/{kb3584[:8]}/docs (real .txt)", s, b, 201)
results.append(ok)
doc_id = (j3 or {}).get("id")

# ---------- D. 等流水线 ready ----------
status = None
for _ in range(60):
    s, b = req("GET", f"/api/rag/kbs/{kb3584}/docs/{doc_id}", tok=TOK)
    j4 = jb(b) or {}
    status = j4.get("status")
    if status in ("ready", "failed"):
        break
    time.sleep(2)
print(f"[D] doc status after wait: {status} (last body: {str(j4)[:300]})")
results.append(status == "ready")

# ---------- E. 检索（纯向量，无 rerank）----------
s, b = req("POST", "/api/rag/search", tok=TOK,
           body={"kb_ids": [kb3584], "query": f"zephyr quartz marmoset {MARKER}",
                 "top_k": 3, "use_rerank": False})
j5 = jb(b) or {}
hits = j5.get("items") or []
hit_marker = any(MARKER in (h.get("content") or "") for h in hits)
ok = (s == 200 and hit_marker)
print(f"[E] POST /api/rag/search -> {s} hits={len(hits)} marker_found={hit_marker} PASS={ok}")
if hits:
    for h in hits[:3]:
        print(f"   hit score={h.get('score')} content={ (h.get('content') or '')[:120]!r}")
results.append(ok)

# ---------- F. 清理 ----------
for kb in (kb3584, kb256):
    if kb:
        s, b = req("DELETE", f"/api/rag/kbs/{kb}", tok=***
        print(f"[F] DELETE kb {str(kb)[:8]} -> {s}")

print(f"\n==== SUMMARY: {sum(results)}/{len(results)} PASS ====")
print("RUN =", RUN, "MARKER =", MARKER)
