"""S12 探针 v9：修正 harness 字段名后的定点重测（RAG 级联 / 会话 / refresh / 限流 / trace / 技能 / LLM）。"""
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
RUN = "p9" + str(int(time.time()) % 100000)
RESULTS = []


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
    last = (-1, b"")
    for a in range(14):
        try:
            resp = urllib.request.urlopen(r, timeout=60)
            return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            last = (e.code, e.read())
            if e.code == 429:
                time.sleep(1.5 + a * 0.5)
                continue
            return last
    return last


def jb(b):
    try:
        return json.loads(b)
    except Exception:
        return b.decode(errors="replace")


def mp(fields, fname, fbytes, ct="application/octet-stream", fname_field="file"):
    boundary = f"----p9{uuid.uuid4().hex}"
    b = b""
    for k, v in fields.items():
        b += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    b += f'--{boundary}\r\nContent-Disposition: form-data; name="{fname_field}"; filename="{fname}"\r\n'.encode()
    b += f"Content-Type: {ct}\r\n\r\n".encode()
    b += fbytes
    b += f"\r\n--{boundary}--\r\n".encode()
    return b, f"multipart/form-data; boundary={boundary}"


def rec(name, ok, ev):
    RESULTS.append({"name": name, "ok": ok, "ev": ev})
    print(("PASS " if ok else "FAIL ") + name + " | " + str(ev)[:150], flush=True)


def wait_doc(kb, doc, tok, tries=50):
    for _ in range(tries):
        s, b = req("GET", f"/api/rag/kbs/{kb}/docs/{doc}", tok=tok)
        d = jb(b) if isinstance(jb(b), dict) else {}
        if d.get("status") in ("ready", "failed"):
            return d.get("status"), d
        time.sleep(1.0)
    return None, {}


s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
TOK = jb(b).get("access_token")
print("login:", s, "ok" if TOK else b[:120])
if not TOK:
    raise SystemExit(1)
# 防跨轮限流泄漏：开场先把 user_qps 拉到 1000（S11/S12 harness 可能残留低值）
for _ in range(8):
    s0, b0 = req("POST", "/api/bff/rate-limits", tok=TOK, body={"dimension": "user_qps", "limit_value": 1000})
    if s0 == 200:
        break
    time.sleep(1.5)
time.sleep(2.0)
s0, b0 = req("GET", "/api/bff/rate-limits", tok=TOK)
_items = (jb(b0) or {}).get("items") or {}
print("qps reset readback:", (_items.get("user_qps") or {}).get("limit"))

