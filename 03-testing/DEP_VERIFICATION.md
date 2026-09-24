# DEP_VERIFICATION — S25 接口/依赖验证（QA_STANDARD §一/§四，2026-09-24）

> 本文件为 **S25b 独立回归** 刷新版（替代 S21 版，结论过时）。
> QA_STANDARD 第一条（测试侧复跑）：对「外部依赖类」接口，测试必须复跑"真实/伪鉴权"验证。
> 重点复验 **BUG-08/BUG-11（凭据发送）** 在 S25a 修复（commit 9fd0a93，`_auth_header` bearer 前缀 `***`→`Bearer `）后是否真正生效。
> **判定原则：不采信开发自报，全部独立复跑；凭据类验证用 SHA256 字节级铁证（抗显示脱敏）。**

## 1. 伪鉴权本地服务（QA_STANDARD §四模板）+ 真实端点
- 实现：宿主 `127.0.0.1:9981` 严格伪鉴权（`05-temp/s25b/s25b_strict_pseudoauth.py`），**只接受精确 `Bearer <非空>`**，wire 记录 `val_len + val_sha256`。
- 指向它的 LLM 节点：`base_url=http://host.docker.internal:9981/v1`，探测即 `POST {base}/chat/completions`。
- 另用真实端点做端到端交叉验证（见 §3）。

## 2. 验证项与结果（全部独立复跑）

### A) 带 key 节点 → 探测应发出 Authorization 且 ok  —— **PASS（BUG-11 已修）**
- 操作：`POST /api/llm/endpoints`（`api_key=qa-s25b-key-4821`，base 指向伪鉴权）→ `POST /api/llm/endpoints/{id}/test`。
- 伪鉴权服务捕获 wire：`has_header=true`，`val_len=23`，`val_sha256=00e7c05d…8a152b`。
- 探测返回：`200 ok=true "ok: model=fake responded in 6ms"`。
- 独立重算 `sha256("Bearer "+KEY)=00e7c05df58d8ff159b954b046a46f42f5c14497f822f9299f994601db8a152b`（len=23）→ **逐字节精确匹配（CORRECT_BEARER）**。
- 与 S23 缺陷形态 `sha256("***"+KEY)=eef7ec0d…`（len=19, BROKEN_MASKED）比对：**不匹配**。
- **结论**：节点配置了 api_key，探测请求**已正确携带 `Authorization: Bearer <key>`** → 任何"需要鉴权"的真实端点，平台探测**可判通过**。**BUG-08/BUG-11 凭据发送路径复核 PASS。**

### B) 无 key 节点 → 探测无 Authorization、ok=false（行为正确区分）—— PASS
- 操作：同 base，`api_key` 留空 → 探测。
- 捕获 wire：`has_header=false`，`val_len=0`，`val_sha256=null`（NO_HEADER）；返回 `ok=false`。
- **结论**：无 key 时不发凭据、判不可用——**行为正确**；与 A 的 wire **可精确区分**（A=CORRECT_BEARER / B=NO_HEADER）。

### C) agent 运行时链路（不回归）—— PASS
- 操作：建 agent 绑带 key 节点 → `POST /v1/chat/completions`（BFF 8000）。
- 返回：`200 content="pong"`；wire `val_len=23, val_sha256=00e7c05d…8a152b`（CORRECT_BEARER，同 A 逐字节）。
- **结论**：agent 运行时链路保持已修状态，无回归。

### D) 真实 LLM 端点（34.121.9.233:4000/v1, model=vllm-qwen3.8-27b, 真实 key）—— **PASS（OBS-02 已恢复）**
- 真实 key 来源：`deploy/.env` `LLM_FALLBACK_API_KEY`（**len=66，无掩码点**，非 S21 脚本里的 `Lea...uXG` 占位）。
- 操作：建真实节点（真实 key）→ `POST /api/llm/endpoints/{id}/test`。
- 返回：`200 ok=true summary="ok: model=vllm-qwen3.8-27b responded in 761ms"`。
- **重要更新（vs S21/S23 OBS-02）**：S21/S23 时该端点 key **持续 401**（环境态）。**本轮 S25 用真实 key 探测 `ok=true`** → 端点侧 key 当前**可用**，OBS-02 的 401 已缓解/恢复。
  - 401 判定路径 + 结构化返回仍验证有效：当端点侧 401 时，平台返回 `{ok:false, summary:"unavailable: HTTP 401"}`（结构化，前端可展示），不崩溃。
  - 宿主直连对照：`/v1/models` 带真实 key=404（该 vLLM 无 /models 路由）、无 key=401（端点要求鉴权）→ 说明端点确需鉴权，平台侧凭据正确；端点侧 401/200 抖动属端点侧 worker key 配置（OBS-02/BUG-08 环境态，非平台缺陷）。
