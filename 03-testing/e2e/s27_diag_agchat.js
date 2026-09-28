// S27 AGENT 诊断: 浏览器真实 LLM 对话，捕获 /chat 响应体 + 冷却防限流
const { launch, realFormLogin, shot, record, robustClick } = require('./s27_lib')
const RUN = 'agchat_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()

  // 捕获 /chat 响应体
  const chatBodies = []
  page.on('response', async (rs) => {
    const u = rs.url()
    if ((u.includes('/agents/') && u.includes('/chat')) || u.includes('/v1/chat/completions')) {
      let body = ''
      try { body = await rs.text() } catch {}
      chatBodies.push({ ts: new Date().toISOString(), method: rs.request().method(), status: rs.status(), url: u.split('8080')[1], body: body.slice(0, 500) })
    }
  })

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // 用已有 agent（绑了真实 LLM 的）：新建一个，冷却，绑 platform-fallback-llm
  const agName = 's27ag_' + RUN
  await page.goto('http://localhost:8080/agents', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)
  await robustClick(page, "button:has-text('新建 Agent')", { label: '新建' })
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  await page.locator('.el-dialog:visible input').first().fill(agName)
  await robustClick(page, '.el-dialog button:has-text("创建")', { label: '创建' })
  await page.waitForTimeout(3500)  // 冷却防限流

  // 配置：绑 platform-fallback-llm
  await robustClick(page, `.el-table__row:has-text("${agName}") button:has-text('配置')`, { label: '配置' })
  await page.waitForURL(/\/agents\/[0-9a-f-]+\/config/, { timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(2000)
  const epCb = page.locator('.el-checkbox:has-text("platform-fallback-llm")').first()
  if (await epCb.count()) await epCb.click()
  await robustClick(page, 'button:has-text("保存四要素")', { label: '保存四要素' })
  await page.waitForTimeout(3500)  // 冷却

  // 对话
  await robustClick(page, `.el-table__row:has-text("${agName}") button:has-text('对话')`, { label: '对话' })
  await page.waitForURL(/\/agents\/[0-9a-f-]+\/chat/, { timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(1500)
  await page.fill('textarea[placeholder*="输入消息"]', 'ping')
  await page.press('textarea[placeholder*="输入消息"]', 'Enter')
  let lastBubble = ''
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(3000)
    const bubbles = page.locator('.chat-bubble')
    const n = await bubbles.count()
    lastBubble = n ? await bubbles.last().textContent() : ''
    if (/pong|⚠️|401|502|failed|AuthenticationError/i.test(lastBubble)) break
  }
  await shot(page, 'agchat_reply_' + RUN)
  console.log('lastBubble:', JSON.stringify(lastBubble))
  console.log('CHAT RESPONSES:', JSON.stringify(chatBodies, null, 2))
  record({ case: 'DIAG_agent_chat', agName, lastBubble, chatBodies, screenshot: '/home/hermes/hermes-workspace/projects/agent-joker/03-testing/screenshots/s27/agchat_reply_' + RUN + '.png' })

  // 清理
  await page.goto('http://localhost:8080/agents', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const delRow = page.locator('.el-table__row', { hasText: agName }).first()
  if (await delRow.count()) {
    await robustClick(page, `.el-table__row:has-text("${agName}") button:has-text('删除')`, { label: '删除' })
    await page.waitForTimeout(500)
    const cb = page.locator('.el-message-box__btns button:has-text("确定")').first()
    if (await cb.count()) await cb.click()
    await page.waitForTimeout(1000)
  }
  await browser.close()
})().catch((e) => { console.error('DIAG AGCHAT ERROR:', e.message); process.exit(2) })
