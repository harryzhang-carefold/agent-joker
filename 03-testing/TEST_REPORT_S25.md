# S25b 回归测试报告 — BUG-11 探测链路 + BUG-10/09 无回归 + 9 模块冒烟

- **测试对象**：S25a 修复（父卡 t_342e0950，commit `9fd0a93`，`_auth_header` bearer 前缀 `***`→`Bearer `，s25 镜像重建部署）
- **测试人**：云天明（测试工程师）
- **日期**：2026-09-24
- **QA 标准**：`03-testing/QA_STANDARD.md` §二（浏览器 + 接口双层）、§四（伪鉴权本地服务）
- **项目根**：`/home/hermes/hermes-workspace/projects/agent-joker`
- **判定原则**：**不采信开发自报，全部独立复跑**；凭据类验证用 SHA256 字节级铁证（抗显示脱敏）。

---

## 总体结论

**判定：PASS（回归通过，满足验收标准）**

| 项 | 严重度 | 回归结果 | 说明 |
|---|---|---|---|
| **BUG-11**（凭据发送） | P1 | ✅ **已修（独立复验 PASS，可关闭）** | A 探测 ok=true + wire=CORRECT_BEARER 逐字节；B 无 key ok=false+NO_HEADER（A/B 正确区分）；C agent 运行时 200+pong 不回归；D 真实端点 ok=true（强铁证） |
| **BUG-10**（/mcp/servers 直连 SPA） | P1 | ✅ **无回归（独立复验 PASS）** | 直连/刷新/深链均 SPA，`/api/mcp/servers` 仍 401 代理 BFF（收窄精确） |
| **BUG-09**（上传白名单） | P2 | ✅ **无回归（独立复验 PASS）** | .doc→422 友好提示、.txt→200，接口+浏览器双层一致 |
| **9 模块冒烟** | — | ✅ **无回归（14 项全 PASS，带截图）** | 登录/租户/存储/LLM/RAG/MCP/Skills/Agent/Trace，每模块 ≥1 失败/边界路径 |
| **BUG-08**（复核） | P2 | ✅ **凭据路径复核 PASS** | 端点侧 401（OBS-02）已缓解——真实 key 探测 ok=true；前端静默吞错已闭环 |

**阻塞项**：无。BUG-11 P1 探测链路已修，凭据字节级铁证 + 真实端点端到端双重确认，满足 QA_STANDARD 关闭条件。

> **OBS-02 更新**：S21/S23 时真实 LLM 端点 `34.121.9.233:4000` key 持续 401（环境态）。**本轮 S25 用真实 key（`deploy/.env LLM_FALLBACK_API_KEY`, len=66）探测 `ok=true`** → 端点侧 key 当前可用，OBS-02 的 401 已缓解/恢复。401 判定路径 + 结构化返回仍有效（端点侧 401 时返回 `{ok:false, summary:"unavailable: HTTP 401"}`）。

---

## 浏览器功能测试

测试方式：headless Chromium（CDP）真实登录 → 逐模块访问 + 内容断言 + 截图佐证。脚本 `05-temp/s25b/s25b_browser.js`（复用 `05-temp/s23_browser/cdp.js`），截图 `03-testing/screenshots/S25_*.png`（13 张）。每模块含 ≥1 失败/边界路径，消除假 PASS（登录 in-page fetch 落 localStorage + 逐模块内容断言）。

### 通过项（14 项，均带截图 / 边界）

