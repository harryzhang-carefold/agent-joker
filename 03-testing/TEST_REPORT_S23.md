# S23 回归测试报告 — BUG-11/10/09 复验

- **测试对象**：S23a 修复（父卡 t_b259dcf6，commits `5dcaea8`/`1736cc3`/`6626472`）
- **测试人**：云天明（测试工程师）
- **日期**：2026-09-24
- **QA 标准**：`03-testing/QA_STANDARD.md` §二（浏览器 + 接口双层）、§四（伪鉴权本地服务）
- **项目根**：`/home/hermes/hermes-workspace/projects/agent-joker`
- **判定原则**：不采信开发自报，全部独立复跑；凭据类验证用 SHA256 字节级铁证（抗显示脱敏）

---

## 总体结论

**判定：FAIL（阻塞验收）**

| BUG | 严重度 | 回归结果 | 说明 |
|---|---|---|---|
| **BUG-11**（凭据发送） | P1 | ❌ **部分修复 / 回归失败** | agent 运行时链路已修好（200+pong+wire `Bearer <key>` 铁证）；**探测链路仍发 `***<key>` 掩码值，未修** |
| **BUG-10**（/mcp/servers 直连） | P1 | ✅ **已修（独立复验 PASS）** | 浏览器地址栏直连渲染 SPA，刷新/分享场景均正常 |
| **BUG-09**（上传白名单） | P2 | ✅ **已修（独立复验 PASS）** | .doc/.exe/.xls→422+友好提示、.txt→200，接口+浏览器双层一致 |

**阻塞项**：BUG-11 探测（probe）链路 P1 未关闭 → 任何需鉴权的真实 LLM/embedding/reranker 端点「连通性」永远判失败。须章北海修复后重新回归。

> **OBS-02 环境态说明**：真实 LLM 端点 `34.121.9.233:4000` 的 key 当前持续 401，属用户端点侧环境态（非代码缺陷）。本回归**不依赖**该端点做「真实 LLM 对话 200」判定，全部改用 QA_STANDARD §四 伪鉴权端点验证凭据链路。

---

## 浏览器功能测试

测试方式：headless Chromium（CDP）走真实登录 → 逐模块访问，截图佐证。脚本 `05-temp/s23_browser/s23_browser_v2.js`（M9 路由修正 `m9_fix.js`）。**关键修正**：首轮脚本登录被 SPA 路由守卫弹回 `/login`、且 M9 用错路由 `/traces`（实际 `/trace/sessions`）导致假 PASS；本轮修正登录（in-page fetch 落 localStorage）+ 逐模块内容断言 + 截图人工复核，消除假 PASS。

### 通过项（12 项，均带截图）

| # | 模块 | 结果 | 截图 |
|---|---|---|---|
| M1 | 登录（admin/acme） | PASS — in-page fetch 落 localStorage，落地 /users 用户管理表 | `S23_01_login_success.png` |
| M2 | 租户管理（admin 权限边界） | PASS — admin 访问 /tenants 弹「无权限访问租户管理，需平台管理员权限」 | `S23_02_tenant_admin.png` |
| M3a | 存储/文件列表 | PASS — 文件上传记录页渲染 | `S23_03a_files_list.png` |
| M3b | **BUG-09 上传 .doc** | PASS — el-upload 弹「unsupported file type .doc（旧 Word 格式），please convert to .docx」+ 接口 422 | `S23_03b_upload_doc_rejected.png` |
| M3c | 上传 .txt（正常） | PASS — el-upload 弹「已上传 s23q_browser.txt」+ 接口 200 落盘 | `S23_03c_upload_txt_ok.png` |
| M4 | LLM 节点 | PASS — Chat 端点 / Embedding / Reranker 列表渲染 | `S23_04_llm_endpoints.png` |
| M5 | RAG 知识库 | PASS — 知识库列表渲染 | `S23_05_rag_kbs.png` |
| M6 | **BUG-10 直连 /mcp/servers** | PASS — 地址栏直连渲染 SPA「MCP Server」列表（joker-platform 等），**无 BFF 401 JSON** | `S23_mcp_spa_fixed.png` |
| M6b | BUG-10 刷新 /mcp/servers | PASS — 刷新后仍 SPA | `S23_06b_mcp_spa_refresh.png` |
| M7 | Skills | PASS — Skill 管理页渲染 | `S23_07_skills.png` |
| M8 | Agent | PASS — Agent 维护列表渲染（含 s08-e2e-agent） | `S23_08_agents.png` |
| M9 | Trace | PASS — 修正路由 `/trace/sessions` 后渲染「Trace 会话」表（会话ID/Agent/状态/事件/Token） | `S23_09_traces.png` |

补充截图：`S23_upload_whitelist.png`（白名单场景）、`S23_09b_audit.png`（接口操作日志，trace:read 边界）。

### 未通过项（浏览器层）

| # | 项 | 关联 BUG | 说明 |
|---|---|---|---|
| — | 无 | — | 浏览器功能层 9 大模块主流程 + BUG-09/10 全部通过，无回归。BUG-11 的失败在**接口/依赖层**（探测链路），浏览器端「连通性」按钮点击后后端返回 ok=false，属接口层验证范畴。 |

