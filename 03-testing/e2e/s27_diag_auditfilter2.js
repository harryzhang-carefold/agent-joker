// S27 TRACE 诊断2: 审计路径过滤 —— 填值后点「查询」按钮（模拟用户），确认 path 参数是否发出 + 结果是否过滤
const { launch, realFormLogin, record, robustClick } = require('./s27_lib')
const RUN = 'trf2_' + Date.now().toString().slice(-6)
;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  const apiHits = []
  page.on('request', (rq) => { if (rq.url().includes('/api/audit') && rq.method() === 'GET') apiHits.push(rq.url().split('8080')[1]) })
  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })
  await page.goto('http://localhost:8080/audit', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await robustClick(page, "button:has-text('查询')", { label: 'q0' })
  await page.waitForTimeout(1200)
  const totalBefore = (await page.locator('.el-pagination__total').textContent().catch(() => '')) || ''
  // 填值 + 按 Enter（el-input change 在 Enter/blur 触发）
  await page.fill('input[placeholder*="路径前缀"]', '/api/rag')
  await page.press('input[placeholder*="路径前缀"]', 'Enter')
  await page.waitForTimeout(600)
  // 再点查询按钮（用户显式操作）
  await robustClick(page, "button:has-text('查询')", { label: 'q1' })
  await page.waitForTimeout(1800)
  const totalAfter = (await page.locator('.el-pagination__total').textContent().catch(() => '')) || ''
  console.log('total before:', totalBefore, '| after(Enter+查询):', totalAfter)
  const paths = []
  for (let i = 0; i < Math.min(6, await page.locator('.el-table__row').count()); i++) {
    paths.push((await page.locator('.el-table__row').nth(i).locator('td').nth(1).textContent().catch(() => '')) || '')
  }
  console.log('sample paths:', JSON.stringify(paths))
  console.log('all start /api/rag:', paths.every((p) => p.startsWith('/api/rag')))
  console.log('audit GETs:', JSON.stringify(apiHits))
  record({ case: 'DIAG_audit_filter2', totalBefore, totalAfter, paths, allRag: paths.every((p) => p.startsWith('/api/rag')), apiHits })
  await browser.close()
})().catch((e) => { console.error('DIAG2 ERROR:', e.message); process.exit(2) })