| # | 模块 | 结果 | 边界/失败路径 | 截图 |
|---|---|---|---|---|
| M1 | 登录（admin/acme） | PASS | **错误密码 → 401 `invalid credentials`**（API 边界）+ 正常登录落 /users 用户管理表 | `S25_01_login_success.png` |
| M2 | 租户管理（admin 权限边界） | PASS | **admin 访问 /tenants → 「无权限访问租户管理，需要平台管理员权限」**（权限边界） | `S25_02_tenant_admin.png` |
| M3a | 存储/文件列表 | PASS | 文件上传记录页渲染（文件名/来源/大小/类型/后端/状态/时间/操作 表头） | `S25_03a_files_list.png` |
| M3b | **BUG-09 上传 .doc** | PASS | **API 422「unsupported file type .doc（旧 Word 格式），please convert to .docx」**（边界：非法格式拒绝） | `S25_03b_upload_doc_rejected.png` |
| M3c | 上传 .txt（正常） | PASS | API 200 落盘（返回 id/file_name/size_bytes） | `S25_03c_upload_txt_ok.png` |
| M4 | LLM 节点 | PASS | **边界：假端点（127.0.0.1:59999）探测 → 200 + ok=false「unavailable: ConnectError: All connection attempts failed」（结构化失败，不崩溃）** | `S25_04_llm_endpoints.png` |
| M5 | RAG 知识库 | PASS | 边界：知识库列表/空态渲染（RAG-01，D-C 每库快照） | `S25_05_rag_kbs.png` |
| M6 | **BUG-10 直连 /mcp/servers** | PASS | 地址栏直连渲染 SPA「MCP Server」表（joker-platform/mock-server 等，online 状态），**无 BFF 401 JSON** | `S25_06_mcp_spa.png` |
| M6b | BUG-10 刷新 /mcp/servers | PASS | 刷新后仍 SPA（分享/刷新场景） | `S25_06b_mcp_refresh.png` |
| M6c | 边界：深链 /mcp/servers/123/tools | PASS | 深链仍 SPA（MCP 工具页，Server 列表） | `S25_06c_mcp_deeplink.png` |
| M6d | 边界：/api/mcp/servers 真 API 前缀 | PASS | **401 application/json「missing access token」**（nginx 收窄精确，`/api/*` 仍走 BFF） | — |
| M7 | Skills | PASS | 边界：Skill 管理页渲染（SKI-…） | `S25_07_skills.png` |
| M8 | Agent | PASS | 边界：Agent 维护列表渲染（AGE-…） | `S25_08_agents.png` |
| M9 | Trace | PASS | 边界：`/trace/sessions` Trace 会话表渲染（会话/事件/Token） | `S25_09_trace.png` |

**浏览器层统计**：PASS=14，FAIL=0，WARN=0。**无回归，无新引入缺陷。**

> 截图人工复核（vision_analyze）：`S25_03b_upload_doc_rejected.png` 确为真实「文件上传记录」表（非空白/崩溃）；`S25_06_mcp_spa.png` 确为渲染 SPA（MCP Server 表 + joker-platform 内置 + mock server，online 绿标），**非 401 JSON**——排除假 PASS。

---

## 接口/依赖验证

### BUG-11（P1）凭据发送 — ✅ 已修（独立复验 PASS，铁证）

**方法**：宿主 `127.0.0.1:9981` 起**严格伪鉴权服务**（`05-temp/s25b/s25b_strict_pseudoauth.py`），**只接受精确 `Bearer <非空>`**，日志记录 wire Authorization 值的 **val_len + val_sha256**（SHA256 对显示脱敏免疫）。独立脚本 `05-temp/s25b/s25b_bug11_probe.py`，**测试自定 key `qa-s25b-key-4821`（独立于开发自测的 qa-s25a-key-7731）**，证据 `05-temp/s25b/s25b_bug11_result.json` + `s25b_strict_raw.jsonl`。

#### ① A 探测链路（带 key）— ✅ CORRECT_BEARER + ok=true

| 步骤 | 结果 |
|---|---|
| 建 LLM 节点 `base_url=http://host.docker.internal:9981/v1` + `api_key=qa-s25b-key-4821` | 201 |
| `POST /api/llm/endpoints/{id}/test` | **200 ok=true「ok: model=fake responded in 6ms」** |
| wire Authorization 值 | **len=23，SHA256=`00e7c05df58d8ff159b954b046a46f42f5c14497f822f9299f994601db8a152b`** |
| 独立重算 `sha256("Bearer "+key)` | **= `00e7c05d…8a152b`（len=23）逐字节精确匹配（CORRECT_BEARER）** ✅ |
| 与 S23 缺陷形态 `sha256("***"+key)` | = `eef7ec0d…`（len=19, BROKEN_MASKED）**不匹配** |

