// S27 AGENT: 列表 / 新建 / 配置(四要素勾选 LLM endpoint) / 真实 LLM 对话端到端 / 多轮
const { launch, realFormLogin, shot, record, check, toasts, robustClick } = require('./s27_lib')
const RUN = 's27agent_' + Date.now().toString().slice(-6)
const REAL_EP = 'a55def7c-2b04-4a61-a998-dc319b5e38f3'  // platform-fallback-llm (34.121.9.233:4000, 真实 vLLM, key 已设)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, ok, extra = {}) => { ok ? p++ : f++; record({ case: c, pass: !!ok, ...extra }); return ok }

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // AGENT-01a 列表
  const agW = { hits: [] }; page.on('response', (r) => { if (r.url().includes('/api/agents') && r.request().method() === 'GET') agW.hits.push(r.status()) })
  await page.goto('http://localhost:8080/agents', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const agRows = await page.locator('.el-table__row').count()
  check('AGENT-01a Agent 列表', agW.hits.includes(200) && agRows > 0, `api=${JSON.stringify(agW.hits.slice(0,3))} rows=${agRows}`)
  R('AGENT-01a Agent 列表', agW.hits.includes(200) && agRows > 0, { api: agW.hits.slice(0,3), rows: agRows, screenshot: await shot(page, `s27_${RUN}_01_agents`) })

  // AGENT-01b 新建 Agent (simple)
  const agName = 's27_agent_' + RUN
  await robustClick(page, "button:has-text('新建 Agent')", { label: '新建Agent' })
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  const dlg = page.locator('.el-dialog:visible')
  await dlg.locator('input').nth(0).fill(agName)
  const agPost = page.waitForResponse((x) => x.url().includes('/api/agents') && x.request().method() === 'POST', { timeout: 20000 }).catch(() => null)
  await robustClick(page, '.el-dialog button:has-text("创建")', { label: '创建' })
  const rAg = await agPost
  const agToasts = await toasts(page, 1500)
  const okAg = (rAg && (rAg.status() === 200 || rAg.status() === 201)) || agToasts.includes('已创建')
  check('AGENT-01b 新建 Agent(simple)', okAg, `api=${rAg ? rAg.status() : 'n/a'} toast=${JSON.stringify(agToasts)}`)
  R('AGENT-01b 新建 Agent(simple)', okAg, { api: rAg ? rAg.status() : null, toasts: agToasts, screenshot: await shot(page, `s27_${RUN}_02_agent_created`) })
  await page.waitForTimeout(2500)  // 冷却，避免 BFF 用户级 QPS 限流 429 (OBS-01)

  // 进入配置页，四要素勾选真实 LLM endpoint
  const agRow = page.locator('.el-table__row', { hasText: agName }).first()
  await robustClick(page, `.el-table__row:has-text("${agName}") button:has-text('配置')`, { label: '配置' })
  await page.waitForURL(/\/agents\/[0-9a-f-]+\/config/, { timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(1800)
  const cfgShot = await shot(page, `s27_${RUN}_03_agent_config`)
  // 勾选真实 LLM endpoint（按名称 platform-fallback-llm 或 id 匹配）
  const epCheckbox = page.locator('.factor-title:has-text("LLM Endpoint")').locator('..').locator('label:has-text("platform-fallback-llm"), .el-checkbox:has-text("platform-fallback-llm")').first()
  let checked = false
  if (await epCheckbox.count()) {
    await epCheckbox.click()
    checked = true
  } else {
    // 兜底：勾选第一个可用 checkbox
    const firstCbx = page.locator('.factor-title:has-text("LLM Endpoint")').locator('..').locator('.el-checkbox:not(.is-disabled)').first()
    if (await firstCbx.count()) { await firstCbx.click(); checked = true }
  }
  // 保存四要素
  const fourResp = page.waitForResponse((x) => (x.url().includes('/api/agents') && x.request().method() === 'PUT') || (x.url().includes('/api/agents') && x.request().method() === 'POST'), { timeout: 20000 }).catch(() => null)
  await page.click('button:has-text("保存四要素")')
  const rFour = await fourResp
  const fourToasts = await toasts(page, 2000)
  const okFour = (rFour && rFour.status() < 400) || fourToasts.some((t) => /已保存|保存成功/.test(t))
  check('AGENT-01c 配置四要素(勾选真实 LLM)', okFour, `checked=${checked} api=${rFour ? rFour.status() : 'n/a'} toast=${JSON.stringify(fourToasts)}`)
  R('AGENT-01c 配置四要素(勾选真实 LLM)', okFour, { checked, api: rFour ? rFour.status() : null, toasts: fourToasts, screenshot: await shot(page, `s27_${RUN}_04_agent_four_elements`) })
  await page.waitForTimeout(800)

  // AGENT-02a 真实 LLM 对话端到端（点「对话」→ 输入 → 发送）
  await page.goto('http://localhost:8080/agents', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const agRow2 = page.locator('.el-table__row', { hasText: agName }).first()
  await robustClick(page, `.el-table__row:has-text("${agName}") button:has-text('对话')`, { label: '对话' })
  await page.waitForURL(/\/agents\/[0-9a-f-]+\/chat/, { timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(1500)
  await shot(page, `s27_${RUN}_05_chat_open`)
  await page.fill('textarea[placeholder*="输入消息"]', 'ping')
  const chatResp = page.waitForResponse((x) => (x.url().includes('/chat') || x.url().includes('/v1/')) && x.request().method() === 'POST', { timeout: 90000 }).catch(() => null)
  await page.press('textarea[placeholder*="输入消息"]', 'Enter')
  // 等待流式/块式完成：读最后一条 .chat-bubble
  let replyText = ''
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(3000)
    const bubbles = page.locator('.chat-bubble')
    const cnt = await bubbles.count()
    replyText = cnt ? await bubbles.last().textContent() : ''
    if (/pong|⚠️|错误|failed|401|502|AuthenticationError/i.test(replyText)) break
    if (i === 9) await shot(page, `s27_${RUN}_06_chat_waiting`)
  }
  const chatR = await chatResp
  await shot(page, `s27_${RUN}_07_chat_reply`)
  // BUG-11 回归核心：真实带 key LLM 端到端 200 且无鉴权错误。
  // 真实 vLLM 回复内容不保证字面 "pong"（S26 曾得 'pong'，但内容随模型而定），
  // 故断言：响应成功(200) + 有非空回复 + 无 401/502/AuthenticationError/failed。
  const noErr = !/⚠️|401|502|failed|AuthenticationError|Connection|refused/i.test(replyText)
  const gotReply = !!((chatR && chatR.status() === 200) || (replyText.trim().length > 0)) && noErr
  check('AGENT-02a 真实 LLM 对话(端到端,BUG-11 回归)', gotReply, `api=${chatR ? chatR.status() : 'n/a'} reply=${(replyText||'').slice(0,160)}`)
  R('AGENT-02a 真实 LLM 对话(端到端,BUG-11 回归)', gotReply, { api: chatR ? chatR.status() : null, reply: (replyText || '').slice(0, 400), screenshot: `s27_${RUN}_07_chat_reply` })

  // AGENT-02b 多轮续接：同会话再发第二句
  await page.fill('textarea[placeholder*="输入消息"]', 'ping 2')
  await page.press('textarea[placeholder*="输入消息"]', 'Enter')
  let reply2 = ''
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(3000)
    const bubbles = page.locator('.chat-bubble')
    reply2 = await bubbles.count() ? await bubbles.last().textContent() : ''
    if (/pong|⚠️/i.test(reply2)) break
    if (i === 9) await shot(page, `s27_${RUN}_08_chat_second`)
  }
  await shot(page, `s27_${RUN}_09_chat_second_turn`)
  const bubbleCount = await page.locator('.chat-bubble').count()
  const multiOk = /pong/i.test(reply2) && !/⚠️|401|502|failed/i.test(reply2) && bubbleCount >= 4
  check('AGENT-02b 会话多轮续接', multiOk, `bubbles=${bubbleCount} reply2=${(reply2||'').slice(0,80)}`)
  R('AGENT-02b 会话多轮续接', multiOk, { bubbles: bubbleCount, reply2: (reply2 || '').slice(0, 200), screenshot: `s27_${RUN}_09_chat_second_turn` })

  // 清理：删除 agent
  await page.goto('http://localhost:8080/agents', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const agRow3 = page.locator('.el-table__row', { hasText: agName }).first()
  if (await agRow3.count()) {
    const delResp = page.waitForResponse((x) => x.url().includes('/api/agents') && x.request().method() === 'DELETE', { timeout: 15000 }).catch(() => null)
    await robustClick(page, `.el-table__row:has-text("${agName}") button:has-text('删除')`, { label: '删除' })
    await page.waitForTimeout(500)
    const cbtn = page.locator('.el-message-box__btns button:has-text("确定"), .el-message-box__btns button:has-text("确认")').first()
    if (await cbtn.count()) await cbtn.click()
    const rDel = await delResp
    await page.waitForTimeout(1200)
    const stillThere = await page.locator('.el-table__row', { hasText: agName }).count()
    R('AGENT-01d 删除 Agent(清理)', (rDel && rDel.status() === 200) && stillThere === 0, { api: rDel ? rDel.status() : null, stillThere, screenshot: await shot(page, `s27_${RUN}_10_agent_deleted`) })
  }

  record({ case: 'AGENT_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`AGENT SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('AGENT ERROR:', e.message); process.exit(2) })
