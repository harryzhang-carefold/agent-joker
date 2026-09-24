// agent 对话 SSE 流式（经 BFF /v1/chat/completions，model=agent 名称）。
// 返回 ReadableStream 消费器：onDelta(content 增量)、onToolCalls、onUsage、onDone(session_id)。
// 兼容块式（stream=false）与流式（stream=true）两种后端。
//
// 请求体（OpenAI 兼容 + 平台扩展）：
//   { model: <agent 名>, messages:[{role:'user',content}], stream:true,
//     show_citations?:bool, session_id?:UUID（续接会话） }
//
// 流式 SSE：data: {choices:[{delta:{role/content/tool_calls}}]} ... data: [DONE]
// 块式 JSON：{ choices:[{message:{content,tool_calls}}], usage, joker:{session_id,citations} }
//
// 引用来源（citations）：块式响应带在 joker.citations；流式时最后 chunk 的 usage 块之后
// 后端不额外回传 → 前端在流结束后可选回查 /api/agents/{id}/sessions 或依赖块式。
// 为保证「引用来源展示」可靠，默认 stream=false（块式，带 citations），并提供 stream 开关。

export async function streamChat({
  accessToken,
  model,
  message,
  sessionId,
  showCitations,
  stream = false,
  onDelta,
  onToolCalls,
  onUsage,
  onSession,
  onCitations,
  onDone,
  onError,
}) {
  const body = {
    model,
    messages: [{ role: 'user', content: message }],
    stream,
  }
  if (showCitations != null) body.show_citations = showCitations
  if (sessionId) body.session_id = sessionId

  let resp
  try {
    resp = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(body),
    })
  } catch (e) {
    onError && onError('网络错误: ' + e.message)
    return null
  }

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const j = await resp.json()
      detail = j.detail || detail
    } catch {}
    onError && onError(typeof detail === 'string' ? detail : JSON.stringify(detail))
    return null
  }

  const ct = resp.headers.get('content-type') || ''

  // ---------- 块式 ----------
  if (!stream || !ct.includes('text/event-stream')) {
    const data = await resp.json()
    const choice = data.choices?.[0]
    const msg = choice?.message || {}
    onDelta && onDelta(msg.content || '')
    if (msg.tool_calls?.length) onToolCalls && onToolCalls(msg.tool_calls)
    if (data.usage) onUsage && onUsage(data.usage)
    if (data.joker) {
      onSession && onSession(data.joker.session_id)
      if (data.joker.citations) onCitations && onCitations(data.joker.citations)
    }
    onDone && onDone()
    return data
  }

  // ---------- 流式 SSE ----------
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let final = null
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE 事件以 \n\n 分隔
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const rawEvent = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        for (const line of rawEvent.split('\n')) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const payload = trimmed.slice(5).trim()
          if (payload === '[DONE]') {
            onDone && onDone(final)
            return final
          }
          try {
            const obj = JSON.parse(payload)
            const delta = obj.choices?.[0]?.delta
            if (delta?.content) onDelta && onDelta(delta.content)
            if (delta?.tool_calls?.length) onToolCalls && onToolCalls(delta.tool_calls)
            if (obj.usage) onUsage && onUsage(obj.usage)
            if (obj.joker) {
              onSession && onSession(obj.joker.session_id)
              if (obj.joker.citations) onCitations && onCitations(obj.joker.citations)
            }
          } catch {
            /* 忽略无法解析的增量 */
          }
        }
      }
    }
    onDone && onDone(null)
  } catch (e) {
    onError && onError('流读取错误: ' + e.message)
  }
  return final
}
