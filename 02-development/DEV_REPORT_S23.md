# DEV_REPORT_S23 — S23a 修复：BUG-11（凭据发送）+ BUG-10（nginx 路由）+ BUG-09（上传白名单）+ 补 QA_STANDARD 自测证据

- 任务卡：t_b259dcf6（章北海，S23a；上游 S22 终审 t_0bef5b8e 按 QA_STANDARD §三 打回）
- 部署基线：`deploy/docker-compose.yml`（`joker-api` / `joker-bff` / `joker-webconsole` / `joker-pg` / `joker-redis` + mock），本卡重建 **s23 镜像**（api/bff/webconsole 均 `:s23`）并重启，运行容器已确认含修复代码。
- 范围：按 S22 终审裁定修复 3 个 BUG，并补齐 QA_STANDARD §一「开发自测证据」（`03-testing/dev_probe_*.log`，真实 HTTP 调用落盘）。**不含** mock-only 结论改动；**不**标记任务完成（等 S22 终审回归）。
- 关键约束（S22 裁定，务必遵守）：
  1. BUG-11 脱敏只作用于「对外 API 响应」，**不**作用于「平台内部探测/运行时取 key」这条内部链路——新增内部专用取 key 通道。
  2. 绝不把明文/密文 key 写进任何日志 / API 响应 / git 文件。
  3. 保持 DECISION-012 对外脱敏不变；内部通道仅限进程内调用，不暴露为 REST。
  4. 真实 LLM 端点 34.121.9.233:4000 当前 key 持续 401（OBS-02，环境态）——**不依赖该端点**做「带 key 真实 LLM 对话 200」验证；改用 QA_STANDARD §四伪鉴权服务验证「凭据确实发出」。

## 结论（一句话）

三个 BUG 全部修复并已在运行容器上真实 HTTP 自测通过：**BUG-11**（带 key 节点探测 `ok=true` 且伪鉴权服务捕获 `has_auth=true`，无 key 对照 `has_auth=false`）、**BUG-10**（直连 `/mcp/servers` → 200 text/html SPA）、**BUG-09**（`.doc/.exe/.xls` → 422，`.txt` → 200）。自测证据 3 份 `dev_probe_*.log` 已落盘并入 git（`.gitignore` 已加例外）。

---

## 一、BUG-11（P1）— LLM 节点探测 + agent 运行时不发送已配置 api_key

### 1.1 根因（S21 已定位，S23 修复）
- `joker_shared/llm/service.py` `_row_to_node`（L48-64）：`enc = d.pop("api_key_enc", None)` 把加密 key 从 node dict **删除**，只留 `api_key_set` 布尔（对外脱敏，DECISION-012 合规）。
- `probe_endpoint`（~L431）→ `get_endpoint` → `_row_to_node` → node 里**已无 `api_key_enc`**。
- `_probe_chat`（~L348）→ `_auth_header(node.get("api_key_enc"))`（~L321）对 `None` 返回 `{}` → **探测请求不带 Authorization**。
- 连带：`joker_shared/agents/runtime.py`（~L436）`node = await llm_svc.get_endpoint(...)`；~L443-445 `if node.get("api_key_enc"): api_key = decrypt_secret(...)` **恒为 False** → `api_key=None` → `ChatOpenAI("not-needed")`。
- 现象：绑定带 key 真实 LLM 的 agent 对话必然 502 `AuthenticationError:401`；带鉴权端点永远探测失败。

### 1.2 修复（按 S22 裁定方案 A）
`joker_shared/llm/service.py`：
- `_row_to_node(row, keep_secret=False)`：默认（REST 响应）保持脱敏（`pop api_key_enc`，只留 `api_key_set`）；`keep_secret=True` 时**保留** `api_key_enc`（内部专用）。
- 新增 3 个**内部专用**取 key 方法（仅进程内调用，**绝不进任何 REST 响应**）：
  - `get_endpoint_internal(session, node_id)` → 返回含 `api_key_enc` 的 endpoint（探测 / agent 运行时取 key）。
  - `get_embedding_internal(...)` / `get_reranker_internal(...)` → 同类，供 embedding/reranker 运行时取 key。
