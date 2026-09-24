"""S12 探针 v12：计算 query embedding 与已存 chunk 向量的真实余弦相似度，定位 0 命中根因。"""
import json, time, urllib.request, urllib.error

WEB = "http://host.docker.internal:8080"
KB = "2faa954d-2426-470e-b718-7c63cfa6de8b"
CHUNK0 = "3fffcfc0-e362-4ca2-84e4-bcc6bad49690"  # refund txt chunk0

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

# 取 KB 的 embedding 模型
s, b = req("GET", f"/api/rag/kbs/{KB}", tok=TOK)
emb_id = jb(b).get("embedding_model_id")
dim = jb(b).get("embedding_dim")
print("emb model:", emb_id, "dim:", dim)

# 用该模型 embed 查询 + 一条已知 chunk 文本，看维度与自相似度
text_chunk = "本公司售后服务与退款政策总则。第一条 退货退款：客户在订单签收后 7 天内，可凭订单号申请无理由退款"
s, b = req("POST", "/api/llm/embeddings/local/embed", tok=TOK, body={"texts": ["退款", text_chunk, "退款"], "dim": dim})
d = jb(b) if isinstance(jb(b), dict) else {}
vecs = d.get("items") or []
print("embed resp:", s, "n_vecs:", len(vecs), "dims:", [len(v) for v in vecs])
if vecs:
    vq, vc, vq2 = vecs[0], vecs[1], vecs[2]
    def cos(a, b):
        dot = sum(x*y for x, y in zip(a, b))
        na = sum(x*x for x in a) ** 0.5
        nb = sum(x*x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
    print("cos(退款, 退款) [self] = %.4f" % cos(vq, vq2))
    print("cos(退款, chunk文本) = %.4f" % cos(vq, vc))
    print("cos(退款, '退款政策') 同类词测试...")
    s, b = req("POST", "/api/llm/embeddings/local/embed", tok=TOK, body={"texts": ["退款政策", "退款"], "dim": dim})
    v2 = (jb(b) or {}).get("items") or []
    if len(v2) >= 2:
        print("cos('退款政策','退款') = %.4f" % cos(v2[0], v2[1]))
    # 直接调 search，显式 score_threshold=0 看是否出结果（用正确字段名）
    for th in (0.0, -1.0):
        s, b = req("POST", "/api/rag/search", tok=TOK, body={"kb_ids": [KB], "query": "退款", "top_k": 5, "score_threshold": th, "use_rerank": False})
        dd = jb(b) if isinstance(jb(b), dict) else {}
        items = dd.get("items") or []
        print(f"search score_threshold={th}: code={s} total={dd.get('total')} eff_threshold={dd.get('threshold')} scores={[it.get('score') for it in items]}")