> 注：BUG-11 的探测失败无法在浏览器 UI 单独呈现为「崩溃」，而是表现为「点连通性永远显示不可用」——该断言在接口层用伪鉴权铁证验证（见下节）。

---

## 接口/依赖验证

### BUG-11（P1）凭据发送 — ❌ 部分修复，探测链路回归失败（铁证）

**方法**：宿主 `127.0.0.1:9981` 起**严格伪鉴权服务**（`05-temp/s23_qa_pseudoauth_strict.py`），只接受**精确 `Bearer <非空>`** 格式，日志 `s23_qa_strict_raw.jsonl` 记录 wire Authorization 值的 **val_len + val_sha256**（SHA256 对显示脱敏免疫）。独立脚本 `05-temp/s23_qa_bug11_v2.py`，证据 `05-temp/s23_qa_bug11_v2_result.json`。

#### ① agent 运行时链路 — ✅ 已修（铁证）

| 步骤 | 结果 |
|---|---|
| 建 LLM 节点 `base_url=http://host.docker.internal:9981/v1` + `api_key=qa-s23r-key-9917` | 201 |
| 建 agent 绑该节点 | 201 |
| `POST /v1/chat/completions`（绑 agent） | **200 + content="pong"** |
| wire Authorization 值 | **len=23，SHA256=`fa633b489297aaceeab576822f29564be66c51ab1e2889e1aed357e0ad9c1d5f`** |
| 与 `"Bearer "+key` 比对 | **逐字节匹配（CORRECT_BEARER）** ✅ |

**结论**：agent 运行时（OpenAI SDK / langchain `ChatOpenAI` 路径，依赖 BUG-12 BFF FERNET_KEY 修复）正确发出 `Authorization: Bearer <key>`，对话链路已通。

#### ② 探测（probe）链路 — ❌ 仍坏（铁证）

| 步骤 | 结果 |
|---|---|
| 同 key 节点 `POST /api/llm/endpoints/{id}/test` | **200，`ok=false`（`unavailable: response has no choices`）** |
| wire Authorization 值 | **len=19，SHA256=`ca17c0ca62576ab25656241b52fd4815857295be08cce57a51e7d9f85585871c`** |
| 与 `"***"+key` 比对 | **逐字节匹配（BROKEN_MASKED）** ❌ |
| 与 `"Bearer "+key` 比对 | 不匹配 |

**结论**：探测路径发出的是 `Authorization: ***<key>`（**字面量三个星号前缀**），非 `Bearer <key>`。对任何真实鉴权端点必 401 → 「连通性」永远判失败。

#### ③ 根因定位（git blob 字节级铁证，抗脱敏）

commit `5dcaea8` 与 HEAD 均（`05-temp/s23_bytecheck2.py` 字节 dump）：

```
services/shared/joker_shared/llm/service.py:358
        return {"Authorization": "***" + key}
  字面量 *** : True   |   'Bearer ' : False
  全文件 'Bearer ' 出现次数 : 0   |   '***' 出现次数 : 1
```

`_auth_header`（L351-358）对 bearer scheme 返回 **字面量 `***` + key**。`_probe_chat`（L360+）/`probe_endpoint`/`probe_embedding`/`probe_reranker` 全部走 `_auth_header` → 探测/嵌入/重排链路发 `***<key>`。而 agent 运行时走 OpenAI SDK/langchain，自行加 `Bearer ` 前缀 → 运行时链路反而正确。**修复只改了「取 key 通道」（`get_endpoint_internal` keep_secret），漏改了「拼 header 前缀」（`_auth_header` 仍用 `***`）。**

#### ④ 开发自测误报定位

dev 的 `05-temp/s23a_host_pseudoauth.py` 判定：
```python
has_auth = ("authorization" in low) and ("bearer" in low)
```
只查 header **存在** + 含 "bearer" **子串**，**不校验 token 合法性**。其 log `03-testing/dev_probe_bug11_pseudoauth.log` 内 `auth_prefix: "***s23afakekey"` 已暴露星号前缀，但 `DEV_REPORT_S23.md` 描述为 "Bearer s23afakekey"。**这正是 QA_STANDARD 要防的「mock 全绿、真鉴权路径从未执行」**。本回归用严格伪鉴权 + SHA256 字节比对复辟了真相。

#### ⑤ 复现步骤（可复跑）

1. 宿主起严格伪鉴权：`python3 05-temp/s23_qa_pseudoauth_strict.py`（127.0.0.1:9981，只接受 `Bearer <非空>`，log `s23_qa_strict_raw.jsonl`）。
2. 跑独立脚本：`python3 05-temp/s23_qa_bug11_v2.py`（admin/acme 登录 → 建带 key 节点 → 探测 + 建 agent 对话 → 清理）。
3. 读 `05-temp/s23_qa_bug11_v2_result.json`：`analysis.probe_classified[0].class == "BROKEN_MASKED"` 且 `A_probe.ok == false` → 探测回归失败；`runtime_classified[0].class == "CORRECT_BEARER"` 且 `chat_content == "pong"` → 运行时已修。