- 内部链路改用 internal 通道：
  - `probe_endpoint` → `get_endpoint_internal`（原 `get_endpoint`）。
  - `probe_embedding` → `get_embedding_internal`；`probe_reranker` → `get_reranker_internal`。
  - `chat_completion`（内部 agent 对话入口）→ `get_endpoint_internal`。
  - `embed_texts` → `get_embedding_internal`；`rerank` → `get_reranker_internal`。
- `joker_shared/agents/runtime.py`：`node = await llm_svc.get_endpoint(...)` → `get_endpoint_internal(...)`，使 `if node.get("api_key_enc")` 命中，正常 `decrypt_secret` 注入 `ChatOpenAI`。
- **对外 REST**（`get_endpoint` / `get_embedding` / `get_reranker` 及所有 router 响应）**保持脱敏不变**（DECISION-012 合规）。明文/密文 key 不进日志/响应/git。

### 1.3 自测证据（QA_STANDARD §四 伪鉴权本地服务，真实 HTTP）
- 机制：宿主 `127.0.0.1:9981` 起裸 socket HTTP 服务（`05-temp/s23a_host_pseudoauth.py`），**强制要求 `Authorization: Bearer *** 头**，收到→`ok=true`，未收到→`ok=false`；每次请求捕获 `{has_auth, auth_prefix}`，`GET /__captured` 回传原始证据。
- 探测（`05-temp/s23a_probe_bug11_inapi.py`，在 `joker-api` 容器内经 BFF `bff:8000`）：
  - A) 建节点 `base_url=http://host.docker.internal:9981/v1` + `api_key=s23afakekey123456` → `POST /api/llm/endpoints/{id}/test`。
  - B) 建**无 key** 节点同 base → 探测（对照组）。
- 结果（run `s23a43135`，ts 2026-09-24T09:45:35Z）：
  - **A 带 key：`A_probe_response.ok=true`，伪鉴权服务捕获 `has_auth=true`（`auth_prefix=Bearers23afakekey`）** —— 凭据确实已发出。
  - **B 无 key（对照）：`ok=false`，捕获 `has_auth=false`** —— 正确区分。
  - `verdict_A_key_sent_ok=true`、`verdict_B_nokey_noauth_false=true`、`BUG11_FIXED=true`。
- **BUG-08 复核**：同一伪鉴权结果即 BUG-08「探测带鉴权头」复核 —— 带 key 发出 Authorization 且 ok，**BUG-08 凭据发送路径现已生效**（S20 时未生效的正是此链路）。
- 落盘：`03-testing/dev_probe_bug11_pseudoauth.log`。
- **真实端点 34.121.9.233:4000 说明**：该 key 当前持续 401（OBS-02 环境态，需用户端点侧核查），**不**用作「带 key 真实 LLM 对话 200」验证（QA_STANDARD 允许的伪鉴权方式已充分证明「凭据确实发出」）。

---

## 二、BUG-10（P1）— 直连/刷新 `/mcp/servers` 命中 BFF 401 JSON，SPA 未渲染

### 2.1 根因
- `deploy/nginx/nginx.conf:43`：`location ~ ^/(api|v1|mcp)(/|$)` 把**前端 SPA 路由** `/mcp/*`（MCP Server 管理页）也代理给了 BFF → 浏览器直连/刷新 `http://host:8080/mcp/servers` 命中 BFF 401 JSON，SPA 不渲染。
- BFF 的 MCP REST 实际都在 `/api/mcp` 下（前端 `api/mcp.js`）；`/mcp` 是 vue-router 的 SPA 前端路由，**不应**进 BFF。BFF 平台 MCP Streamable 端点（仅 docker 网络内 `bff:8000/mcp` 访问）不经 webconsole 反代。

