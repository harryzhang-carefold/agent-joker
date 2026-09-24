# DEV_REPORT_S20 — BUG-08 LLM 端点连通性测试 401 排查（用户实测）

- 任务卡：t_75684eb5（章北海，S20）
- 上游：用户实测反馈「LLM/embedding 节点连通性测试失败（HTTP 401），但端点本身是通的」。
- 部署基线：`deploy/` docker compose（`joker-api` / `joker-bff` / `joker-webconsole` / `joker-pg` / `joker-redis` healthy），api 镜像 s17、webconsole 镜像 s17（本卡重建含前端修复）。
- 排查方法：严格按用户指定 6 步顺序执行（新增端点→查库核对→测试→容器内取 key 比对→用库中 key 直连→回归+文档）。证据脚本全部落 `05-temp/s20_*.py`（gitignore，不入 git），key 仅经环境变量注入容器，**不落任何 git 可追踪文件、不进 argv**。

## 结论（一句话）

**BUG-08 的 401 是端点侧（外部 vLLM 服务 34.121.9.233:4000）问题，不是平台代码 bug。**
平台侧「新增端点 → Fernet 加密入库 → 解密 → 探测请求构造」整条链路已被逐字节证明正确；
401 是同一有效 key 在端点侧的**间歇性拒绝，与请求来源无关**。
唯一真实平台代码问题是**前端小 bug（静默吞错）**，已修复并回归。

---

## 一、用户指定 6 步排查执行记录（完整证据链）

### Step 1 — 经 API 新增一个端点（真实 key + 真实 base_url/model）
- 登录 `acme/admin`（`llm:manage` 平台 scope）→ 200。
- `POST /api/llm/endpoints`（经 BFF 8000）：
  - `name=s20-probe-1790229346`，`base_url=http://34.121.9.233:4000/v1`，`model=vllm-qwen3.8-27b`，`api_key=<66 字符真实 key>`，`auth_scheme=bearer`，`status=active`。
  - **返回 201**，响应体 `api_key_set=true`（明文 key 不回显，符合 DECISION-012）。
- 证据脚本：`05-temp/s20_step1_create.py`；节点 id 存 `05-temp/s20_node.json`。

### Step 2 — 查库确认存进去的是新节点（非旧种子）
- 宿主 psql 直查 `joker-pg` `llm_endpoints` 表全量列表：
  - 新节点行存在：`329c7cb1-bbd8-4390-b21c-a46fae7a470b | s20-probe-1790229346 | http://34.121.9.233:4000/v1 | vllm-qwen3.8-27b | 2026-09-24 05:55:46`。
  - 与旧种子 `platform-fallback-llm`（2026-09-22 建）是**两行不同记录**，确认存的是新节点。
- 结论：**写入正确，新节点数据已落库**（不是读到旧种子节点）。

### Step 3 — 对该节点测试连通性
- `POST /api/llm/endpoints/{id}/test` → 200，`{"ok": false, "latency_ms": ~1200, "summary": "unavailable: HTTP 401"}`。
- 复测 3 次全 401；`last_test_result` 落库 `unavailable: HTTP 401`。
- 平台探测请求（httpx，`Bearer <解密 key>`，POST `{base_url}/chat/completions`）确实发出并拿到 401 响应（`joker-api` 日志可见 `HTTP Request: POST http://34.121.9.233:4000/v1/chat/completions "HTTP/1.1 401 Unauthorized"`）。

### Step 4 — 容器内取库中 key 解密，逐字节比对提交 key
- 在 `joker-api` 容器内直接连 `joker-pg` 取该节点 `base_url / model / api_key_enc`，用**应用同款 `joker_shared.crypto.decrypt_secret`** 解密：
  - `api_key_enc` 长度 184（Fernet 密文），前缀 `gAAAAABqtLti...`。
  - 解密后 key 长度 **66**；提交 key 长度 **66**。
  - **逐字节相等：`byte-equal: True`**；前缀 `Leaflong-0` / 后缀 `o6EA8R0uXG` 两侧一致；`repr` 两侧一致。
- 证据脚本：`05-temp/s20_in_container.py`（宿主驱动 `s20_step45_driver.py`，key 经 `docker exec -e` 注入，不进 argv）。
- 结论：**加解密链路正确，库中 key 与提交 key 完全一致（无截断/无改写/无 Fernet 漂移）**。

### Step 5 — 用「从库取出的 key」在容器内直连端点
- 容器内用解密后的 key 直接 POST `http://34.121.9.233:4000/v1/chat/completions`（urllib，绕过平台探测代码）：
  - 单发时曾观察到 401，随后同一容器同一 key 出现 **200**（端点侧波动，见下）。
