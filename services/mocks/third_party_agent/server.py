"""S07 E2E 用 mock 第三方 agent server（DECISION-008 协议）。

实现 OpenAI 兼容 /chat/completions + 平台回传端点 POST /tool_results：
- 请求 messages 中若已有 role=tool（平台执行工具后回填）→ 返回最终回复
  （引用该工具结果文本，供 E2E 断言 TP-FINAL / 工具 ok）；
- 否则若请求带 tools（平台把 agent 勾选的 MCP 工具以 lc_name 下发）→ 返回一个
  tool_calls（回传 tools 里给出的名字，参数带 x/echo 字段）；
- 否则（无工具）→ 直接回复 TP-NO-TOOL（AGENT-10 验收 3：不配置工具对话正常）。

状态完全由请求 messages 驱动（不依赖跨请求全局），故同一容器先后服务
「有工具 agent」与「无工具 agent」不会互相串味。
无鉴权（自测内网）。验证点：平台拦截执行 + 回传闭环 + 平台不注入记忆。
"""
from __future__ import annotations

import json
import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mock-tp-agent")


def _last_tool(messages: list) -> dict | None:
    for m in reversed(messages or []):
        if m.get("role") == "tool":
            return m
    return None


def _first_tool_name(tools: list) -> str | None:
    for t in tools or []:
        name = (t.get("function") or {}).get("name")
        if name:
            return name
    return None


async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    tools = body.get("tools") or []

    # 本轮 messages 已含工具执行结果（平台回填 role=tool）→ 最终回复（引用工具结果）
    tool_msg = _last_tool(messages)
    if tool_msg is not None:
        return JSONResponse({
            "id": "chatcmpl-mock-tp", "object": "chat.completion", "model": "mock-tp",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant",
                "content": f"TP-FINAL: tool_result={str(tool_msg.get('content'))[:200]}",
            }}],
        })

    # 平台提供了工具 → 发起 tool_call（用平台实际下发的工具名 lc_name）
    first_tool_name = _first_tool_name(tools)
    if first_tool_name:
        return JSONResponse({
            "id": "chatcmpl-mock-tp", "object": "chat.completion", "model": "mock-tp",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": "call_mocktp_1", "type": "function",
                    "function": {"name": first_tool_name, "arguments": json.dumps({"x": "tp-42", "echo": "tp-42"})},
                }],
            }}],
        })

    # 无工具 → 直接回复（AGENT-10 验收 3）
    return JSONResponse({
        "id": "chatcmpl-mock-tp", "object": "chat.completion", "model": "mock-tp",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant",
            "content": "TP-NO-TOOL: 你好，我是 mock 第三方 agent。",
        }}],
    })


async def tool_results(request: Request) -> JSONResponse:
    body = await request.json()
    log.info("tool_results received: %s", body.get("tool_results"))
    return JSONResponse({"ok": True, "received": len(body.get("tool_results") or [])})


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "module": "mock-tp-agent"})


app = Starlette(routes=[
    Route("/chat/completions", chat_completions, methods=["POST"]),
    Route("/tool_results", tool_results, methods=["POST"]),
    Route("/healthz", healthz, methods=["GET"]),
])

if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MOCK_TP_PORT", "9200")))
