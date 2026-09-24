"""BFFGateway（S02 最小集）：PlatformMCPServer 挂载。

范围（卡 S02 第 4 项，ARCH §3.1）：
- /mcp 端点：MCP Streamable HTTP（DECISION-011），暴露平台内置三工具
  upload_doc / query_doc / rag_search（代码注册，is_platform 语义）
- 工具实现 = 薄封装：以平台机器凭证（INTERNAL_HMAC_SECRET）构造 X-Auth-* 签名头，
  代执行 PlatformAPI /internal/storage/*（DECISION-009/012）
- 工具内身份来源（ARCH §3.1：ToolInterceptor 强制注入 access_token）：
  工具入参 access_token（S08 ToolInterceptor 注入）优先；自测/BFF 直连路径
  回退到 HTTP 层 Authorization 头（contextvar）。两条路径共用同一薄封装。
- rag_search = stub 501（S05 实装；契约见 02-development/API_NOTES.md）
- 工具调用的 scope 门禁/ToolInterceptor 拦截 = S08 统一接入（D-B）
"""