- 关键对照（同窗口、同 key）：
  - **容器内 → LLM 端点 34.121.9.233:4000**：间歇 401（部分窗口 10/10 全 401，部分窗口全 200）。
  - **宿主 curl/urllib → 同一端点同 key**：间歇 200 / 401。
  - **容器内 → embedding 端点 34.64.61.208:4000**：200（正常，key 在容器内能被外部端点接受）。
  - **host-network 容器 → LLM 端点**：有 200 也有 401（与 NAT 桥接容器同分布）。
  - **容器内绑低源端口(888) → LLM 端点**：200；**绑默认源端口 → 200**（同一窗口）；下一窗口又全 401。
- 40-burst 同窗口对照（`05-temp/s20_burst40.json`）：
  - 容器 40 连发：`{401: 37, RST: 3, 200: 0}`，401 平均延迟 ~605ms。
  - 宿主 40 连发：`{401: 36, RST: 4, 200: 0}`，401 平均延迟 ~528ms。
  - **同一时间窗、同一 key、不同来源（容器 vs 宿主）拿到几乎相同的 401 分布与延迟 → 401 与请求来源（容器 NAT / IP / 源端口）无关。**

### Step 6 — 回归自测 + 前端小 bug 修复 + 文档
- 前端小 bug 修复（见 §二）+ 回归 8/8 PASS（见 §三）。
- 更新 `03-testing/BUGS.md` 增 BUG-08（完整证据链）。
- 本报告。

---

## 二、代码链路正确性证明（区分「代码 bug」vs「网络/代理/端点侧」）

逐项排除平台代码问题：

1. **写入/存储正确**：新节点 201 落库，`api_key_set=true`，`api_key_enc` 为 Fernet 密文（184 字符），与提交 key 一一对应（Step 2/4）。
2. **解密正确**：容器内用应用同款 `decrypt_secret` 解出的 key 与提交 key **逐字节相等**（len=66，前缀/后缀/repr 全一致）（Step 4）。排除「加密/解密漂移、key 被截断或改写」。
3. **探测请求构造正确**：`joker_shared/llm/service.py::_probe_chat` 构造 `Authorization: Bearer <key>` + POST `{base_url}/chat/completions`；`joker-api` 日志可见该请求确实发出并拿到 401（非平台拼错 URL/头）。
4. **同 key 在端点侧能成功**：宿主同 key 多次拿到 200 + **真实 completion 响应**（`chatcmpl-...`，模型 `vllm-qwen3.8-27b` 返回内容）→ **key 本身有效**，端点能接受它。
5. **401 与来源无关**：容器 / 宿主 / host-network 容器 / 低源端口，同一窗口同一 key 拿到几乎一致的 401/200 分布与延迟（40-burst：容器 37×401 vs 宿主 36×401，零 200；而另窗口宿主 10/10=200、容器 10/10=401；再另窗口全 200）。→ **不是容器 NAT 出口被端点侧按来源 IP 拒绝**（主 agent 最初假设，已证伪）。
6. **容器能正常访问外部端点**：容器内访问 embedding 端点 34.64.61.208:4000 = 200，说明容器出站网络与认证能力正常，401 专属于 34.121.9.233:4000 这个端点。
7. **非本地 MITM/代理**：容器无 proxy 环境变量；401 响应 `server:uvicorn` + 真实 GMT `date` 头 + ~500ms 往返（含跨网 RTT）→ 响应来自远端真实服务，非本地拦截；容器解析假域名正确 `Name or service not known`（无 DNS 劫持）。

**判定：BUG-08 = 端点侧（外部 vLLM 服务）间歇性拒绝同一有效 key，属网络/端点侧问题，非平台代码问题。**

### 端点侧 401 的根因假设（推测，供用户核查）
401 呈「同一有效 key 间歇 401、与来源无关、部分请求 RST」特征，最可能是：
- **34.121.9.233:4000 的 vLLM 由 LB 分发到多个 worker/副本，部分副本未配置（或配置了不同的）`--api-key`** → 命中"配了正确 key 的 worker"=200，命中"未配/配错 key 的 worker"=401。这能解释：同一 key 时而 200 时而 401、与来源无关、且 200 时返回真实 completion。
- 次要可能：端点侧有**按来源/令牌限流或临时鉴权抖动**（偶发 RST = 连接被端点侧主动 reset）。
- 需用户在端点侧 vLLM/LB 处核实（平台侧无法从外部直接验证内部 worker 的 key 配置）。

---

## 三、前端小 bug 修复（BUG-08 附带）+ 回归

