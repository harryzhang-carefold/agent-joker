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
    for _ in range(3):
        try:return urllib.request.urlopen(r,timeout=60).status,urllib.request.urlopen(r,timeout=60).read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    return -1,b"?"
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
print("login",s,"tok?",bool(TOK))
if not TOK:
    print("LOGIN FAILED:",b[:300]);raise SystemExit(1)
s,b=req("GET","/api/llm/embeddings?status=active",tok=TOK)
print("emb list:",s,str(jb(b))[:150])
emb=[e for e in (jb(b) or {}).get("items") or [] if e.get("provider")=="local"][0]["id"]
s,b=req("POST","/api/rag/kbs",tok=TOK,body={"name":"dbg2-"+str(int(time.time())%100000),"embedding_model_id":emb})
print("kb:",s,b[:200])
KB=jb(b).get("id")
time.sleep(1)
for fn,ct in [("refund_policy.txt","text/plain")]:
    raw,c2=mp(fn,open("/s12data/fixtures/"+fn,"rb").read(),ct)
    s,b=req("POST",f"/api/rag/kbs/{KB}/docs",tok=TOK,raw=raw,ct=c2)
    print("upload",fn,":",s,b[:300])
    if s!=201:
        break
