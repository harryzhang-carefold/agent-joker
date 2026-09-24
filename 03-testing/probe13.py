"""S12 探针 v13：BASE-09 refresh 401 + BASE-05 登出后 access 未失效 根因验证。"""
import json, time, urllib.request, urllib.error

WEB = "http://host.docker.internal:8080"

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

# 1) 登录
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW()})
d = jb(b)
TOK, REF = d.get("access_token"), d.get("refresh_token")
print("login:", s, "access?", bool(TOK), "refresh?", bool(REF), "keys:", list(d.keys()))

# 2) refresh（带完整响应体）
print("\n--- BASE-09 refresh ---")
s, b = req("POST", "/api/auth/refresh", body={"refresh_token": REF})
print("refresh direct:", s, "body:", str(b)[:300])

# 3) 再登录一次，测登出→access 是否失效（jti 黑名单）
print("\n--- BASE-05 logout → access blacklist ---")
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW()})
d = jb(b)
T2, R2 = d.get("access_token"), d.get("refresh_token")
print("login2:", s, bool(T2))
# 登出前 access 有效
s, b = req("GET", "/api/users?page=1", tok=T2)
print("pre-logout GET /api/users:", s)
# 登出
s, b = req("POST", "/api/auth/logout", tok=T2, body={})
print("logout:", s, "body:", str(b)[:120])
# 登出后同 access token 再请求
s, b = req("GET", "/api/users?page=1", tok=T2)
print("POST-logout same access token GET /api/users:", s, "(期望 401, 实际", s, ")")
# 登出后 refresh
s, b = req("POST", "/api/auth/refresh", body={"refresh_token": R2})
print("post-logout refresh:", s, "body:", str(b)[:150])

# 4) 直接看 BFF 是否剥 Authorization（通过 404 路径看 headers 是否透传）
print("\n--- BFF header 透传检查 ---")
s, b = req("GET", "/api/bff/echo-headers", tok=T2, headers={"X-Test-Probe": "hello123"})
print("echo-headers:", s, str(b)[:200])