# ============ 1. RAG 级联（harness 用 docname 错导致 0/6） ============
s, b = req("GET", "/api/llm/embeddings?status=active", tok=TOK)
embs = [e for e in (jb(b) or {}).get("items") or [] if e.get("provider") == "local"]
emb = embs[0]["id"] if embs else None
s, b = req("POST", "/api/rag/kbs", tok=TOK, body={"name": f"p9-kb-{RUN}", "embedding_model_id": emb, "tag": "official", "top_k_default": 5, "score_threshold": 0.3})
d = jb(b)
KB = d.get("id")
rec("1.1 建库(official)", s == 201 and KB, f"code={s} kb={str(KB)[:8]}")
six = [("refund_policy.txt", "text/plain"), ("policy.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
       ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ("report.pdf", "application/pdf"),
       ("formula.png", "image/png"), ("scan.jpg", "image/jpeg")]
up_ok = 0
doc_ids = {}
FIX = "/s12data/fixtures"
for fn, ct in six:
    stem, ext = fn.rsplit(".", 1)
    dn = f"{stem}_p9.{ext}"
    raw, c2 = mp({}, dn, open(f"{FIX}/{fn}", "rb").read(), ct)
    s, b = req("POST", f"/api/rag/kbs/{KB}/docs", tok=TOK, raw=raw, ctype=c2)
    d = jb(b) if isinstance(jb(b), dict) else {}
    doc_ids[fn] = d.get("id")
    if s == 201:
        up_ok += 1
rec("1.2 RAG-02 六类文档上传", up_ok == 6, f"uploaded={up_ok}/6 ids={list(doc_ids.values())[:2]}")
s, b = req("GET", f"/api/storage/upload-records?source=kb&page=1&page_size=200", tok=TOK)
rec("1.3 RAG-02 上传记录 source=kb", s == 200 and any((x.get("file_name") or "").startswith("refund_policy_p9") for x in (jb(b) or {}).get("items") or []),
    f"total={ (jb(b) or {}).get('total') if isinstance(jb(b), dict) else '?'}")
txt = doc_ids.get("refund_policy.txt")
st, dd = wait_doc(KB, txt, TOK)
rec("1.4 解析流水线 ready+chunk", st == "ready" and (dd.get("chunk_count") or 0) >= 1, f"status={st} chunks={dd.get('chunk_count')} parse={dd.get('parse_method')}")
# 切分策略
s, b = req("POST", f"/api/rag/kbs/{KB}/docs/{txt}/resplit", tok=TOK, body={"split_strategy": "fixed", "split_params": {"chunk_size": 300, "overlap": 20}})
st, dd = wait_doc(KB, txt, TOK)
rec("1.5 RAG-04 定长切分", s == 200 and st == "ready" and (dd.get("chunk_count") or 0) >= 2, f"code={s} chunks={dd.get('chunk_count')}")
s, b = req("POST", f"/api/rag/kbs/{KB}/docs/{txt}/resplit", tok=TOK, body={"split_strategy": "parent_child", "split_params": {"parent_size": 400, "child_size": 150}})
st, dd = wait_doc(KB, txt, TOK)
rec("1.6 RAG-04 父子切分", st == "ready" and (dd.get("chunk_count") or 0) >= 2, f"chunks={dd.get('chunk_count')}")
s, b = req("POST", f"/api/rag/kbs/{KB}/docs/{txt}/resplit", tok=TOK, body={"split_strategy": "semantic", "split_params": {"threshold": 0.25}})
st, dd = wait_doc(KB, txt, TOK)
rec("1.7 RAG-04 语义切分", st == "ready" and (dd.get("chunk_count") or 0) >= 1, f"chunks={dd.get('chunk_count')}")
req("POST", f"/api/rag/kbs/{KB}/docs/{txt}/resplit", tok=TOK, body={"split_strategy": "fixed", "split_params": {"chunk_size": 500, "overlap": 50}})
# 等重切分完成（ready 只代表解析完成；重嵌入可能滞后）
for _ in range(40):
    s, b = req("GET", f"/api/rag/kbs/{KB}/docs/{txt}/chunks?page=1&page_size=50", tok=TOK)
    ci = ((jb(b) or {}).get("items") or []) if isinstance(jb(b), dict) else []
    s2, b2 = req("POST", "/api/rag/search", tok=TOK, body={"kb_ids": [KB], "query": "退款", "top_k": 3, "use_rerank": False})
    d2 = jb(b2) if isinstance(jb(b2), dict) else {}
    if len(ci) >= 1 and (d2.get("total") or 0) >= 1:
        break
    time.sleep(1.5)
s, b = req("GET", f"/api/rag/kbs/{KB}/docs/{txt}/file", tok=TOK)
rec("1.8 RAG-05 原文档查看", s == 200 and len(b) > 50, f"code={s} bytes={len(b)} err={b[:80] if s != 200 else ''}")
s, b = req("GET", f"/api/rag/kbs/{KB}/docs/{txt}/chunks?page=1&page_size=10", tok=TOK)
citems = (jb(b) or {}).get("items") or []
rec("1.9 RAG-05 chunk 列表(顺序+内容+位置)", s == 200 and len(citems) >= 1 and all(("chunk_index" in c and "content" in c and "pos" in c) for c in citems),
    f"chunks={len(citems)} idx={[c.get('chunk_index') for c in citems[:3]]}")
def search_poll(kb, query, tries=20, use_rerank=False):
    for _ in range(tries):
        s, b = req("POST", "/api/rag/search", tok=TOK, body={"kb_ids": [kb], "query": query, "top_k": 3, "use_rerank": use_rerank})
        d = jb(b) if isinstance(jb(b), dict) else {}
        if (d.get("total") or 0) >= 1:
            return s, d
        time.sleep(1.5)
    return s, d

s, d = search_poll(KB, "订单签收后 7 天内可无理由退款", use_rerank=False)
hits = d.get("items") or []
rec("1.10 RAG-07 纯向量检索有命中", s == 200 and len(hits) >= 1, f"hits={len(hits)} reranked={d.get('reranked')}")
s, d = search_poll(KB, "订单签收后 7 天内可无理由退款")
hits = d.get("items") or []
rec("1.11 RAG-09 命中带 chunk_index+pos+doc_id", s == 200 and len(hits) >= 1 and all(("chunk_index" in h and "pos" in h and "doc_id" in h) for h in hits),
    f"hit0={hits[0] and {k: str(hits[0].get(k))[:20] for k in ('chunk_index', 'pos', 'doc_id')}}")
s, d = search_poll(KB, "退款")
hits = d.get("items") or []
rec("1.12 D-A 库级 official → is_official=true", s == 200 and len(hits) >= 1 and any(h.get("is_official") is True for h in hits),
    f"official={sum(1 for h in hits if h.get('is_official'))}/{len(hits)}")
print("RAG part done", flush=True)

# ============ 2. 会话（正确字段：响应 id 非 session_id；PATCH 重命名） ============
s, b = req("GET", "/api/agents", tok=TOK)
agents = [a for a in (jb(b) or {}).get("items") or [] if (a.get("name") or "").startswith(f"p9-agent") or a.get("type") == "simple"]
# 建一个自己的 agent
s, b = req("POST", "/api/agents", tok=TOK, body={"name": f"p9-agent-{RUN}", "type": "simple", "system_prompt": "客服", "llm_endpoint_ids": [], "knowledge_base_ids": [KB], "mcp_tool_ids": []})
d = jb(b)
AG = d.get("id")
rec("2.0 建 simple agent(绑定 KB)", s == 201 and AG, f"code={s} ag={str(AG)[:8]}")
s, b = req("POST", f"/api/agents/{AG}/chat", tok=TOK, body={"message": "请问退款政策是怎样的？", "show_citations": True})
d = jb(b) if isinstance(jb(b), dict) else {}
SID = d.get("session_id")
rec("2.1 对话得回复", s == 200 and d.get("reply"), f"reply={str(d.get('reply'))[:50]}")
s, b = req("GET", f"/api/agents/{AG}/sessions", tok=TOK)
items = (jb(b) or {}).get("items") or []
rec("2.2 AGENT-04 会话列表含本会话", s == 200 and any(x.get("id") == SID for x in items), f"total={(jb(b) or {}).get('total')} fields={list(items[0].keys()) if items else []}")
s, b = req("POST", f"/api/agents/{AG}/sessions", tok=TOK, body={})
d = jb(b) if isinstance(jb(b), dict) else {}
NSID = d.get("id")
rec("2.3 AGENT-04 会话新建(200+id)", s in (200, 201) and NSID, f"code={s} id={str(NSID)[:8]}")
s, b = req("PATCH", f"/api/agents/{AG}/sessions/{NSID}", tok=TOK, body={"title": "p9-renamed"})
rec("2.4 AGENT-04 会话重命名(PATCH)", s == 200, f"code={s} {b[:60]}")
s, b = req("DELETE", f"/api/agents/{AG}/sessions/{NSID}", tok=TOK)
rec("2.5 AGENT-04 会话删除(DELETE)", s == 200, f"code={s} {b[:60]}")
# AGENT-05 official 强制引用
s, b = req("POST", f"/api/agents/{AG}/chat", tok=TOK, body={"message": "请问退款政策是怎样的？", "show_citations": True})
d = jb(b) if isinstance(jb(b), dict) else {}
rec("2.6 AGENT-05 official 命中强制附 RAG 来源", s == 200 and (d.get("citations_forced_official") is True or len(d.get("citations") or []) >= 1),
    f"forced={d.get('citations_forced_official')} cites={len(d.get('citations') or [])}")
# AGENT-07 多轮（复用 session_id）
s, b = req("POST", f"/api/agents/{AG}/chat", tok=TOK, body={"message": "请记住：我的订单号是 ORD-99887", "session_id": SID, "show_citations": False})
s2, b2 = req("POST", f"/api/agents/{AG}/chat", tok=TOK, body={"message": "我刚才提到的订单号是多少？", "session_id": SID, "show_citations": False})
d2 = jb(b2) if isinstance(jb(b2), dict) else {}
r2 = d2.get("reply") or ""
rec("2.7 AGENT-07 多轮上下文连贯(同 session_id)", s2 == 200 and ("99887" in r2 or "ORD" in r2), f"reply2={r2[:60]}")

# ============ 3. refresh（正确端点 /api/auth/refresh，无 auth 头） ============
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
d = jb(b)
t1, r1 = d.get("access_token"), d.get("refresh_token")
s, b = req("POST", "/api/auth/refresh", body={"refresh_token": r1})
d2 = jb(b) if isinstance(jb(b), dict) else {}
rec("3.1 BASE-09 refresh 换新 token", s == 200 and d2.get("access_token") and d2.get("access_token") != t1, f"code={s} {str(b)[:80]}")
s, b = req("POST", "/api/auth/refresh", body={"refresh_token": r1})
rec("3.2 BASE-09 旧 refresh 重放 401", s == 401, f"code={s} {b[:60]}")

# ============ 4. BASE-05 登出黑名单（再确认：经 webconsole） ============
s, b = req("POST", "/api/auth/login", body={"tenant_code": "acme", "username": "admin", "password": PW})
d = jb(b)
t2 = d["access_token"]
s, b = req("GET", "/api/users?page=1", tok=t2)
pre = s
time.sleep(1.2)
s, b = req("POST", "/api/auth/logout", tok=t2, body={"refresh_token": d.get("refresh_token")})
time.sleep(1.0)
s, b = req("GET", "/api/users?page=1", tok=t2)
rec("4.1 BASE-05 登出后 access token 失效", pre == 200 and s == 401, f"pre={pre} post_logout={s} (401=OK 200=BUG)")

# ============ 5. audit 时间筛选（start/end） ============
s, b = req("GET", "/api/audit/logs?start=2020-01-01T00:00:00Z&end=2021-01-01T00:00:00Z&page_size=50", tok=TOK)
rec("5.1 BASE-06 audit 时间范围筛选(2020→0)", s == 200 and (jb(b) or {}).get("total") == 0, f"total={(jb(b) or {}).get('total')}")
s, b = req("GET", "/api/audit/logs?path=/api/auth/logout&page_size=20", tok=TOK)
rec("5.2 BASE-05 登出记录到操作日志", s == 200 and any("/api/auth/logout" in (a.get("path") or "") for a in (jb(b) or {}).get("items") or []),
    f"found={any('/api/auth/logout' in (a.get('path') or '') for a in (jb(b) or {}).get('items') or [])}")
# upload-records 时间筛选（asyncpg 500 复现）
s, b = req("GET", "/api/storage/upload-records?start=2020-01-01T00:00:00Z&end=2021-01-01T00:00:00Z", tok=TOK)
rec("5.3 STORE-05 上传记录时间筛选(应 200 total=0)", s == 200 and (jb(b) or {}).get("total") == 0, f"code={s} {b[:60]} (500=BUG)")

# ============ 6. roles scopes（正确字段 scope_codes） ============
rn = f"p9r{RUN}"
s, b = req("POST", "/api/roles", tok=TOK, body={"name": rn, "scope_codes": ["rag:search", "storage:read"]})
d = jb(b)
rid = d.get("id")
s2, b2 = req("GET", "/api/roles", tok=TOK)
rr = next((x for x in (jb(b2) or {}).get("items") or [] if x.get("id") == rid), None)
rec("6.1 BASE-02 角色权限清单(scope_codes)", rr is not None and "rag:search" in (rr.get("scopes") or []), f"scopes={rr.get('scopes') if rr else None}")
s, b = req("PUT", f"/api/roles/{rid}", tok=TOK, body={"scope_codes": ["rag:search", "storage:read", "agents:manage"]})
s2, b2 = req("GET", "/api/roles", tok=TOK)
rr = next((x for x in (jb(b2) or {}).get("items") or [] if x.get("id") == rid), None)
rec("6.2 BASE-02 改角色权限即时生效", s == 200 and rr and "agents:manage" in (rr.get("scopes") or []), f"new={rr.get('scopes') if rr else None}")
# 用户详情 roles 字段
s, b = req("POST", "/api/users", tok=TOK, body={"username": f"p9u{RUN}", "password": "x12345", "role_names": ["member"]})
d = jb(b)
uid = d.get("id")
s2, b2 = req("GET", f"/api/users/{uid}", tok=TOK)
rec("6.3 BASE-02 用户详情含 roles 字段", s2 == 200 and (jb(b2) or {}).get("roles") is not None, f"roles={(jb(b2) or {}).get('roles')} keys={sorted((jb(b2) or {}).keys()) if isinstance(jb(b2), dict) else '?'}")
s, b = req("PUT", f"/api/users/{uid}", tok=TOK, body={"role_names": ["admin"]})
s2, b2 = req("GET", f"/api/users/{uid}", tok=TOK)
rec("6.4 BASE-02 变更角色后详情读回", s == 200 and (jb(b2) or {}).get("roles") == ["admin"], f"roles={(jb(b2) or {}).get('roles')}")

# ============ 7. LLM-01 修改 endpoint（base_url 字段） ============
s, b = req("POST", "/api/llm/endpoints", tok=TOK, body={"name": f"p9ep{RUN}", "base_url": "http://127.0.0.1:1/v1", "model": "mock", "api_key": "k", "status": "active"})
d = jb(b)
ep = d.get("id")
s, b = req("PUT", f"/api/llm/endpoints/{ep}", tok=TOK, body={"base_url": "http://127.0.0.1:2/v1"})
rec("7.1 LLM-01 修改 endpoint(base_url)", s == 200, f"code={s} {b[:80]}")
req("DELETE", f"/api/llm/endpoints/{ep}", tok=TOK)

# ============ 8. 技能上传（files 字段） ============
sn = f"p9skill{RUN}"
raw, c2 = mp({"name": sn, "description": "p9"}, f"skill_{sn}.md", b"# skill content", "text/markdown", fname_field="files")
s, b = req("POST", "/api/skills/upload", tok=TOK, raw=raw, ctype=c2)
d = jb(b) if isinstance(jb(b), dict) else {}
rec("8.1 SKILL-01 上传 skill 文件(files 字段)", s == 201 and d.get("id"), f"code={s} {str(b)[:80]}")
if d.get("id"):
    s, b = req("GET", f"/api/skills/{d['id']}", tok=TOK)
    d = jb(b) if isinstance(jb(b), dict) else {}
    rec("8.2 SKILL-02 文件走存储(source=skill)", s == 200 and len(d.get("files") or []) >= 1, f"files={[f.get('file_name') for f in (d.get('files') or [])]}")
    req("DELETE", f"/api/skills/{d['id']}", tok=TOK)

# ============ 9. MCP-03 referring-agents ============
s, b = req("POST", "/api/mcp/servers", tok=TOK, body={"name": f"p9mcp{RUN}", "url": "http://joker-mock-mcp:9100/mcp", "transport": "streamable_http"})
d = jb(b)
srv = d.get("id")
s, b = req("GET", f"/api/mcp/servers/{srv}/referring-agents", tok=TOK)
d = jb(b) if isinstance(jb(b), dict) else {}
rec("9.1 MCP-03 查询 server 关联调用方", s == 200 and "items" in d or "total" in d, f"code={s} {str(b)[:80]}")
req("DELETE", f"/api/mcp/servers/{srv}?confirm=false", tok=TOK)

# ============ 10. TRACE 按会话检索 ============
s, b = req("GET", f"/api/trace/events?session_id={SID}&page_size=50", tok=TOK)
rec("10.1 TRACE-02 按会话检索 trace", s == 200 and (jb(b) or {}).get("total") >= 1, f"total={(jb(b) or {}).get('total')}")

# ============ 11. 限流（user_qps=1，窗口对齐验证） ============
def set_rl(val):
    for _ in range(8):
        s, b = req("POST", "/api/bff/rate-limits", tok=TOK, body={"dimension": "user_qps", "limit_value": val})
        if s == 200:
            time.sleep(2.5)
            s2, b2 = req("GET", "/api/bff/rate-limits", tok=TOK)
            items = (jb(b2) or {}).get("items") or {}
            if (items.get("user_qps") or {}).get("limit") == val:
                return True
        time.sleep(1.5)
    return False

ok = set_rl(1)
read = None
s, b = req("GET", "/api/bff/rate-limits", tok=TOK)
read = ((jb(b) or {}).get("items") or {}).get("user_qps", {}).get("limit")
codes = [req("GET", "/api/users?page=1", tok=TOK)[0] for _ in range(4)]
rec("11.1 限流 单用户超 QPS→429", ok and 429 in codes, f"set_ok={ok} read={read} codes={codes}")
time.sleep(1.5)
codes2 = [req("GET", "/api/users?page=1", tok=TOK)[0] for _ in range(4)]
set_rl(1000)
print("\n=== SUMMARY ===")
print(json.dumps(RESULTS, ensure_ascii=False, indent=1))
