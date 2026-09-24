"""S12 探针 v6：RAG 上传 422 根因 + refresh 401 + 限流 429 行为 + 会话 500 根因。"""
import json
import time
import uuid
import urllib.request
import urllib.error

WEB = "http://host.docker.internal:8080"


def SEEDPW():
    try:
        with open("/proj/deploy/.env") as f:
            for line in f:
                if line.startswith("SEED_ADMIN_PASSWORD="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "acme123"


PW = SEEDPW()


def req(method, path, tok=None, body=None, raw=None, ctype=None):
    h = {"Content-Type": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    if raw is not None:
        data = raw
        if ctype:
            h["Content-Type"] = ctype
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    r = urllib.request.Request(WEB + path, data=data, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jb(b):
    try:
        return json.loads(b)
    except Exception:
        return b.decode(errors="replace")


def mp(fields, fname, fbytes, ct="application/octet-stream"):
    boundary = f"----probe6{uuid.uuid4().hex}"
    b = b""
    for k, v in fields.items():
        b += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    b += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode()
    b += f"Content-Type: {ct}\r\n\r\n".encode()
    b += fbytes
    b += f"\r\n--{boundary}--\r\n".encode()
    return b, f"multipart/form-data; boundary={boundary}"


s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
TOK = jb(b).get("access_token")
print("login:", s, "ok" if TOK else "NO_TOKEN", b[:100] if not TOK else "")
if not TOK:
    raise SystemExit(1)

print("\n--- A. RAG 上传根因：逐个类型上传，打印 422 detail ---")
s, b = req("POST", "/api/rag/kbs", tok=TOK, body={"name": f"probe6-kb-{int(time.time())}", "embedding_model_id": None, "tag": "official"})
# 没有 embedding id 会 422；先查 embedding
s, b = req("GET", "/api/llm/embeddings", tok=TOK)
embs = (jb(b) or {}).get("items") or []
print("embeddings:", [(e.get("name"), e.get("id")) for e in embs][:5])
emb = embs[0]["id"] if embs else None
s, b = req("POST", "/api/rag/kbs", tok=TOK, body={"name": f"probe6-kb-{int(time.time())}", "embedding_model_id": emb})
d = jb(b)
KB = d.get("id") if isinstance(d, dict) else None
print("kb create:", s, str(b)[:120])
if not KB:
    raise SystemExit("no kb")

FIX = "/s12data/fixtures"
for fname, ct in [("refund_policy.txt", "text/plain"), ("policy.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                  ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ("report.pdf", "application/pdf"),
                  ("formula.png", "image/png"), ("scan.jpg", "image/jpeg")]:
    raw, ct2 = mp({}, fname, open(f"{FIX}/{fname}", "rb").read(), ct)
    s, b = req("POST", f"/api/rag/kbs/{KB}/docs", tok=TOK, raw=raw, ctype=ct2)
    print(f"upload {fname}: {s} {b[:150]}")

print("\n--- B. refresh token 端点/参数 ---")
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
d = jb(b)
t1, r1 = d.get("access_token"), d.get("refresh_token")
print("login2 keys:", sorted(d.keys()) if isinstance(d, dict) else d)
s, b = req("POST", "/api/auth/refresh", body={"refresh_token": r1})
print("refresh(POST json):", s, b[:120])
s, b = req("POST", "/api/auth/refresh", body=None, headers_=None) if False else req("POST", "/api/auth/refresh", raw=json.dumps({"refresh_token": r1}).encode(), ctype="application/json")
print("refresh(raw json):", s, b[:120])
# 可能 body 字段名不同
s, b = req("POST", "/api/auth/refresh", body={"token": r1})
print("refresh(token=):", s, b[:120])

print("\n--- C. 会话 500 根因 ---")
s, b = req("GET", "/api/agents", tok=TOK)
agents = (jb(b) or {}).get("items") or []
if agents:
    agid = agents[0]["id"]
    s, b = req("POST", "/api/chats", tok=TOK, body={"agent_id": agid, "title": "probe6 chat"})
    d = jb(b)
    cid = d.get("id") if isinstance(d, dict) else None
    print("create chat:", s, str(b)[:150])
    if cid:
        s, b = req("PUT", f"/api/chats/{cid}", tok=TOK, body={"title": "renamed"})
        print("rename chat:", s, str(b)[:200])
        s, b = req("DELETE", f"/api/chats/{cid}")
        print("delete chat (no body):", s, str(b)[:200])
print("DONE")
