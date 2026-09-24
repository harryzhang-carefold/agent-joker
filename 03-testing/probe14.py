"""S12 探针 v14：剩余未分类项定点验证（一次跑完，供 BUGS/REPORT 定稿）。
覆盖: MCP-03 referring / SKILL 上传422 / audit时间参数 / LLM update 400 /
upload-records时间参数 / 会话create+rename+delete / 限流429 / 用户roles读回 / role scopes 读回。"""
import json, time, uuid, urllib.request, urllib.error

WEB = "http://host.docker.internal:8080"
RUN = f"p14{int(time.time())%100000}"

def PW():
    try:
        for line in open("/proj/deploy/.env"):
            if line.startswith("SEED_ADMIN_PASSWORD="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "acme123"

def req(m, p, tok=None, body=None, raw=None, ct=None, timeout=60, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
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
print("login:", s, bool(TOK))
if not TOK:
    print("LOGIN FAIL", b[:200]); raise SystemExit(1)

# 重置限流高值（先跑业务，限流最后跑）
for _ in range(6):
    s, b = req("POST", "/api/bff/rate-limits", tok=TOK, body={"dimension": "user_qps", "limit_value": 1000})
    if s == 200:
        break
    time.sleep(1)

print("\n===== [A] BASE-02 role scopes 读回 =====")
s, b = req("POST", "/api/roles", tok=TOK, body={"name": f"p14role{RUN}", "scope_codes": ["rag:search", "storage:read"]})
rid = (jb(b) if isinstance(jb(b), dict) else {}).get("id")
print("create role:", s, "id=", rid, "body=", str(b)[:120])
s, b = req("GET", "/api/roles", tok=TOK)
items = (jb(b) or {}).get("items") or []
my = next((r for r in items if r.get("id") == rid), None)
print("list role scopes readback:", my.get("scopes") if my else "NOT FOUND")
# 改权限
s, b = req("PUT", f"/api/roles/{rid}", tok=TOK, body={"scope_codes": ["rag:search", "agents:manage"]})
print("update role:", s, str(b)[:80])
s, b = req("GET", "/api/roles", tok=TOK)
my2 = next((r for r in (jb(b) or {}).get("items") or [] if r.get("id") == rid), None)
print("after update scopes:", my2.get("scopes") if my2 else "NOT FOUND")
# 清场
req("DELETE", f"/api/roles/{rid}", tok=TOK)

print("\n===== [B] BASE-02 用户 roles 读回 =====")
s, b = req("POST", "/api/users", tok=TOK, body={"username": f"p14u{RUN}", "password": "Pass1234!", "tenant_code": "acme", "role_names": ["member"]})
uid = (jb(b) if isinstance(jb(b), dict) else {}).get("id")
print("create user:", s, "id=", uid, str(b)[:120])
s, b = req("PUT", f"/api/users/{uid}", tok=TOK, body={"role_names": ["admin", "member"]})
print("assign roles:", s, str(b)[:80])
s, b = req("GET", f"/api/users/{uid}", tok=TOK)
print("get user detail:", s, "roles field=", (jb(b) if isinstance(jb(b), dict) else {}).get("roles"), "keys=", list((jb(b) if isinstance(jb(b), dict) else {}).keys()))
req("DELETE", f"/api/users/{uid}", tok=TOK)

print("\n===== [C] AGENT-04 会话 create/rename/delete =====")
s, b = req("POST", "/api/agents", tok=TOK, body={"name": f"p14agent{RUN}", "type": "simple"})
aid = (jb(b) if isinstance(jb(b), dict) else {}).get("id")
print("create agent:", s, "id=", aid)
# 会话列表
s, b = req("GET", f"/api/agents/{aid}/sessions", tok=TOK)
print("list sessions:", s, "body=", str(b)[:150])
# 新建会话（看真实 status + 字段名）
s, b = req("POST", f"/api/agents/{aid}/sessions", tok=TOK, body={})
print("create session:", s, "body=", str(b)[:200])
d = jb(b) if isinstance(jb(b), dict) else {}
sid = d.get("session_id") or d.get("id")
print("  parsed sid=", sid)
if sid:
    s, b = req("PATCH", f"/api/agents/{aid}/sessions/{sid}", tok=TOK, body={"title": "p14t"})
    print("rename session:", s, str(b)[:150])
    s, b = req("DELETE", f"/api/agents/{aid}/sessions/{sid}", tok=TOK)
    print("delete session:", s, str(b)[:150])

print("\n===== [D] MCP-03 referring agents =====")
s, b = req("POST", "/api/mcp/servers", tok=TOK, body={"name": f"p14mcp{RUN}", "url": "http://joker-mock-mcp:9000/mcp", "transport": "streamable_http"})
mid = (jb(b) if isinstance(jb(b), dict) else {}).get("id")
print("create mcp server:", s, "id=", mid)
# 常见路径探测
for pth in (f"/api/mcp/servers/{mid}/referring-agents", f"/api/mcp/servers/{mid}/callers", f"/api/mcp/servers/{mid}/referencing", f"/api/mcp/servers/{mid}/refs"):
    s, b = req("GET", pth, tok=TOK)
    print(f"  GET {pth}: {s} {str(b)[:80]}")
if mid:
    req("DELETE", f"/api/mcp/servers/{mid}", tok=TOK)

print("\n===== [E] SKILL 上传 422 根因 =====")
s, b = req("POST", "/api/skills", tok=TOK, body={"name": f"p14skill{RUN}", "content": "# test\nhello", "category": "ops"})
sk = (jb(b) if isinstance(jb(b), dict) else {}).get("id")
print("create skill:", s, "id=", sk)
raw, c2 = mp(f"p14skill_{RUN}.md", b"# skill content\nhello\n", "text/markdown")
s, b = req("POST", f"/api/skills/{sk}/files", tok=TOK, raw=raw, ct=c2)
print("upload skill file:", s, "body=", str(b)[:200])
if sk:
    req("DELETE", f"/api/skills/{sk}", tok=TOK)

print("\n===== [F] audit 时间筛选 + upload-records 时间筛选 =====")
s, b = req("GET", "/api/audit/logs?start=2020-01-01T00:00:00Z&end=2020-01-02T00:00:00Z", tok=TOK)
d = jb(b) if isinstance(jb(b), dict) else {}
print("audit old-range:", s, "total=", d.get("total"), "body=", str(b)[:150])
s, b = req("GET", "/api/storage/upload-records?start=2020-01-01T00:00:00Z&end=2020-01-02T00:00:00Z", tok=TOK)
d = jb(b) if isinstance(jb(b), dict) else {}
print("upload-records old-range:", s, "total=", d.get("total"), "body=", str(b)[:150])

print("\n===== [G] LLM endpoint update 400 根因 =====")
s, b = req("POST", "/api/llm/endpoints", tok=TOK, body={"name": f"p14ep{RUN}", "base_url": "http://joker-mock-llm:9000/v1", "model": "mock", "api_key": "mock", "status": "active"})
ep = (jb(b) if isinstance(jb(b), dict) else {}).get("id")
print("create endpoint:", s, "id=", ep)
s, b = req("PUT", f"/api/llm/endpoints/{ep}", tok=TOK, body={"description": "p14 update"})
print("update endpoint (description only):", s, "body=", str(b)[:200])
if ep:
    req("DELETE", f"/api/llm/endpoints/{ep}", tok=TOK)

print("\n===== [H] 限流 429 复测（user_qps=10 后连发） =====")
for _ in range(6):
    s, b = req("POST", "/api/bff/rate-limits", tok=TOK, body={"dimension": "user_qps", "limit_value": 10})
    if s == 200:
        break
    time.sleep(1)
time.sleep(1.1)
codes = []
for i in range(16):
    s, b = req("GET", "/api/users?page=1", tok=TOK, timeout=10)
    codes.append(s)
print("16 rapid GETs codes:", codes, "| 429s=", codes.count(429))
# 复位
for _ in range(6):
    s, b = req("POST", "/api/bff/rate-limits", tok=TOK, body={"dimension": "user_qps", "limit_value": 1000})
    if s == 200:
        break
    time.sleep(1)
time.sleep(1.1)
s, b = req("GET", "/api/users?page=1", tok=TOK)
print("reset check:", s)

print("\n===== [I] TRACE-02 按会话检索 trace =====")
s, b = req("GET", f"/api/agents/{aid}/sessions", tok=TOK)
sess = (jb(b) or {}).get("items") or []
print("sessions now:", len(sess))
if sess:
    sid0 = sess[0].get("session_id") or sess[0].get("id")
    s, b = req("GET", f"/api/trace/events?session_id={sid0}", tok=TOK)
    d = jb(b) if isinstance(jb(b), dict) else {}
    print("trace by session:", s, "total=", d.get("total"), "keys=", list(d.keys()) if isinstance(d, dict) else type(d))

print("\n=== done RUN=", RUN, "===")
