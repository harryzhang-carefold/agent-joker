"""S12 探针 v11：RAG 检索 0 命中根因 —— 已确认 chunk 存在且 ready，测试不同阈值/查询。"""
import json, time, urllib.request, urllib.error

WEB = "http://host.docker.internal:8080"
TAG = "p10_1790167567"  # probe10 建的库
KB = "2faa954d-2426-470e-b718-7c63cfa6de8b"
TXT = "a15dc09b-c0e3-4732-884f-f4ea28956677"

def PW():
    try:
        for line in open("/proj/deploy/.env"):
            if line.startswith("SEED_ADMIN_PASSWORD="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "acme123"

def req(m, p, tok=None, body=None, timeout=60):
    h = {"Content-Type": "application/json"}
    d = json.dumps(body).encode() if body is not None else None
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

s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW()})
TOK = jb(b).get("access_token")
print("login:", s, bool(TOK))

# 看 KB 默认检索配置
s, b = req("GET", f"/api/rag/kbs/{KB}", tok=TOK)
d = jb(b) if isinstance(jb(b), dict) else {}
print("\nKB config:", {k: d.get(k) for k in ("search_threshold", "default_top_k", "top_k", "threshold", "min_score", "similarity_threshold") if k in d})
print("  full keys:", list(d.keys()))

# 文档 chunk 数确认
s, b = req("GET", f"/api/rag/kbs/{KB}/docs/{TXT}", tok=TOK)
dd = jb(b) if isinstance(jb(b), dict) else {}
print("\ndoc status:", dd.get("status"), "chunk_count:", dd.get("chunk_count"))

queries = [
    "退款",
    "订单签收后 7 天内可无理由退款",
    "本公司售后服务与退款政策总则",
    "退款金额将原路返回支付账户",
]
print("\n--- 默认阈值检索 ---")
for q in queries:
    s, b = req("POST", "/api/rag/search", tok=TOK, body={"kb_ids": [KB], "query": q, "top_k": 5, "use_rerank": False})
    d = jb(b) if isinstance(jb(b), dict) else {}
    print(f"  q={q[:24]:24} code={s} total={d.get('total')} items={len(d.get('items') or [])} keys={list(d.keys()) if isinstance(d,dict) else type(d)}")

print("\n--- 显式低阈值 (0.0 / 0.1) ---")
for th in (0.0, 0.05, 0.1, 0.3):
    s, b = req("POST", "/api/rag/search", tok=TOK, body={"kb_ids": [KB], "query": "退款", "top_k": 5, "threshold": th, "use_rerank": False})
    d = jb(b) if isinstance(jb(b), dict) else {}
    items = d.get("items") or []
    scores = [it.get("score") or it.get("similarity") or it.get("score") for it in items]
    print(f"  threshold={th} code={s} total={d.get('total')} items={len(items)} scores={scores}")
    if items and s == 200 and th == 0.0:
        print("    item0:", {k: items[0].get(k) for k in list(items[0].keys())[:12]})
