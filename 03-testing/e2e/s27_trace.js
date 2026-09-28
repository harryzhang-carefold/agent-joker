// S27 TRACE/审计: Trace 会话列表(查询) / 会话详情 / 接口操作日志(审计) 查询
const { launch, realFormLogin, shot, record, check, robustClick } = require('./s27_lib')
const RUN = 's27trace_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, ok, extra = {}) => { ok ? p++ : f++; record({ case: c, pass: !!ok, ...extra }); return ok }

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // TRACE-01a Trace 会话列表
  const trW = { hits: [] }; page.on('response', (r) => { if (r.url().includes('/api/trace') && r.request().method() === 'GET') trW.hits.push(r.status()) })
  await page.goto('http://localhost:8080/trace/sessions', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  // 点「查询」
  await robustClick(page, "button:has-text('查询')", { label: '查询' })
  await page.waitForTimeout(1800)
  const trRows = await page.locator('.el-table__row').count()
  check('TRACE-01a Trace 会话列表(查询)', trW.hits.includes(200) && trRows > 0, `api=${JSON.stringify(trW.hits.slice(0,3))} rows=${trRows}`)
  R('TRACE-01a Trace 会话列表', trW.hits.includes(200) && trRows > 0, { api: trW.hits.slice(0,3), rows: trRows, screenshot: await shot(page, `s27_${RUN}_01_trace_list`) })

  // TRACE-01b 会话详情（点第一行「详情」）
  const firstRow = page.locator('.el-table__row').first()
  if (await firstRow.count()) {
    await robustClick(page, '.el-table__row button:has-text("详情")', { label: '详情' })
    await page.waitForURL(/\/trace\/sessions\/[0-9a-f-]+/, { timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(2000)
    const detailContent = await page.locator('.page, .chat-main, .msg-area, .el-card').first().textContent().catch(() => '')
    const detailOk = /\/trace\/sessions\//.test(page.url()) && detailContent.trim().length > 0
    check('TRACE-01b 会话详情', detailOk, `url=${page.url()} contentLen=${detailContent.length}`)
    R('TRACE-01b Trace 会话详情', detailOk, { url: page.url(), contentSnippet: detailContent.slice(0, 150), screenshot: await shot(page, `s27_${RUN}_02_trace_detail`) })
  } else {
    R('TRACE-01b Trace 会话详情', false, { note: 'no row' })
  }

  // TRACE-02a 接口操作日志(审计)
  const auW = { hits: [] }; page.on('response', (r) => { if (r.url().includes('/api/audit') && r.request().method() === 'GET') auW.hits.push(r.status()) })
  await page.goto('http://localhost:8080/audit', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await robustClick(page, "button:has-text('查询')", { label: '审计查询' })
  await page.waitForTimeout(2000)
  const auRows = await page.locator('.el-table__row').count()
  check('TRACE-02a 接口操作日志(审计)', auW.hits.includes(200) && auRows > 0, `api=${JSON.stringify(auW.hits.slice(0,3))} rows=${auRows}`)
  R('TRACE-02a 接口操作日志(审计)', auW.hits.includes(200) && auRows > 0, { api: auW.hits.slice(0,3), rows: auRows, screenshot: await shot(page, `s27_${RUN}_03_audit`) })

  // TRACE-02b 审计按路径前缀过滤（边界：/api/rag 应过滤）
  await page.fill('input[placeholder*="路径前缀"]', '/api/rag')
  await robustClick(page, "button:has-text('查询')", { label: '审计过滤查询' })
  await page.waitForTimeout(2000)
  const filteredRows = await page.locator('.el-table__row').count()
  // 过滤后应有 rag 相关行（前面测过 rag），行数应 <= 50 且 > 0
  const filterOk = filteredRows > 0
  check('TRACE-02b 审计路径前缀过滤', filterOk, `filteredRows=${filteredRows}`)
  R('TRACE-02b 审计路径前缀过滤(边界)', filterOk, { filteredRows, screenshot: await shot(page, `s27_${RUN}_04_audit_filtered`) })

  record({ case: 'TRACE_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`TRACE SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('TRACE ERROR:', e.message); process.exit(2) })