### 2.2 修复
- `deploy/nginx/nginx.conf`：正则从 `^/(api|v1|mcp)(/|$)` 收窄为 **`^/(api|v1)(/|$)`**，移除 `/mcp` 分支（最小改动，仅代理真正 API 前缀）。
- 前端 MCP API 走 `/api/mcp`（不受影响）；SPA 路由 `/mcp/*` 现由 `location / { try_files ... /index.html; }` fallback 渲染。
- 前端 `frontend/src/views/storage/FilesView.vue` `accept` 属性与 BUG-09 白名单对齐（去掉 `.png/.jpg`，改为 `.txt,.md,.docx,.xlsx,.pdf,.csv`）——纯前端选择框提示，非强制（强制在后端）。

### 2.3 自测证据（真实 HTTP，webconsole 宿主 8080）
- 脚本 `05-temp/s23a_probe_bug10_mcp_spa.py`：`curl -s -o /dev/null -w '%{http_code} %{content_type} %{size_download}'` 直连。
- 结果：
  - `/mcp/servers` → **200 text/html**（body 为 `<!DOCTYPE html> ... agent-joker WebConsole` SPA 壳）。
  - `/mcp/servers/123/tools` → 200 text/html；`/` → 200 text/html。
  - `verdict_mcp_spa_200_html=true`、`BUG10_FIXED=true`。
- 落盘：`03-testing/dev_probe_mcp_spa.log`。

---

## 三、BUG-09（P2）— 上传 `.doc/.exe/.xls` 未 422 拒绝

### 3.1 根因
- `services/api/app/routers/storage.py` `upload_file` **无扩展名白名单校验**，任意扩展名 200 落盘。
- 说明：RAG 知识库文档上传（`/api/rag/kbs/{id}/docs`）走 `joker_shared/rag/parser.SUPPORTED_TYPES`（含 png/jpg），与存储模块白名单**不共用**；本处只约束存储模块（通用文件存储），RAG 文档解析路径互不影响。

### 3.2 修复
- `services/api/app/routers/storage.py`：新增 `ALLOWED_UPLOAD_EXTS = {.txt .md .pdf .docx .xlsx .csv}`（按 FEATURES P2-2 裁定）+ `_check_upload_ext()`，`upload_file` 入口调用：
  - 白名单内 → 放行。
  - `.doc` → 422，detail「unsupported file type .doc (旧 Word 格式), please convert to .docx」。
  - 其他非白名单（`.exe/.xls` 等）→ 422，detail「unsupported file type <ext>, please use one of: ...」。
  - 无扩展名 → 422。
- 前端 `FilesView.vue` `accept` 同步对齐（见 2.2）。

### 3.3 自测证据（真实 HTTP，webconsole→bff→api 全链路 multipart）
- 脚本 `05-temp/s23a_probe_bug09_upload.py`：登录 acme admin → `POST /api/storage/files?source=api`（multipart）。
- 结果：
  - `s23_bad.doc` → **422**（`.doc 请转 .docx`）。
  - `s23_bad.exe` → **422**；`s23_bad.xls` → **422**。
  - `s23_good_<run>.txt` → **200**（返回 id/checksum/upload_record_id）。
  - `verdict_doc_422 / exe_422 / xls_422 / txt_200` 全 true、`BUG09_FIXED=true`。
- 落盘：`03-testing/dev_probe_upload_whitelist.log`。

---

## 四、改动文件清单（本次提交）
| 文件 | 改动 | BUG |
|---|---|---|
| `services/shared/joker_shared/llm/service.py` | `_row_to_node(keep_secret)` + 3 个 internal 取 key 方法；探测/对话/embedding/rerank 内部链路改走 internal 通道 | BUG-11 |
| `services/shared/joker_shared/agents/runtime.py` | agent 运行时取节点改 `get_endpoint_internal` | BUG-11 |
| `deploy/nginx/nginx.conf` | 正则 `^/(api\|v1\|mcp)` → `^/(api\|v1)`（移除 /mcp SPA 路由误代理） | BUG-10 |
| `frontend/src/views/storage/FilesView.vue` | `accept` 对齐存储白名单 | BUG-09/10 |
| `services/api/app/routers/storage.py` | 扩展名 allowlist 校验（`.doc/.exe/.xls`→422） | BUG-09 |
| `deploy/docker-compose.yml` | 镜像 tag `s17` → `s23`（api/bff/webconsole） | 部署 |
| `.gitignore` | 加 `!03-testing/dev_probe_*.log` 例外（自测证据入 git） | 自测证据 |
| `.dockerignore` | 构建上下文瘦身（排除 node_modules/.git/测试文档产物，避免进 docker build） | 部署 |