#### ⑥ 影响

- 任何需鉴权的真实 LLM/embedding/reranker 端点「连通性」永远判失败（用户误判节点不可用）。
- agent 运行时对话已通（BUG-12 一并修复后）。
- **探测子功能未修 → BUG-11 未完整关闭。**

#### ⑦ 修复建议（探测链路）

`_auth_header`（service.py:358）对 bearer scheme 应为：
```python
return {"Authorization": "Bearer " + key}   # 当前是 "***" + key
```
统一所有走 `_auth_header` 的内部探测/嵌入/重排路径与运行时一致发 `Bearer <key>`。修后按 §⑤ 复验：A 项 `analysis.probe_classified[0].class == "CORRECT_BEARER"` 且 `A_probe.ok == true`。

---

### BUG-10（P1）/mcp/servers 直连 — ✅ 已修（独立复验 PASS）

| 步骤 | 结果 |
|---|---|
| 浏览器地址栏直连 `http://localhost:8080/mcp/servers` | 200 text/html，渲染 SPA「MCP Server」列表 |
| 刷新 `/mcp/servers` | 仍 SPA |
| `/mcp/servers/123/tools`（深链） | 200 text/html SPA |
| `/api/mcp/servers`（真 API 前缀，对照） | 401 application/json（正确代理 BFF） |

**结论**：nginx 正则收窄 `^/(api|v1)(/|$)` 生效，`/mcp/*` 前端 SPA 路由不再误代理 BFF，且收窄精确（`/api/*` 仍走 BFF）。**修复有效。** 脚本 `05-temp/s23_qa_bug10.py`，证据 `s23_qa_bug10_result.json`，截图 `S23_mcp_spa_fixed.png`/`S23_06b_mcp_spa_refresh.png`。

---

### BUG-09（P2）上传白名单 — ✅ 已修（独立复验 PASS）

| 文件 | 接口层 | 浏览器层 |
|---|---|---|
| `.doc` | 422 `unsupported file type .doc（旧 Word 格式），please convert to .docx` | el-upload 弹同款友好提示 |
| `.exe` | 422 `unsupported file type .exe, please use one of: .csv, .docx, .md, .pdf, .txt, .xlsx` | — |
| `.xls` | 422 同上 | — |
| `.md` | 200（首轮）/409（重名，自测产物，非缺陷） | — |
| `.txt` | 200 落盘（返回 id/checksum） | el-upload 弹「已上传」，列表出现新文件 |

**结论**：扩展名 allowlist（.txt/.md/.pdf/.docx/.xlsx/.csv）生效，.doc 友好提示转 .docx。**修复有效。** 脚本 `05-temp/s23_qa_bug09.py`，证据 `s23_qa_bug09_result.json`，截图 `S23_03b/03c_upload_*.png`+`S23_upload_whitelist.png`。

> 注：`s23q_good.md` 重跑 409 是「文件已存在」幂等冲突（上一轮已落盘同名），属测试脚本复用文件名的产物，非产品缺陷；.txt 用唯一名复跑 200 确认落盘正常。

---

## 其余模块防回归冒烟

9 大模块主流程各点一遍（登录/租户/存储/LLM/RAG/MCP/Skills/Agent/Trace）+ 接口操作日志（audit），**均渲染正常、无回归**（见上「浏览器功能测试」通过项）。无新引入缺陷。

---

## 待办 / 交接

1. **BUG-11 探测链路修复**（P1，阻塞）→ 交章北海：改 `service.py:358` `_auth_header` bearer 前缀 `***` → `Bearer `。
2. 修后**重新回归**（本条 §BUG-11 ⑤ 复现步骤），须 `probe_classified=CORRECT_BEARER` + `A_probe.ok=true` 方可关闭 BUG-11。
3. OBS-02（真实端点 34.121.9.233:4000 key 401）为用户端点侧环境态，不阻塞本回归判定，但完整「真实 LLM 对话 200」需用户端点侧核查 key 后复测。

## 交付物清单

- 本报告：`03-testing/TEST_REPORT_S23.md`
- BUGS.md 回写：BUG-11 改「回归失败/部分修复」，BUG-10/09 补「S23 独立复验 PASS」
- 浏览器截图：`03-testing/screenshots/S23_*.png`（12 项 + 2 补充）
- 接口/铁证脚本与证据：
  - `05-temp/s23_qa_bug11_v2.py` / `s23_qa_bug11_v2_result.json` / `s23_qa_pseudoauth_strict.py` / `s23_qa_strict_raw.jsonl`
  - `05-temp/s23_bytecheck2.py`（git blob 字节铁证）
  - `05-temp/s23_qa_bug10.py` / `s23_qa_bug10_result.json`
  - `05-temp/s23_qa_bug09.py` / `s23_qa_bug09_result.json`
  - `05-temp/s23_browser/s23_browser_v2.js` / `browser_results_v2.json` / `m9_fix.js` / `m9_fix_results.json`
