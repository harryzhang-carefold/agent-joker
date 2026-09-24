"""S07/S11/S12 用 mock LLM server（OpenAI 兼容 /chat/completions）。

用途：真实 27B 端点不可用（环境态 401）时，闭环验证 SAR tool-calling loop、
引用强制、多轮、附件、记忆沉淀等 S07 验收点（card 允许「mock LLM 或真实 27B」）。
行为（确定性、无真实推理）：
- 收到 messages 中若已有 role=tool（说明上一轮发了 tool_call 并被平台执行回传）
  → 返回最终内容：把工具回传内容回显进回复（含 "hello-s07" 供 E2E 断言）。
- 否则（第一轮）：
  - 用户消息含 "s07_echo" → 返回一个 tool_calls（name=s07_echo, args.x=hello-s07）。
  - 用户消息含 "退款" → 返回一段引用知识库的客服回答（引用 markdown 由平台按
    is_official 强制附加，mock LLM 只出正文）。
  - 用户消息含 "记忆"/"之前" → 返回「我记得你之前问过…」类内容。
  - 其余 → 固定简单回答。
无鉴权（自测内网）。端口 MOCK_LLM_PORT（默认 9300）。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mock-llm")


def _content_of(messages: list) -> str:
    """取最近一条 user 消息文本。"""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            return ""
    return ""


def _last_tool_message(messages: list) -> dict | None:
    for m in reversed(messages or []):
        if m.get("role") == "tool":
            return m
    return None


def _finish() -> str:
    return "stop"


def _usage(prompt_tokens: int = 40, completion_tokens: int = 30) -> dict:
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    tools = body.get("tools") or []
    log.info(
        "chat_completions: user=%r tools=%s tool_msgs=%d",
        _content_of(messages)[:80],
        [(t.get("function") or {}).get("name") for t in tools],
        sum(1 for m in messages if m.get("role") == "tool"),
    )
    cid = f"chatcmpl-mock-{uuid.uuid4().hex[:8]}"
    tool_msg = _last_tool_message(messages)

    # 第一轮 + 用户要求调用 s07_echo → 发 tool_call（验证 SAR tool-calling loop）
    # SAR 把工具名映射为 mcp_<server>_<tool>（DECISION-008 标识去冒号），故按后缀匹配；
    # 且 LLM 回传的 function.name 必须 = tools 里给出的名字（SAR 据此映射回 tool_id）。
    # 通用 echo 工具触发（S07=s07_echo / S09=s09_echo / …）：
    # lc_name 形如 mcp_<uuid>_<tool>（DECISION-008，UUID 无下划线）；
    # 取 mcp_ 之后、首个下划线之后的段作 base 名（如 s09_echo）；用户消息含 base 名 → 发 tool_call。
    echo_tool = next(
        ((t.get("function") or {}).get("name")
         for t in tools
         if (t.get("function") or {}).get("name", "").endswith("_echo")),
        None,
    )
    if tool_msg is None and echo_tool:
        rest = echo_tool.split("mcp_", 1)[1] if echo_tool.startswith("mcp_") else echo_tool
        base = rest.split("_", 1)[1] if "_" in rest else rest  # <uuid>_<tool> → <tool>
        user = _content_of(messages)
        if base in user:
            # 优先回显用户消息中形如 x-y（字母数字连字符）的值（如 trace-s09-test / hello-s07）；
            # 否则取第一个非工具名 token。
            arg_val = "hello"
            m = re.search(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b", user)
            if m:
                arg_val = m.group(0)
            else:
                for tok in user.split():
                    if tok != base and "echo" not in tok:
                        arg_val = tok
                        break
            return JSONResponse({
                "id": cid, "object": "chat.completion", "model": "mock-llm",
                "choices": [{
                    "index": 0, "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant", "content": "",
                        "tool_calls": [{
                            "id": f"call_mock_{uuid.uuid4().hex[:8]}", "type": "function",
                            "function": {"name": echo_tool, "arguments": json.dumps({"x": arg_val})},
                        }],
                    },
                }],
                "usage": _usage(50, 10),
            })

    # 已收到工具回传 → 最终回复（含工具结果，供 E2E 断言 "hello-s07"）
    if tool_msg is not None:
        result_text = (tool_msg.get("content") or "")[:200]
        return JSONResponse({
            "id": cid, "object": "chat.completion", "model": "mock-llm",
            "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant",
                            "content": f"工具执行完成，回显结果如下：{result_text}"},
            }],
            "usage": _usage(60, 40),
        })

    # 第一轮普通回答（按主题分派）
    user = _content_of(messages)
    if "退款" in user or "签收" in user:
        content = (
            "根据知识库中的官方退款政策：订单签收后 7 天内可无理由退款，"
            "超过 7 天需联系客服处理，特殊商品除外。"
        )
    elif "记忆" in user or "之前" in user:
        content = "我记得你之前咨询过退款政策（签收后 7 天内可无理由退款）。"
    else:
        content = "好的，我已经收到你的消息，有什么可以帮你的？"

    return JSONResponse({
        "id": cid, "object": "chat.completion", "model": "mock-llm",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": _usage(),
    })


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "module": "mock-llm", "ts": int(time.time())})


app = Starlette(routes=[
    Route("/chat/completions", chat_completions, methods=["POST"]),
    Route("/v1/chat/completions", chat_completions, methods=["POST"]),
    Route("/healthz", healthz, methods=["GET"]),
    Route("/v1/healthz", healthz, methods=["GET"]),
])

if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MOCK_LLM_PORT", "9300")))