- **结论**：真实鉴权端点连通性探测 **ok=true**（端到端强铁证，比伪鉴权更强）。

### E) 真实 embedding 端点（34.64.61.208:4000/v1, model=gte-qwen2, dim=3584）—— **PASS**
- **路由修正（本轮定位）**：embedding 节点须走 `POST /api/llm/embeddings` 创建 + `POST /api/llm/embeddings/{id}/test` 探测（**非** `/api/llm/endpoints/{id}/test`，后者走 `_probe_chat`→`/chat/completions`，而 gte-qwen2 是纯 embedding 服务无该路由 → 404，此为**测试脚本误用路由，非平台缺陷**）。
- 操作：`POST /api/llm/embeddings`（provider=api, dimensions=3584, 无 key）→ `POST /api/llm/embeddings/{id}/test`。
- 返回：`200 ok=true summary="ok: model=gte-qwen2 dim=3584 in 13330ms"`。
- 宿主直连对照：`POST /v1/embeddings` → **200 + 真实向量**（5/5 稳定）。
- **结论**：真实 embedding 端点可达、维度匹配（3584）。该端点无鉴权要求，无 key 亦 ok。（若端点需鉴权，则同 A 路径已证明凭据正确发出。）

## 3. 复现脚本与证据（S25b 独立）
- 伪鉴权：`05-temp/s25b/s25b_strict_pseudoauth.py`（宿主 127.0.0.1:9981）。
- BUG-11 A/B/C 探测：`05-temp/s25b/s25b_bug11_probe.py` → `05-temp/s25b/s25b_bug11_result.json`，wire 原始 `05-temp/s25b/s25b_strict_raw.jsonl`。
- 真实端点（LLM+embedding 正确路由）：`05-temp/s25b/s25b_real_endpoint_v2.py` → `s25b_real_endpoint_v2.json`；embedding 正确路由 `05-temp/s25b/s25b_emb_correct.py` → `s25b_emb_correct.json`；端点侧诊断 `05-temp/s25b/s25b_emb_direct.py`/`s25b_emb_diag.py`。
- 铁证 log：`03-testing/dev_probe_s25b_bug11_probe.log`。
- 容器实码：`docker exec joker-api` `/app/joker_shared/llm/service.py:358` = `return {"Authorization": "Bearer " + key}`（`Bearer `×1，`***`×0）。

## 4. 判定汇总
| 项 | 预期 | 实际 | 判定 |
|---|---|---|---|
| A 带 key 节点探测发 `Bearer <key>` 且 ok | ok=true + wire=CORRECT_BEARER 逐字节 | 一致（sha=00e7c05d…，len=23） | **PASS** |
| B 无 key 节点探测无 Authorization、ok=false | ok=false + NO_HEADER | 一致 | PASS（行为正确） |
| C agent 运行时 200+pong + CORRECT_BEARER | 一致 | 一致 | PASS（无回归） |
| D 真实 LLM 401/200 判定路径 + 结构化返回 | 结构化 ok=false / 有效 key 时 ok=true | 真实 key 探测 ok=true（OBS-02 已恢复） | PASS |
| E 真实 embedding ok dim=3584 | ok=true dim=3584 | 一致（走 `/api/llm/embeddings/{id}/test`） | PASS |

**核心结论**：BUG-08/BUG-11 的"凭据发送"修复**真正生效**——探测链路（`_auth_header` bearer 前缀 `Bearer `）与 agent 运行时统一发出 `Authorization: Bearer <key>`，
SHA256 字节级铁证（A/C 均 CORRECT_BEARER）+ 真实端点端到端 ok=true（D）双重确认。
**BUG-11 可关闭**（待 S25b 回归报告 TEST_REPORT_S25.md 汇总）。
> 附注：embedding 探测的"404"为**测试脚本误用 `/endpoints/{id}/test` 路由**（应走 `/embeddings/{id}/test`），非平台缺陷；本轮已用正确路由复验 PASS。
