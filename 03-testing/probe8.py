"""S12 探针 v8：BASE-05 终局验证 —— 登出→检查 Redis deny key→同 token 再请求。"""
import asyncio
import base64
import json
import time
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


def req(method, path, tok=None, body=None):
    h = {"Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    r = urllib.request.Request(WEB + path, data=data, headers=h, method=method)
    try:
        return urllib.request.urlopen(r, timeout=30).status
    except urllib.error.HTTPError as e:
        return e.code


async def main():
    from joker_shared import redis_client
    r = redis_client.get_redis()
    print("redis ping:", await r.ping())

    pw = SEEDPW()
    s = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": pw})
    d = json.loads(req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": pw}) if isinstance(req, str) else b"{}")
    # do proper login twice to keep tokens
    import urllib.request
    def login():
        data = json.dumps({"tenant_code": "acme", "username": "admin", "password": pw}).encode()
        rq = urllib.request.Request(WEB + "/api/auth/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
        return json.loads(urllib.request.urlopen(rq, timeout=30).read())

    d1 = login()
    t1 = d1["access_token"]
    jti1 = json.loads(base64.urlsafe_b64decode(t1.split(".")[1] + "=="))["jti"]
    key1 = f"joker:jwt:deny:{jti1}"
    print("t1 jti:", jti1[:20], "key:", key1)
    print("pre-logout key exists:", await r.exists(key1))
    print("pre-logout /api/users:", req("GET", "/api/users?page=1", tok=t1))
    req("POST", "/api/auth/logout", tok=t1, body={"refresh_token": d1.get("refresh_token")})
    await asyncio.sleep(1.0)
    print("post-logout key exists:", await r.exists(key1), "ttl:", await r.ttl(key1))
    print("post-logout /api/users same token:", req("GET", "/api/users?page=1", tok=t1))
    # 直接验证 is_denied
    print("is_denied(jti1):", await redis_client.is_denied(jti1))
    await redis_client.aclose()

asyncio.run(main())
