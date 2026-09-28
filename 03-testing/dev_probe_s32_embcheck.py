"""S32 dev probe: reachability + dimension of the real 3584-dim embedding endpoint.

Runs INSIDE the joker-api container (network path identical to production code):
  docker cp 03-testing/dev_probe_s32_embcheck.py joker-api:/tmp/
  docker exec joker-api python3 /tmp/dev_probe_s32_embcheck.py
"""
import json

import httpx

BASE = "http://" + "34.64.61.208:4000/v1"

out = {}
try:
    r = httpx.get(BASE + "/models", timeout=10)
    out["models_status"] = r.status_code
    try:
        out["models"] = [m.get("id") for m in r.json().get("data", [])][:12]
    except Exception:
        out["models_body"] = r.text[:300]
except Exception as e:
    out["models_error"] = repr(e)

# try an embeddings call to confirm real 3584-dim output
try:
    body = {"model": "qwen2", "input": ["s32 probe"]}
    r = httpx.post(BASE + "/embeddings", json=body, timeout=30)
    out["emb_status"] = r.status_code
    if r.status_code == 200:
        data = r.json()["data"]
        out["emb_dim"] = len(data[0]["embedding"])
    else:
        out["emb_body"] = r.text[:300]
except Exception as e:
    out["emb_error"] = repr(e)

print(json.dumps(out, ensure_ascii=False, indent=2))
