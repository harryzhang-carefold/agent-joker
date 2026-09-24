import json
rows=[json.loads(l) for l in open('/home/hermes/hermes-workspace/projects/agent-joker/03-testing/results.jsonl') if l.strip()]
print('total',len(rows))
fails=[]
for r in rows:
    st=str(r.get('status') or r.get('result') or r.get('state') or '')
    if st.upper() in ('FAIL','FAILED'):
        fails.append(r)
print('fails',len(fails))
for r in fails:
    print(r.get('id'), '|', str(r.get('message') or r.get('error') or r.get('detail') or r.get('name'))[:180])