> 说明：`.dockerignore` 与 `deploy/docker-compose.yml` 的镜像 tag 改动为 s23 重建镜像所需，随本次修复一并纳入。

## 五、自测证据（QA_STANDARD §一 落盘）
| 证据 | 路径 | 关键结果 |
|---|---|---|
| BUG-11 伪鉴权 | `03-testing/dev_probe_bug11_pseudoauth.log` | 带 key `has_auth=true`+`ok=true`；无 key `has_auth=false`+`ok=false`；`BUG11_FIXED=true` |
| BUG-10 SPA | `03-testing/dev_probe_mcp_spa.log` | `/mcp/servers` 200 text/html；`BUG10_FIXED=true` |
| BUG-09 白名单 | `03-testing/dev_probe_upload_whitelist.log` | `.doc/.exe/.xls` 422；`.txt` 200；`BUG09_FIXED=true` |
| 复现脚本 | `05-temp/s23a_probe_bug11_inapi.py` / `s23a_probe_bug10_mcp_spa.py` / `s23a_probe_bug09_upload.py` / `s23a_host_pseudoauth.py`（05-temp gitignore，不入 git） | 可复跑 |

## 六、已知问题 / 环境态（非本卡范围）
- **OBS-02（环境态）**：真实 LLM 端点 `34.121.9.233:4000` 当前 key 持续 401（S20 时同 key 宿主直连可拿 200，现已恶化为全 401，疑似 key 轮换/失效或端点侧 LB 后 worker 全部未配 `--api-key`）。**需用户在端点侧核查 key 是否仍有效**。本卡用伪鉴权服务验证「凭据确实发出」，不依赖该端点；端点 key 恢复后，绑定带 key 真实 LLM 的 agent 对话即可 200。
- 真实 embedding 端点（34.64.61.208:4000/v1, gte-qwen2, dim=3584）无鉴权要求，S21 已验证可达（不受 BUG-11 影响）。

## 七、部署
- `deploy/docker-compose.yml`：api/bff/webconsole 镜像 tag 升至 `:s23`。
- 重建并重启：`docker compose up -d --build api bff webconsole`（本次 s23 镜像已由 S23a run 构建；运行容器已确认含 `get_endpoint_internal` / `_check_upload_ext` / 收窄后 nginx 正则）。
- 验证：`docker compose ps` 7 容器 healthy；`joker-webconsole` 内 `location ~ ^/(api|v1)(/|$)`；`joker-api` 内 `/app/joker_shared/llm/service.py` 含 internal 方法、`/app/api/app/routers/storage.py` 含 `_check_upload_ext`。
- 台账：本次为已有服务（joker-* 容器）版本升级，无新增组件/端口/项目关系变更，`SERVER_REGISTRY.md` 无需新增行（joker 服务此前已登记）。

## 八、QA_STANDARD 合规自检
- §一 开发自测：3 个修改接口（LLM 探测 / 存储上传 / MCP SPA 入口）均真实 HTTP 调用一次并通过，证据落盘 `dev_probe_*.log` ✓
- §一 外部依赖：LLM 节点用「伪鉴权本地服务」（强制 Authorization）验证凭据发出，非 mock ✓
- 明文/密文 key 未进任何日志/响应/git 文件（`dev_probe_bug11` 仅记 `auth_prefix=Bearers23afakekey` 前 14 字符，为测试用假 key）✓
- 真实端点 401 标注为环境态 OBS-02，不据此下「带 key 真实 LLM 对话 200」结论 ✓
