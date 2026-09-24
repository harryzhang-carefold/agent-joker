"""S12 探针 v7：按 API_NOTES 正确端点复核 harness 误报 + 定位真 bug。"""
import json
import time
import urllib.request
import urllib.error

WEB = "http://host.docker.internal:8080"
BFF = "http://host.docker.internal:8000"


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


def req(method, url, tok=None, body=None, raw=None, ctype=None):
    h = {"Content-Type": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    if raw is not None:
        data = raw
        h["Content-Type"] = ctype or "application/octet-stream"
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
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


s, b = req("POST", WEB + "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
TOK = jb(b).get("access_token")
print("login:", s, "ok" if TOK else b[:150])
if not TOK:
    raise SystemExit(1)

print("\n--- A. refresh（经 webconsole 8080，正确端点） ---")
s, b = req("POST", WEB + "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
d = jb(b)
t1, r1 = d["access_token"], d["refresh_token"]
s, b = req("POST", WEB + "/api/auth/refresh", body={"refresh_token": r1})
d2 = jb(b)
print("refresh:", s, "new_token" if isinstance(d2, dict) and d2.get("access_token") else str(b)[:150])
if isinstance(d2, dict) and d2.get("access_token"):
    print("  → 旧 refresh 重放应 401:")
    s, b = req("POST", WEB + "/api/auth/refresh", body={"refresh_token": r1})
    print("  replay:", s, str(b)[:80])

print("\n--- B. 会话（正确路径 /api/agents/{id}/sessions） ---")
s, b = req("GET", WEB + "/api/agents", tok=TOK)
agents = (jb(b) or {}).get("items") or []
print("agents:", [(a.get("name"), a.get("id")[:8]) for a in agents][:3])
if agents:
    agid = agents[0]["id"]
    # 发起一轮对话产生会话
    s, b = req("POST", WEB + f"/api/agents/{agid}/sessions", tok=TOK, body={"title": "probe7 chat"})
    d = jb(b)
    print("create session (POST):", s, str(b)[:120])
    sid = d.get("id") if isinstance(d, dict) else None
    if not sid:
        # 可能自动创建，直接列
        pass
    s, b = req("GET", WEB + f"/api/agents/{agid}/sessions", tok=TOK)
    sess = (jb(b) or {}).get("items") or []
    print("sessions:", len(sess), [(x.get("title"), x.get("id")[:8]) for x in sess][:3])
    if sess:
        cid = sess[0]["id"]
        s, b = req("PUT", WEB + f"/api/agents/{agid}/sessions/{cid}", tok=TOK, body={"title": "renamed-p7"})
        print("rename session:", s, str(b)[:120])
        s, b = req("DELETE", WEB + f"/api/agents/{agid}/sessions/{cid}")
        print("delete session:", s, str(b)[:120])

print("\n--- C. audit 时间筛选（path/from/to 参数） ---")
s, b = req("GET", WEB + "/api/audit/logs?page=1&page_size=5", tok=TOK)
d = jb(b)
print("audit sample keys:", sorted((d.get("items") or [{}])[0].keys()) if d.get("items") else d)
s, b = req("GET", WEB + "/api/audit/logs?from=2020-01-01T00:00:00Z&to=2020-12-31T00:00:00Z", tok=TOK)
d = jb(b)
print("audit from/to 2020 total:", d.get("total") if isinstance(d, dict) else str(b)[:80])
s, b = req("GET", WEB + "/api/audit/logs?path=/api/auth/logout", tok=TOK)
d = jb(b)
print("audit path=/api/auth/logout total:", d.get("total") if isinstance(d, dict) else str(b)[:80])
print("  logout sample:", str(((d.get("items") or [None])[0]))[:150] if d.get("items") else "none")

print("\n--- D. upload-records start/end ISO8601 ---")
s, b = req("GET", WEB + "/api/storage/upload-records?start=2020-01-01T00:00:00Z&end=2021-01-01T00:00:00Z", tok=TOK)
d = jb(b)
print("upload-records 2020 total:", d.get("total") if isinstance(d, dict) else str(b)[:80])
s, b = req("GET", WEB + "/api/storage/upload-records?source=kb", tok=TOK)
d = jb(b)
print("upload-records source=kb total:", d.get("total") if isinstance(d, dict) else str(b)[:80])

print("\n--- E. BASE-05：登出后 access token 经 webconsole 是否失效 ---")
s, b = req("POST", WEB + "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
d = jb(b)
t2 = d["access_token"]
s, b = req("GET", WEB + "/api/users?page=1", tok=t2)
print("pre-logout:", s)
s, b = req("POST", WEB + "/api/auth/logout", tok=t2, body={"refresh_token": d["refresh_token"]})
print("logout:", s, str(b)[:60])
time.sleep(1.0)
s, b = req("GET", WEB + "/api/users?page=1", tok=t2)
print("post-logout same token:", s, "(401=OK, 200=BUG)")

print("\n--- F. roles scopes 字段名 ---")
s, b = req("POST", WEB + "/api/roles", tok=TOK, body={"name": "probe7-r1", "scope_names": ["rag:search"]})
d = jb(b)
print("create role:", s, str(b)[:150])
rid = d.get("id") if isinstance(d, dict) else None
s, b = req("GET", WEB + "/api/roles", tok=TOK)
r0 = next((x for x in (jb(b) or {}).get("items") or [] if x.get("id") == rid), None)
print("role readback:", json.dumps(r0, ensure_ascii=False)[:250] if r0 else "NOT FOUND")
if r0:
    s, b = req("PUT", WEB + f"/api/roles/{rid}", tok=TOK, body={"scope_names": ["rag:search", "storage:read"]})
    print("PUT scopes:", s)
    s, b = req("GET", WEB + "/api/roles", tok=TOK)
    r1 = next((x for x in (jb(b) or {}).get("items") or [] if x.get("id") == rid), None)
    print("role after PUT:", json.dumps(r1, ensure_ascii=False)[:250] if r1 else "NOT FOUND")
    s, b = req("DELETE", WEB + f"/api/roles/{rid}", tok=TOK)
    print("delete role:", s)
print("DONE")
