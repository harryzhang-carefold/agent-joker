"""S12 探针 v10：RAG 级联终局验证 —— 全新 KB + 唯一文件名上传 6 类，验证下游 chunk/切分/检索/原文查看。
目的：区分 RAG-02 0/6 是产品 BUG 还是测试运行产物（429/文件名冲突）。"""
import json, time, uuid, urllib.request, urllib.error

WEB = "http://host.docker.internal:8080"
FIX = "/s12data/fixtures"
TAG = f"p10_{int(time.time())}"

def PW():
    try:
        for line in open("/proj/deploy/.env"):
            if line.startswith("SEED_ADMIN_PASSWORD="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "acme123"

def req(m, p, tok=None, body=None, raw=None, ct=None, timeout=90):
    h = {"Content-Type": "application/json"}
    d = None
    if body is not None:
        d = json.dumps(body).encode()
    if raw is not None:
        d = raw[0] if isinstance(raw, tuple) else raw
        h["Content-Type"] = raw[1] if isinstance(raw, tuple) else ct
    if tok:
        h["Authorization"] = f"Bearer {tok}"
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

def mp(fn, fbytes, ct):
    bnd = f"----x{uuid.uuid4().hex}"
    b = b""
    b += f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fn}\"\r\n".encode()
    b += f"Content-Type: {ct}\r\n\r\n".encode()
    b += fbytes
    b += f"\r\n--{bnd}--\r\n".encode()
    return b, f"multipart/form-data; boundary={bnd}"

s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW()})
TOK = jb(b).get("access_token")
print("login:", s, "tok?" , bool(TOK))
if not TOK:
    print("LOGIN FAILED:", b[:300]); raise SystemExit(1)

# 重置限流
for _ in range(6):
    s, b = req("POST", "/api/bff/rate-limits", tok=TOK, body={"dimension": "user_qps", "limit_value": 1000})
    if s == 200:
        break
    time.sleep(1.2)

# 建库
s, b = req("GET", "/api/llm/embeddings?status=active", tok=TOK)
items = (jb(b) or {}).get("items") or []
emb = next((e for e in items if e.get("provider") == "local"), None)
print("local emb:", emb and emb["id"], "dim=", emb and emb.get("dimensions"))
s, b = req("POST", "/api/rag/kbs", tok=TOK, body={"name": f"p10-kb-{TAG}", "embedding_model_id": emb["id"]})
d = jb(b)
KB = d.get("id")
print("create kb:", s, "kb=", KB)
if not KB:
    print("KB FAIL:", b[:300]); raise SystemExit(1)

six = [
    ("refund_policy.txt", "text/plain"),
    ("policy.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("report.pdf", "application/pdf"),
    ("formula.png", "image/png"),
    ("scan.jpg", "image/jpeg"),
]
doc_ids = {}
for fname, ct in six:
    stem, ext = fname.rsplit(".", 1)
    un = f"{stem}_{TAG}.{ext}"
    raw, c2 = mp(un, open(f"{FIX}/{fname}", "rb").read(), ct)
    t0 = time.time()
    s, b = req("POST", f"/api/rag/kbs/{KB}/docs", tok=TOK, raw=raw, ct=c2)
    dd = jb(b)
    did = dd.get("id") if isinstance(dd, dict) else None
    doc_ids[fname] = did
    print(f"  upload {fname} -> {s} ({time.time()-t0:.1f}s) id={did} body={str(b)[:120]}")
    time.sleep(0.4)

up_ok = sum(1 for v in doc_ids.values() if v)
print(f"uploaded={up_ok}/6")

# 等 txt 文档 ready
txt = doc_ids.get("refund_policy.txt")
st, dd = None, {}
for _ in range(60):
    s, b = req("GET", f"/api/rag/kbs/{KB}/docs/{txt}", tok=TOK)
    dd = jb(b) if isinstance(jb(b), dict) else {}
    st = dd.get("status")
    if st in ("ready", "failed"):
        break
    time.sleep(1.0)
print(f"\ntxt doc: status={st} chunk_count={dd.get('chunk_count')} parse={dd.get('parse_method')} err={dd.get('error') or dd.get('fail_reason')}")

# RAG-05 原文档查看（真实 doc_id）
s, b = req("GET", f"/api/rag/kbs/{KB}/docs/{txt}/file", tok=TOK)
print(f"\nRAG-05 view original file: code={s} bytes={len(b)} head={b[:60]!r}")

# RAG-04 定长切分（resplit）
s, b = req("POST", f"/api/rag/kbs/{KB}/docs/{txt}/resplit", tok=TOK,
           body={"split_strategy": "fixed", "split_params": {"chunk_size": 500, "overlap": 50}})
print(f"\nRAG-04 fixed resplit: code={s} body={str(b)[:150]}")

# 检索
def search_poll(query, use_rerank=False, tries=30):
    for _ in range(tries):
        s, b = req("POST", "/api/rag/search", tok=TOK,
                   body={"kb_ids": [KB], "query": query, "top_k": 3, "use_rerank": use_rerank})
        d = jb(b) if isinstance(jb(b), dict) else {}
        tot = d.get("total")
        if s == 200:
            return s, d
        time.sleep(1.0)
    return s, d

s, d = search_poll("订单签收后 7 天内可无理由退款")
items_s = d.get("items") or []
print(f"\nRAG-07 search(no rerank): code={s} total={d.get('total')} hits={len(items_s)} reranked={d.get('reranked')}")
if items_s:
    h0 = items_s[0]
    print("  hit0 keys:", list(h0.keys()))
    print("  hit0 pos/index/doc:", h0.get("position"), h0.get("chunk_index") or h0.get("index"), h0.get("doc_id") or h0.get("document_id"))

s, d = search_poll("退款", use_rerank=True)
print(f"RAG-07 search(rerank): code={s} total={d.get('total')} reranked={d.get('reranked')}")

# chunk 列表
s, b = req("GET", f"/api/rag/kbs/{KB}/docs/{txt}/chunks?page=1&page_size=50", tok=TOK)
d = jb(b) if isinstance(jb(b), dict) else {}
ci = d.get("items") or []
print(f"\nRAG-05 chunk list: code={s} count={len(ci)}")
if ci:
    print("  chunk0:", {k: ci[0].get(k) for k in ("index", "position", "content") if k in ci[0]}, "content_len=", len(ci[0].get("content") or ""))

print("\n=== TAG:", TAG, "kb=", KB, "=== done")
