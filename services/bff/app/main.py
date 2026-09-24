"""BFFGateway 应用入口（S08 统一网关）：
  ① 限流（DECISION-013）② 统一 JWT 鉴权+黑名单（BFF-01/DECISION-002）③ 身份提取
  ④ 配置化路由转发（BFF-03/DECISION-014）⑤ OpenAI 兼容（BFF-04/DECISION-016）
  ⑥ ToolInterceptor 统一动作链 + 平台 MCP 对外暴露（BFF-06/07）。

启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
（Dockerfile.bff；SAR 运行时与拦截器同容器组共享 joker_shared 库，DECISION-015/018。）
"""
from __future__ import annotations

import logging

from app.gateway import create_app
from joker_shared.config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = create_app()
