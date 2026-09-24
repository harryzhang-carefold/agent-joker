import json,collections
rows=[json.loads(l) for l in open('/home/hermes/hermes-workspace/projects/agent-joker/03-testing/results.jsonl') if l.strip()]
print('keys sample:',sorted(rows[0].keys()))
print('first row:',json.dumps(rows[0],ensure_ascii=False)[:400])
c=collections.Counter()
for r in rows:
    for k in ('status','result','state','pass','ok','success'):
        if k in r: c[(k,str(r[k]))]+=1
for k,v in c.most_common(): print(k,v)
