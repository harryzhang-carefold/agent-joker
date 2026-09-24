import json, time, uuid, urllib.request, urllib.error
WEB="http://host.docker.internal:8080"
def PW():
    try:
        for line in open("/proj/deploy/.env"):
            if line.startswith("SEED_ADMIN_PASSWORD="): return line.split("=",1)[1].strip()
    except: pass
    return "acme123"
def req(m,p,tok=None,body=None,raw=None,ct=None):
    h={"Content-Type":"application/json"};d=None
    if body is not None:d=json.dumps(body).encode()
    if raw is not None:d=raw;h["Content-Type"]=ct
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(WEB+p,data=d,headers=h,method=m)
    last=(-1,b"")
    for a in range(14):
        try:
            resp=urllib.request.urlopen(r,timeout=60)
            return resp.status,resp.read()
        except urllib.error.HTTPError as e:
            last=(e.code,e.read())
            if e.code==429:
                time.sleep(1.5+a);continue
            return last
    return last
def jb(b):
    try:return json.loads(b)
    except:return b.decode(errors="replace")
def mp(fn,fbytes,ct):
    bnd=f"----x{uuid.uuid4().hex}";b=b""
    b+=f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fn}\"\r\n".encode()
    b+=f"Content-Type: {ct}\r\n\r\n".encode();b+=fbytes;b+=f"\r\n--{bnd}--\r\n".encode()
    return b,f"multipart/form-data; boundary={bnd}"
s,b=req("POST","/api/auth/login",body={"tenant_code":"acme","username":"admin","password":PW()})
TOK=jb(b).get("access_token")
print("login",s)
# 先确保 user_qps 复位（前一轮限流测试可能残留低值）
for _ in range(6):
    s,b=req("POST","/api/bff/rate-limits",tok=TOK,body={"dimension":"user_qps","limit_value":1000})
    if s==200:break
    time.sleep(1.5)
time.sleep(2)
s,b=req("GET","/api/llm/embeddings?status=active",tok=TOK)
emb=[e for e in (jb(b) or {}).get("items") or [] if e.get("provider")=="local"][0]["id"]
s,b=req("POST","/api/rag/kbs",tok=TOK,body={"name":"dbg-"+str(int(time.time())%100000),"embedding_model_id":emb})
KB=jb(b).get("id")
print("kb",s,str(KB)[:8])
time.sleep(1)
raw,c2=mp("dbg_refund.txt",open("/s12data/fixtures/refund_policy.txt","rb").read(),"text/plain")
s,b=req("POST","/api/rag/kbs/%s/docs"%KB,tok=TOK,raw=raw,ct=c2)
print("upload:",s,b[:300])