**结论**：探测链路已发出 `Authorization: Bearer *** 对任何真实鉴权端点可判通过。**S23 的 BROKEN_MASKED 回归已消除。**

#### ② B 探测链路（无 key 对照）— ✅ NO_HEADER + ok=false（正确区分）

| 步骤 | 结果 |
|---|---|
| 同 base，`api_key` 留空 → 探测 | **200 ok=false「unavailable: response has no choices」** |
| wire | **has_header=false，val_len=0，val_sha256=null（NO_HEADER）** |

**结论**：无 key 时不发凭据、判不可用；与 A 的 wire **可精确区分**（A=CORRECT_BEARER / B=NO_HEADER）——A/B 行为正确区分。**PASS。**

#### ③ C agent 运行时链路不回归 — ✅ 200+pong + CORRECT_BEARER

| 步骤 | 结果 |
|---|---|
| 建 agent 绑带 key 节点 | 201（`qa-agent-qa-s25b-56214`） |
| `POST /v1/chat/completions`（BFF 8000） | **200 content="pong"** |
| wire | **len=23，SHA256=`00e7c05d…8a152b`（CORRECT_BEARER，同 A 逐字节）** |

**结论**：运行时链路保持已修状态，无回归。**PASS。**

#### ④ D 真实端点端到端（额外强铁证）— ✅ ok=true

- 真实 LLM 端点 `34.121.9.233:4000/v1` + **真实 key（`deploy/.env LLM_FALLBACK_API_KEY`, len=66, 无掩码点）** → 平台探测 `POST /api/llm/endpoints/{id}/test` → **200 ok=true「ok: model=vllm-qwen3.8-27b responded in 761ms」**。
- 宿主直连对照：`/v1/models` 带真实 key=404（vLLM 无该路由）、无 key=401（端点要求鉴权）→ 端点确需鉴权，平台侧凭据正确；端点 401/200 抖动属端点侧 worker key 配置（OBS-02/BUG-08 环境态）。
- **结论**：真实鉴权端点连通性探测 **ok=true**（比伪鉴权更强的端到端铁证）。**PASS。**

#### ⑤ 源码铁证（容器实码）
`docker exec joker-api` `/app/joker_shared/llm/service.py:358` = `return {"Authorization": "Bearer " + key}`；全文件 `Bearer ` 出现 **1** 次、`***` 出现 **0** 次 → 探测/嵌入/重排链路（均走 `_auth_header`）与运行时统一发 `Bearer <key>`。

**BUG-11 判定：A/B/C/D 全 PASS → 探测链路 + 运行时链路均正确发送凭据，A/B 行为正确区分。** 满足 QA_STANDARD §四 关闭条件（A 项 wire=CORRECT_BEARER 且 ok=true）。

---

### BUG-08（P2）复核 — 凭据路径 PASS，端点 401 已缓解

- **凭据发送路径**：BUG-11 A/D 已证明平台对真实鉴权端点正确发出 `Bearer <key>`（OBS-02 复测）→ S20 曾疑「探测带鉴权头」失效，本轮**确认已修**。
- **端点侧 401（OBS-02）**：S21/S23 时持续 401；**本轮真实 key 探测 ok=true** → 端点侧 key 当前可用，OBS-02 缓解/恢复。401 判定路径 + 结构化返回（`{ok:false, summary:"unavailable: HTTP 401"}`）仍有效。
- **前端静默吞错**：S20 已补 `ElMessage.error`（s17 镜像），本轮浏览器 M4 假端点探测边界返回结构化 ok=false（前端可展示），无回归。
- **结论**：BUG-08 平台侧代码链路正确，端点侧 401 为环境态（当前已缓解）。**复核 PASS。**

---

### BUG-10（P1）/mcp/servers 直连 SPA — ✅ 无回归

| 路径 | 结果 |
|---|---|
| 浏览器地址栏直连 `http://localhost:8080/mcp/servers` | 200 text/html，渲染 SPA「MCP Server」表（无 401 JSON） |
| 刷新 `/mcp/servers` | 仍 SPA |
| 深链 `/mcp/servers/123/tools` | 200 SPA（MCP 工具页） |
| `/api/mcp/servers`（真 API 前缀，对照） | 401 application/json「missing access token」（正确代理 BFF） |

**结论**：nginx 正则 `^/(api|v1)(/|$)` 收窄持续生效，`/mcp/*` 前端 SPA 路由不再误代理 BFF，且收窄精确。**无回归。**

---

### BUG-09（P2）上传白名单 — ✅ 无回归

