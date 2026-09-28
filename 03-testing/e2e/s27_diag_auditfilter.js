// S27 TRACE 诊断: 审计路径前缀过滤是否真生效（total + 行路径前缀）
const { launch, realFormLogin, record, robustClick } = require('./s27_lib')
const RUN = 'trf_' + Date.now().toString().slice(-6)
;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  const apiHits = []
  page.on('request', (rq) => { if (rq.url().includes('/api/audit') && rq.method() === 'GET') apiHits.push(rq.url().split('8080')[1]) })
  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })
  await page.goto('http://localhost:8080/audit', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await robustClick(page, "button:has-text('查询')", { label: 'q' })
  await page.waitForTimeout(1500)
  const totalBefore = await page.locator('.el-pagination__total').textContent().catch(() => 'n/a')
  console.log('total before filter:', totalBefore)
  // 填 /api/rag 过滤
  await page.fill('input[placeholder*="路径前缀"]', '/api/rag')
  await page.waitForTimeout(800)  // @change 会触发 load
  await page.waitForTimeout(1500)
  const totalAfter = await page.locator('.el-pagination__total').textContent().catch(() => 'n/a')
  console.log('total after filter /api/rag:', totalAfter)
  // 看前几行路径是否都以 /api/rag 开头
  const paths = []
  for (let i = 0; i < Math.min(5, await page.locator('.el-table__row').count()); i++) {
    paths.push((await page.locator('.el-table__row').nth(i).locator('td').nth(1).textContent().catch(() => '')) || '')
  }
  console.log('sample paths after filter:', JSON.stringify(paths))
  const allRag = paths.every((p) => p.startsWith('/api/rag'))
  console.log('all sampled paths start with /api/rag:', allRag)
  console.log('audit GET requests:', JSON.stringify(apiHits, null, 1))
  record({ case: 'DIAG_audit_filter', totalBefore, totalAfter, paths, allRag, apiHits })
  await browser.close()
})().catch((e) => { console.error('DIAG ERROR:', e.message); process.exit(2) })