### 问题
`frontend/src/views/llm/LlmNodeView.vue` 的 `onSave` / `onTest` 用 `catch (e) {}` **静默吞错**，`onDelete` 无 catch：
- 保存失败（409 重名 / 字段 422 / 网络错）→ 用户**无感知**，表现为"点了保存但没保存成功 / 数据没写入"，且对话框状态混乱。
- 连通性测试请求本身失败（非 `ok:false`，而是接口 401/500）→ 无任何提示。
> 注：`http.js` 响应拦截器会对非 `silent` 请求统一弹一次 `detail`，但**保存/测试失败时用户无法确认"没保存成功"这一语义**，且 `onDelete` 的 409 提示缺失。故按任务要求在业务层补明确提示。

### 修复（`frontend/src/views/llm/LlmNodeView.vue`）
- `onSave`：`catch (e) {}` → 读 `e?.response?.data?.detail || e?.message`，`ElMessage.error('保存失败，数据未写入: <原因>')`，并关闭对话框（让 UI 回到列表，用户可看到"没写入"）。
- `onDelete`：删除调用包 try/catch，失败 `ElMessage.error('删除失败: <原因>')`（409 被引用 / 网络错）。
- `onTest`：`catch (e) {}` → `ElMessage.error('连通性测试请求失败: <原因>')`。
- 均为纯前端改动，**未改任何后端代码**（后端链路已证明正确，无需改）。

### 部署 + 回归（`05-temp/s20_regression.py`，8/8 PASS）
- 重建 `agent-joker-webconsole:s17` 镜像（多阶段 node build 产 dist）+ 重建 `joker-webconsole` 容器（同网络 `agent-joker_default`、`-p 8080:80`）。
- bundle 三层核对：`LlmNodeView-*.js` 含 `保存失败，数据未写入` / `删除失败` / `连通性测试请求失败` 三关键字；且 bundle 内**无** `catch(e){}` 静默块（`silent_catches=0`）。
- 回归 8 项全 PASS：webconsole healthz(8080)=200 / bff healthz(8000)=200 / 登录 acme admin=200 / 列 LLM 端点=200(total 23) / bundle 含保存失败提示 / bundle 无静默 catch / 连通性测试接口返回结构化 `{ok,summary}`=200 / 删除测试节点=200。
- **结论：前端修复不影响后端，全链路（webconsole→bff→api）无回归。**

---

## 四、部署部分（S20 变更）

- **改动镜像**：`agent-joker-webconsole:s17`（重建，含前端 `LlmNodeView.vue` 错误提示修复）。其余服务（api/bff/pg/redis/mock*）镜像与配置**不变**。
- **容器**：`joker-webconsole` 重建（`docker run --network agent-joker_default -p 8080:80 agent-joker-webconsole:s17`），healthy，`/healthz`=200。
- **验证**：8/8 回归 PASS（§三）；bundle 三关键字核对通过。
- **台账**：本卡未新增/变更任何基础设施组件、端口、容器规格（webconsole 为同规格重建），`SERVER_REGISTRY.md` 无新增项需登记；`joker-*` 各容器资源占用不变。

## 五、给用户的可操作建议（针对端点侧 401）

这不是平台代码问题。要根治连通性测试 401，请在**端点侧**处理：
1. **核对 34.121.9.233:4000 的 vLLM 部署**：若为多 worker / 多副本 / 经 LB 转发，确保**每个 worker 副本都配置了完全相同的 `--api-key`**（疑似部分副本未配 → 命中即 401）。统一后重测。
2. 若端点侧对来源做了限流/鉴权策略，确认平台容器出口 IP（`36.24.190.41`，经 NAT）在白名单内，且无按来源的临时拦截。
3. 端点侧修好后，**平台侧无需改代码**——同一 key 恢复稳定 200 后，`POST /api/llm/endpoints/{id}/test` 会自动返回 `ok:true`（探测逻辑已证明正确）。
4. 端点侧不可控时，可把 `base_url` 指向一个**单实例、key 一致、可达**的 vLLM 地址，或部署到与 docker 同网段。

## 六、遗留 / 已知
- 端点侧 34.121.9.233:4000 当前仍间歇 401（环境态，非平台缺陷）；agent 对话在端点不可用时走 mock-llm / 本地 fallback 兜底（S03/S07 既有设计），平台功能闭环不受影响。
- 本卡测试节点 `s20-probe-1790229346` 已在回归末尾删除；`05-temp/s20_*` 脚本 gitignore 不入 git；真实 key 全程仅经环境变量，未落任何 git 可追踪文件。