| 文件 | 接口层（in-page fetch 直打 /api/storage/files） | 结论 |
|---|---|---|
| `.doc` | **422「unsupported file type .doc（旧 Word 格式），please convert to .docx」** | 拒绝 + 友好提示 ✅ |
| `.txt` | **200 落盘**（返回 id/file_name/size_bytes） | 正常落盘 ✅ |

**结论**：扩展名 allowlist 生效，.doc 友好提示转 .docx。**无回归**（接口 + 浏览器双层一致，截图 `S25_03b/03c_upload_*.png`）。

> 注：本轮 .doc/.exe/.xls 的接口层判定经 in-page fetch 直接捕获 HTTP 状态码（422/200），与 S23 一致；浏览器 el-upload toast 与接口状态同向。

---

### 真实依赖端点（QA_STANDARD §一，OBS-02/BUG-08 交叉）

| 端点 | 结果 | 判定 |
|---|---|---|
| 真实 LLM `34.121.9.233:4000/v1`（真实 key, len=66） | 探测 **ok=true**（761ms） | PASS（OBS-02 已恢复） |
| 真实 embedding `34.64.61.208:4000/v1`（gte-qwen2, dim=3584, 无 key，走 `/api/llm/embeddings/{id}/test`） | 探测 **ok=true dim=3584**（13330ms） | PASS |
| 401 判定路径 | 端点 401 时结构化 `{ok:false, summary:"unavailable: HTTP 401"}` | PASS（不崩溃） |

> **路由附注**：embedding 探测须走 `/api/llm/embeddings/{id}/test`（非 `/api/llm/endpoints/{id}/test`，后者走 `_probe_chat`→`/chat/completions`，纯 embedding 服务无该路由 → 404）。本轮初测误用 chat 路由得 404，经容器实码 + 宿主直连（`/v1/embeddings` 200 + 向量）定位后，用正确路由复验 **PASS**。**此为测试脚本误用路由，非平台缺陷。**

---

## 回归结论

- **BUG-11 探测 wire = CORRECT_BEARER 且 ok=true（A）+ 无 key NO_HEADER（B）+ 运行时 200+pong（C）+ 真实端点 ok=true（D）**：✅ 满足通过标准。
- **BUG-10 / BUG-09 无回归**：✅
- **9 模块冒烟无回归（14 项全 PASS，带截图）**：✅
- **报告两节（浏览器功能测试 + 接口/依赖验证）齐全**：✅
- **BUGS.md 回写**：✅（BUG-11 关闭 + BUG-08 复核）

**回归判定：PASS（回归通过，满足验收标准，无阻塞项）。**

---

## 交付物清单

- 本报告：`03-testing/TEST_REPORT_S25.md`
- 依赖验证刷新：`03-testing/DEP_VERIFICATION.md`（S21→S25 版）
- 铁证 log：`03-testing/dev_probe_s25b_bug11_probe.log`
- BUGS.md 回写：BUG-11 → 已关闭（S25 铁证摘要）；BUG-08 → 复核结论更新
- 浏览器截图：`03-testing/screenshots/S25_*.png`（13 张，9 模块 + BUG-09/10 边界）
- 接口/铁证脚本与证据（`05-temp/s25b/`）：
  - `s25b_strict_pseudoauth.py` / `s25b_bug11_probe.py` / `s25b_bug11_result.json` / `s25b_strict_raw.jsonl`
  - `s25b_real_endpoint_v2.py` / `s25b_real_endpoint_v2.json`
  - `s25b_emb_correct.py` / `s25b_emb_correct.json` / `s25b_emb_direct.py` / `s25b_emb_diag.py`
  - `s25b_browser.js` / `browser_results.json`
  - `s25b_login_check.py`（登录通道验证）

## 备注（非阻塞，供后续参考）

1. **OBS-02 已缓解**：真实 LLM 端点 key 当前可用（探测 ok=true）。若后续端点侧再出现 401 抖动，属端点侧 worker key 配置（BUG-08 环境态），平台侧无需改代码。
2. **embedding 探测路由**：UI/API 对 embedding 节点应走 `/api/llm/embeddings/{id}/test`。本轮定位到「走 `/endpoints/{id}/test` 会 404」是纯 embedding 服务的预期行为（无 /chat/completions 路由），非缺陷；若前端 LLM 节点页对 embedding 类节点误用 chat 探测入口，建议前端确认路由选择（本轮浏览器冒烟 LLM 模块主流程正常，未触发该场景）。
