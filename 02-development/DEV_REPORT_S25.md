# DEV_REPORT_S25 — TASK-S25a：BUG-11 探测链路 Bearer 前缀修复 + 镜像重建部署 + 严格字节级自测

- **开发**：章北海（zhangbeihai）
- **日期**：2026-09-24
- **项目根**：`/home/hermes/hermes-workspace/projects/agent-joker`
- **任务卡**：t_342e0950（S24 终审 t_ff562cb9 打回的修复卡）
- **上游结论**：S23 回归（03-testing/TEST_REPORT_S23.md §BUG-11）+ S24 独立 byte 复核，三方一致确认唯一剩余 P1 缺陷。

---

## 1. 根因

`services/shared/joker_shared/llm/service.py` 的 `_auth_header()`（L358）对 bearer scheme 返回
**字面量 `"***" + key`**（全文件 `Bearer` 出现 0 次）：

```python
return {"Authorization": "***" + key}
```

`_probe_chat` / `probe_endpoint` / `probe_embedding` / `probe_reranker` 全部走 `_auth_header`，
因此**所有探测/嵌入/重排链路发出 `Authorization: ***<key>` 掩码值** → 对任何真实鉴权端点必 401 →
「连通性」永远判失败。S23a 修好了「取 key 通道」（`get_endpoint_internal(keep_secret)`），
但漏改了「拼 header 前缀」。agent 运行时链路走 OpenAI SDK（自行加 `Bearer `）故不受影响。

铁证（S23 捕获）：wire `len=19`，`SHA256=ca17c0ca…` == `sha256("***"+key)`。

## 2. 改动 diff

```diff
# services/shared/joker_shared/llm/service.py (L358)
-        return {"Authorization": "***" + key}
+        return {"Authorization": "Bearer " + key}
```

- **仅 bearer 分支改动**；`api_key_header` 分支（`X-API-Key: <key>`）未动。
- 部署 tag 升级：`deploy/docker-compose.yml` 中 `agent-joker-api:s23 → s25`、`agent-joker-bff:s23 → s25`
  （两镜像都 `COPY services/shared/joker_shared`，均重建；webcontainer mock 资产 s09 不动）。

### 字节级源码铁证（抗显示脱敏）

```
工作树 L358:  行 len=49
              行 SHA256=933ae99df3d24e93e2839b481077d76276897aaf6fcb7822ed9676a9d3eb5a33
              期望行 SHA256=933ae99df3d24e93e2839b481077d76276897aaf6fcb7822ed9676a9d3eb5a33  (match=True)
              全文件 "Bearer " 出现 1 次 | "***" 出现 0 次
```

## 3. 镜像重建 + 部署

- `docker compose build api bff` → `agent-joker-api:s25` / `agent-joker-bff:s25` 构建成功。
- `docker compose up -d` 重部署（清理了 2 个旧 compose 版本残留容器 `f214814b362d_joker-bff` 与旧 `joker-webconsole`）。
- **容器内铁证**（docker exec 读 `/app/joker_shared/llm/service.py`）：
  - `joker-api`：L358 行 SHA256=`933ae99d…b5a33`（match=True），`bearer_count=1 mask_count=0`
  - `joker-bff`：`bearer_count=1 mask_count=0`
- 部署状态：6 容器全 healthy（joker-api / joker-bff / joker-webconsole / joker-pg / joker-redis + mocks 在线）；
  `8080 → 200 text/html`；`bff 8000/healthz → 200`。

## 4. 严格字节级自测（QA_STANDARD §四）

方法：宿主 `127.0.0.1:9981` 严格伪鉴权（`05-temp/s25a_strict_pseudoauth.py`，BEARER 前缀用
**char-code 构建** `bytes([66,101,97,114,101,114,32])`，只接受精确 `Bearer <非空>`），对 wire
Authorization 值记录 **val_len + val_sha256**，与 `sha256("Bearer "+KEY)` **精确比对**。
**未使用任何 `("bearer" in low)` 子串判定**（S23a 误报根因）。脚本 `05-temp/s25a_bug11_probe.py`。

KEY=`qa-s25a-key-7731`
`sha256("Bearer "+KEY)` = `747c31578a31fea82596d81fd96775d2f7689574b2ffd18b2140d2afc6eb2fd3` (len=23)
`sha256("***"+KEY)`（S23 缺陷形态参照）= `09375637a17afecc5542d646f33ed1ba08190f242b484d77ba6716a10b2af872` (len=19)

| # | 场景 | 结果 | wire 铁证 | 判定 |
|---|---|---|---|---|
| A | 带 key 节点探测 `/api/llm/endpoints/{id}/test` | **200 ok=true**（27ms） | val_len=23, val_sha256=`747c3157…eb2fd3` == 期望，byte_match=True → **CORRECT_BEARER** | PASS |
| B | 无 key 节点探测（对照） | 200 **ok=false**（无 choices） | has_header=**false**, val_len=0 → NO_HEADER | PASS |
| C | agent 运行时 `/v1/chat/completions`（绑带 key 节点） | **200 + content="pong"** | val_len=23, val_sha256=`747c3157…eb2fd3`，byte_match=True → CORRECT_BEARER（不回归） | PASS |
| D | BUG-10 `/mcp/servers` SPA | 200 text/html（含深链）；`/api/mcp/servers` 401 JSON | — | PASS（无回归） |
| E | BUG-09 上传白名单 | .exe/.doc/.xls → 422；.txt → 200 落盘 | — | PASS（无回归） |

**总结论：BUG11_OVERALL_PASS = true（6/6 字节级判定通过）。**

> 过程备注：首轮自测时 9981 端口被 S23 遗留伪鉴权进程（pid 454595）占用，wire log 落入其
> 文件导致 no_capture；已 kill 该残留进程、重启 S25 伪鉴权后复跑，上表为有效证据。

## 5. 证据路径

| 证据 | 路径 |
|---|---|
| 字节级 wire 自测总日志（含 val_len+sha256 比对结论） | `03-testing/dev_probe_s25_bug11_probe.log` |
| 结构化自测结果（verdict 6 项全 true） | `05-temp/s25a_bug11_probe.py` → `05-temp/s25a_bug11_result.json` |
| wire 原始抓取（jsonl，val_len+val_sha256） | `05-temp/s25_strict_raw.jsonl` |
| 严格伪鉴权服务脚本 | `05-temp/s25a_strict_pseudoauth.py`（+ `05-temp/s25_strict_srv.out`） |
| BUG-10 回归 | `03-testing/dev_probe_s25_mcp_spa.log`（`05-temp/s25a_probe_bug10_mcp_spa.py`） |
| BUG-09 回归 | `03-testing/dev_probe_s25_upload_whitelist.log`（`05-temp/s25a_probe_bug09_upload.py`） |

## 6. BUGS.md 关单状态

**未关单。** 按任务要求，BUG-11 关单由测试 S25b 独立复验后回写 `03-testing/BUGS.md`，
开发不擅自改单。

## 7. 已知问题

- 真实 LLM 端点 `34.121.9.233:4000` 间歇 401 属端点侧环境态（S20 已定性，非代码缺陷），
  本轮自测不依赖该端点，全部经伪鉴权链路验证。
- 本地 git commit 已完成；**推远端由终审 S24 负责**。
