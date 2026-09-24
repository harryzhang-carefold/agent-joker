import json, time, uuid, urllib.request, urllib.error
WEB="http://host.docker.internal:8080"
def PW():
    try:
        for line in open("/proj/deploy/.env"):
            if line.startswith("SEED_ADMIN_PASSWORD="): return line.split("=",1)[1].strip()
    except: pass
    return "acme123"
def req(m,p,tok=None,body=None,raw=None,ct=None,verbose=True):
    h={"Content-Type":"application/json"};d=None
    if body is not None:d=json.dumps(body).encode()
    if raw is not None:d=raw;h["Content-Type"]=ct
    if tok:h["Authorization"]=f"Bearer {tok}"
    r=urllib.request.Request(WEB+p,data=d,headers=h,method=m)
    try:
        resp=urllib.request.urlopen(r,timeout=60)
        return resp.status,resp.read()
    except urllib.error.HTTPError as e:
        return e.code,e.read()
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
# reset qps
for _ in range(5):
    s,b=req("POST","/api/bff/rate-limits",tok=TOK,body={"dimension":"user_qps","limit_value":1000})
    if s==200:break
    time.sleep(1.5)
time.sleep(2)
s,b=req("GET","/api/llm/embeddings?status=active",tok=TOK)
emb=[e for e in (jb(b) or {}).get("items") or [] if e.get("provider")=="local"][0]["id"]
s,b=req("POST","/api/rag/kbs",tok=TOK,body={"name":"dbg3-"+str(int(time.time())%100000),"embedding_model_id":emb})
KB=jb(b).get("id")
print("kb",s)
# 逐上传，打印真实状态码 + 间隔
six=[("refund_policy.txt","text/plain"),("policy.docx","application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
("data.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),("report.pdf","application/pdf"),
("formula.png","image/png"),("scan.jpg","image/jpeg")]
for i,(fn,ct) in enumerate(six):
    raw,c2=mp(fn,open("/s12data/fixtures/"+fn,"rb").read(),ct)
    t0=time.time()
    s,b=req("POST",f"/api/rag/kbs/{KB}/docs",tok=TOK,raw=raw,ct=c2)
    print(f"upload[{i}] {fn} -> {s} ({time.time()-t0:.1f}s) body={b[:150]}")
    if i<5: time.sleep(1.5)
