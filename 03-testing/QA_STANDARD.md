# QA 验收标准（用户 2026-09-24 拍板，全体 dev-team 强制遵守）

> 背景：BUG-08（LLM 连通性探测不带 API key → 真实端点 401）在 S12 测试、S13 验收、
> 以及开发自测中**全部漏检**，根因是三个阶段都只用 **mock 端点**（不需要鉴权），
> 真实的鉴权路径从未被执行过。本标准即为杜绝此类"mock 全绿、真端点必挂"。

## 一、开发自测（开发本人，每个接口）
1. **每个新增/修改的接口，开发必须实际调用一次并通过**（不能只写单测断言、不能只靠 mock）。
   调用方式 = 真实 HTTP 请求打到本服务（docker compose 环境），记录：
   - 请求方法/路径/关键入参
   - 响应状态码 + 关键响应字段
   - 落盘到 `03-testing/dev_probe_<接口>.log`（可复用 curl / python httpx 脚本）
2. **涉及外部依赖（LLM 端点 / embedding / 云存储 / 第三方 MCP / 第三方 Agent）的接口，
   必须至少用一个"带鉴权或带真实行为"的目标验证**，不能只用 mock。
   - 无真实端点可用时，必须自建一个**会拒绝未鉴权请求**的本地捕获/校验服务（如本地
     HTTP 服务强制要求 Authorization 头），验证"鉴权头/凭据确实被发送且生效"。
   - mock 只用于"功能逻辑"验证，**不能替代"凭据/鉴权/真实协议"验证**。
3. 自测通过前不得标记任务完成；自测证据（脚本+日志）必须随 DEV_REPORT 一起提交。

## 二、测试（测试人员，浏览器 + 接口双层）
1. **浏览器功能测试（强制）**：测试必须通过浏览器对每个用户可见功能实际操作一遍，
   不能只用接口脚本替代。记录到 `03-testing/BROWSER_TEST.md`：
   - 每个功能页：操作步骤 + 关键截图（`03-testing/screenshots/<功能>.png`）
   - 成功路径 + 至少一条失败/边界路径（错误提示是否符合预期）
   - 覆盖登录/登出、各模块主流程、以及本次修复涉及的所有页面
2. **接口层**：对开发自测中"外部依赖类"接口，测试必须复跑"真实/伪鉴权"验证，
   确认与开发自测一致（防止开发自测造假或环境漂移）。
3. 测试报告 `TEST_REPORT.md` 必须分两节：`## 浏览器功能测试` 与 `## 接口/依赖验证`，
   各列"通过项 / 未通过项"，未通过项关联 BUG 编号。

## 三、验收（PM/验收人）
1. 验收**不得仅凭 mock 环境或单一环境的绿**下结论。
2. 验收必须核对：
   - 开发自测证据存在且覆盖全部新增接口
   - 浏览器测试报告存在且有截图佐证
   - 涉及外部依赖的功能有"真实/伪鉴权"验证记录
   - BUGS.md 中 P0/P1 全部关闭
3. 以上任一缺失 → 验收打回，不得标记交付。

## 四、"伪鉴权本地服务"最小模板（开发/测试共用）
本地起一个要求 Authorization 头的 HTTP 服务（或 nginx 加 `auth_request`），
用它验证"平台确实发出了凭据"。示例（python，容器内 127.0.0.1）：
```python
import socket, threading, json
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 9980)); srv.listen(5)
def handle(c):
    try:
        data=b""
        while b"\r\n\r\n" not in data:
            ch=c.recv(65536)
            if not ch: break
            data+=ch
        has = b"Authorization: Bearer " in data
        body = json.dumps({"ok": has,
              "choices":[{"message":{"role":"assistant","content":"pong"}}] if has else []
              }).encode()
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "+str(len(body)).encode()+b"\r\n\r\n"+body)
    finally:
        c.close()
while True:
    c,_=srv.accept(); threading.Thread(target=handle,args=(c,)).start()
```
指向它的节点探测：返回 ok=有 Authorization 即通过；若 ok=false（无鉴权头）→ 证明凭据没发出。

## 五、责任与记录
- 开发：自测证据缺失/造假 → 任务打回并重跑。
- 测试：浏览器测试缺失（无截图）→ 测试报告无效，打回。
- 验收：按第二节清单逐项核对，缺一项即打回。
- 每次交付在 `DELIVERY_REPORT.md` 末尾附一节 `## QA 证据清单`，列出：
  开发自测日志 / 浏览器测试报告 / 截图 / 依赖验证记录 的路径，供用户抽查。
