"""S12 探针 v15：BASE-02 role scope 绑定 + AGENT-07 多轮记忆 终局验证。"""
import json, time, uuid, urllib.request, urllib.error

WEB = "http://host.docker.internal:8080"
RUN = f"p15{int(time.time())%100000}"

def PW():
    try:
        for line in open("/proj/deploy/.env"):
            if line.startswith("SEED_ADMIN_PASSWORD="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "acme123"

def req(m, p, tok=None, body=None, timeout=60, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
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

print("\n===== [A] 已存在的平台/租户 scope 列表 =====")
s, b = req("GET", "/api/scopes", tok=TOK)
items = (jb(b) or {}).get("items") or []
print("scopes count:", len(items), "| codes:", [x.get("code") for x in items][:40])

print("\n===== [B] 用真实存在的 scope code 建角色，验证读回 =====")
# 找一个真实存在的 code（从上面列表取第一个非空）
real_code = next((x.get("code") for x in items if x.get("code")), None)
print("using real code:", real_code)
if real_code:
    s, b = req("POST", "/api/roles", tok=TOK, body={"name": f"p15role{RUN}", "scope_codes": [real_code]})
    d = jb(b) if isinstance(jb(b), dict) else {}
    rid = d.get("id")
    print("create role w/ real code:", s, "id=", rid, "body=", str(b)[:120])
    s, b = req("GET", "/api/roles", tok=TOK)
    my = next((r for r in (jb(b) or {}).get("items") or [] if r.get("id") == rid), None)
    print("read back scopes:", my.get("scopes") if my else "NOT FOUND", "(expect [real_code])")
    if rid:
        req("DELETE", f"/api/roles/{rid}", tok=TOK)

print("\n===== [C] 用 harness 原 code rag:search 建角色，看 404 =====")
s, b = req("POST", "/api/roles", tok=TOK, body={"name": f"p15role2{RUN}", "scope_codes": ["rag:search"]})
print("create role w/ 'rag:search':", s, "body=", str(b)[:200])

print("\n===== [D] AGENT-07 多轮记忆：建 agent，同 session 两轮 =====")
# 先建一个 KB（官方退款文档）供 agent 使用（复用 probe10 的 KB 2faa...）
KB = "2faa954d-2426-470e-b718-7c63cfa6de8b"
s, b = req("POST", "/api/agents", tok=TOK, body={"name": f"p15agent{RUN}", "type": "simple", "knowledge_base_ids": [KB]})
d = jb(b) if isinstance(jb(b), dict) else {}
aid = d.get("id")
print("create agent:", s, "id=", aid)
if aid:
    # 显式建 session 并传 session_id 给两轮
    s, b = req("POST", f"/api/agents/{aid}/sessions", tok=TOK, body={})
    sid = (jb(b) if isinstance(jb(b), dict) else {}).get("id")
    print("session:", s, sid)
    s, b = req("POST", f"/api/agents/{aid}/chat", tok=TOK,
               body={"message": "请记住：我的订单号是 ORD-99231", "session_id": sid}, timeout=180)
    print("turn1:", s, (jb(b) if isinstance(jb(b), dict) else {}).get("reply", "")[:60])
    s, b = req("POST", f"/api/agents/{aid}/chat", tok=TOK,
               body={"message": "我刚才提到的订单号是多少？", "session_id": sid}, timeout=180)
    d2 = jb(b) if isinstance(jb(b), dict) else {}
    print("turn2 reply:", d2.get("reply", "")[:80])
    print("  contains 99231/ORD/订单?", any(k in (d2.get("reply") or "") for k in ("99231", "ORD", "订单")))
    # 清场
    req("POST", f"/api/agents/{aid}/sessions/{sid}/close", tok=TOK)
    req("DELETE", f"/api/agents/{aid}", tok=TOK)

print("\n=== done RUN=", RUN, "===")
