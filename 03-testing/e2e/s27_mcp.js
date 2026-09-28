// S27 MCP: Server 列表(含 BUG-10 SPA 直连回归) / 注册 Server / 工具列表 / 删除
const { launch, realFormLogin, shot, record, check, toasts } = require('./s27_lib')
const RUN = 's27mcp_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, ok, extra = {}) => { ok ? p++ : f++; record({ case: c, pass: !!ok, ...extra }); return ok }

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // 响应监听在导航前挂载（避免 GET 列表先于 waiter）
  const srvW = { hits: [] }; page.on('response', (r) => { if (r.url().includes('/api/mcp/servers') && r.request().method() === 'GET') srvW.hits.push(r.status()) })

  // MCP-01a' BUG-10 回归：浏览器地址栏**直连** /mcp/servers（刷新/分享链接场景）应渲染 SPA，而非 BFF 401 JSON
  await page.goto('http://localhost:8080/mcp/servers', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)
  const spaOk = await page.locator("text=/MCP Server|注册 Server/").count()
  const no401 = !(await page.locator('text=/missing access token|invalid|401/').count())
  check('MCP-01a 直连 /mcp/servers 渲染 SPA(BUG-10 回归)', spaOk > 0 && no401, `spaText=${spaOk} no401=${no401}`)
  R('MCP-01a 直连 /mcp/servers(BUG-10 回归)', spaOk > 0 && no401, { spaText: spaOk, no401, screenshot: await shot(page, `s27_${RUN}_01_mcp_direct`) })

  // MCP-01a 列表
  const rows0 = await page.locator('.el-table__row').count()
  check('MCP-01a MCP Server 列表', srvW.hits.includes(200) && rows0 > 0, `api=${JSON.stringify(srvW.hits.slice(0,3))} rows=${rows0}`)
  R('MCP-01a MCP Server 列表', srvW.hits.includes(200) && rows0 > 0, { api: srvW.hits.slice(0,3), rows: rows0, screenshot: await shot(page, `s27_${RUN}_02_mcp_list`) })

  // MCP-01b 注册 MCP Server（mock-mcp host.docker.internal:9100/mcp）
  const srvName = 's27_mcp_' + RUN
  await page.click("button:has-text('注册 Server')")
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  const dlg = page.locator('.el-dialog:visible')
  await dlg.locator('input').nth(0).fill(srvName)
  await dlg.locator('input').nth(1).fill('http://joker-mock-mcp:9100/mcp')
  const regResp = page.waitForResponse((x) => x.url().includes('/api/mcp/servers') && x.request().method() === 'POST', { timeout: 30000 }).catch(() => null)
  await page.click('.el-dialog button:has-text("注册")')
  const rReg = await regResp
  const regToasts = await toasts(page, 3000)
  const okReg = (rReg && (rReg.status() === 200 || rReg.status() === 201)) || regToasts.some((t) => /注册|已保存|success/i.test(t))
  check('MCP-01b 注册 MCP Server', okReg, `api=${rReg ? rReg.status() : 'n/a'} toast=${JSON.stringify(regToasts)}`)
  R('MCP-01b 注册 MCP Server', okReg, { api: rReg ? rReg.status() : null, toasts: regToasts, screenshot: await shot(page, `s27_${RUN}_03_mcp_registered`) })
  await page.waitForTimeout(1000)

  // MCP-02a 工具列表（新注册 server 点「工具」）
  const newSrvRow = page.locator('.el-table__row', { hasText: srvName }).first()
  if (await newSrvRow.count()) {
    await newSrvRow.locator("button:has-text('工具')").click()
    await page.waitForURL(/\/mcp\/servers\/[0-9a-f-]+\/tools/, { timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(1800)
    const toolRows = await page.locator('.el-table__row').count()
    const toolW = await page.locator("text=/工具名|Server 列表/").count()
    check('MCP-02a MCP 工具列表', toolRows > 0 || toolW > 0, `rows=${toolRows}`)
    R('MCP-02a MCP 工具列表', toolRows > 0 || toolW > 0, { rows: toolRows, url: page.url(), screenshot: await shot(page, `s27_${RUN}_04_mcp_tools`) })
    await page.click("button:has-text('Server 列表')").catch(() => {})
    await page.waitForTimeout(800)
  } else {
    R('MCP-02a MCP 工具列表', false, { note: 'new server row not found' })
  }

  // MCP-03a 删除 Server（清理）
  const delRow = page.locator('.el-table__row', { hasText: srvName }).first()
  if (await delRow.count()) {
    const delResp = page.waitForResponse((x) => x.url().includes('/api/mcp/servers') && x.request().method() === 'DELETE', { timeout: 15000 }).catch(() => null)
    await delRow.locator("button:has-text('删除')").click()
    // 确认
    await page.waitForTimeout(500)
    const cbtn = page.locator('.el-message-box__btns button:has-text("确定"), .el-message-box__btns button:has-text("确认")').first()
    if (await cbtn.count()) await cbtn.click()
    const rDel = await delResp
    await page.waitForTimeout(1500)
    const stillThere = await page.locator('.el-table__row', { hasText: srvName }).count()
    const okDel = (rDel && rDel.status() === 200) && stillThere === 0
    check('MCP-03a 删除 MCP Server', okDel, `api=${rDel ? rDel.status() : 'n/a'} stillThere=${stillThere}`)
    R('MCP-03a 删除 MCP Server(清理)', okDel, { api: rDel ? rDel.status() : null, stillThere, screenshot: await shot(page, `s27_${RUN}_05_mcp_deleted`) })
  } else {
    R('MCP-03a 删除 MCP Server(清理)', false, { note: 'row not found' })
  }

  record({ case: 'MCP_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`MCP SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('MCP ERROR:', e.message); process.exit(2) })
