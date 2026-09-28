// S27 LLM: Chat 端点 列表/新建/连通性(mock ok + 不可达 fail) + Embedding/Reranker 列表
// 修复: 响应监听在导航前挂载（避免 GET 列表先于 waiter）；连通性读 /test 响应体 ok 字段。
const { launch, realFormLogin, shot, record, check, toasts, apiWatcher } = require('./s27_lib')
const RUN = 's27llm_' + Date.now().toString().slice(-6)

// 在导航前挂载的 GET 捕获器
function watchGet(page, prefix) {
  const hits = []
  page.on('response', (r) => {
    if (r.url().includes(prefix) && r.request().method() === 'GET') hits.push(r.status())
  })
  return { hits, ok: () => hits.some((s) => s === 200) }
}

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, ok, extra = {}) => { ok ? p++ : f++; record({ case: c, pass: !!ok, ...extra }); return ok }

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // LLM-01a Chat 端点列表（导航前挂载 GET 监听）
  const epW = watchGet(page, '/api/llm/endpoints')
  await page.goto('http://localhost:8080/llm/endpoints', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const epRows = await page.locator('.el-table__row').count()
  check('LLM-01a Chat 端点列表', epW.ok() && epRows > 0, `api=${JSON.stringify(epW.hits.slice(0,3))} rows=${epRows}`)
  R('LLM-01a Chat 端点列表', epW.ok() && epRows > 0, { api: epW.hits.slice(0,3), rows: epRows, screenshot: await shot(page, `s27_${RUN}_01_endpoints`) })

  // LLM-01b 新建 Chat 端点（指向不可达地址，便于连通性 fail 测试）
  const newEpName = 's27_ep_' + RUN
  await page.click("button:has-text('新建')")
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  const epPost = page.waitForResponse((x) => x.url().includes('/api/llm/endpoints') && x.request().method() === 'POST', { timeout: 20000 }).catch(() => null)
  await page.fill('.el-dialog:visible input', newEpName)
  const dlgInputs = page.locator('.el-dialog:visible input')
  await dlgInputs.nth(1).fill('http://127.0.0.1:59999/v1')   // Base URL
  await dlgInputs.nth(2).fill('s27-test-model')               // 模型
  await page.click('.el-dialog button:has-text("保存")')
  const rEp = await epPost
  const epToasts = await toasts(page, 1500)
  const okEp = (rEp && rEp.status() === 201) || epToasts.includes('已保存')
  check('LLM-01b 新建 Chat 端点', okEp, `api=${rEp ? rEp.status() : 'n/a'} toast=${JSON.stringify(epToasts)}`)
  R('LLM-01b 新建 Chat 端点', okEp, { api: rEp ? rEp.status() : null, toasts: epToasts, screenshot: await shot(page, `s27_${RUN}_02_endpoint_created`) })
  await page.waitForTimeout(800)

  // LLM-01d 连通性测试（不可达 → 不可用 + 明确错误提示，BUG-08 回归）
  const row = page.locator('.el-table__row', { hasText: newEpName }).first()
  const testReqP = page.waitForResponse((x) => x.url().includes('/test') && x.request().method() === 'POST', { timeout: 60000 }).catch(() => null)
  await row.locator("button:has-text('连通性')").click()
  let testBody = ''
  try { const tr = await testReqP; testBody = tr ? (await tr.text()).slice(0, 300) : '' } catch {}
  const tToasts = await toasts(page, 3000)
  const failShown = tToasts.some((t) => /不可用|ConnectError|unavailable|failed/i.test(t)) || /unavailable|ConnectError/.test(testBody)
  check('LLM-01d 连通性(不可达,BUG-08 回归)', failShown, `body=${testBody.slice(0,120)} toast=${JSON.stringify(tToasts)}`)
  R('LLM-01d 连通性测试(不可达,边界)', failShown, { testBody: testBody.slice(0,200), toasts: tToasts, screenshot: await shot(page, `s27_${RUN}_03_endpoint_test_fail`) })

  // LLM-01c 连通性测试（mock 正常路径）：选一个 base_url 含 joker-mock-llm 的行（确保可达）
  const mockRow = page.locator('.el-table__row', { hasText: 'joker-mock-llm' }).first()
  if (await mockRow.count()) {
    const mockTestP = page.waitForResponse((x) => x.url().includes('/test') && x.request().method() === 'POST', { timeout: 30000 }).catch(() => null)
    await mockRow.locator("button:has-text('连通性')").click()
    let mockBody = ''
    try { const mr = await mockTestP; mockBody = mr ? (await mr.text()).slice(0, 300) : '' } catch {}
    const mToasts = await toasts(page, 3000)
    const okShown = /"ok":\s*true|ok: model/.test(mockBody) || mToasts.some((t) => /可用|ok|responded/i.test(t))
    check('LLM-01c 连通性(mock,正常)', okShown, `body=${mockBody.slice(0,120)} toast=${JSON.stringify(mToasts)}`)
    R('LLM-01c 连通性测试(mock,正常)', okShown, { testBody: mockBody.slice(0,200), toasts: mToasts, screenshot: await shot(page, `s27_${RUN}_04_endpoint_test_ok`) })
  } else {
    R('LLM-01c 连通性测试(mock,正常)', false, { note: 'no reachable mock endpoint row found' })
  }

  // Embedding 列表（导航前挂载）
  const embW = watchGet(page, '/api/llm/embeddings')
  await page.goto('http://localhost:8080/llm/embeddings', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const embRows = await page.locator('.el-table__row').count()
  check('LLM-02a Embedding 列表', embW.ok() && embRows > 0, `api=${JSON.stringify(embW.hits.slice(0,3))} rows=${embRows}`)
  R('LLM-02a Embedding 模型列表', embW.ok() && embRows > 0, { api: embW.hits.slice(0,3), rows: embRows, screenshot: await shot(page, `s27_${RUN}_05_embeddings`) })

  // Reranker 列表
  const rrW = watchGet(page, '/api/llm/rerankers')
  await page.goto('http://localhost:8080/llm/rerankers', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const rrRows = await page.locator('.el-table__row').count()
  check('LLM-03a Reranker 列表', rrW.ok() && rrRows > 0, `api=${JSON.stringify(rrW.hits.slice(0,3))} rows=${rrRows}`)
  R('LLM-03a Reranker 模型列表', rrW.ok() && rrRows > 0, { api: rrW.hits.slice(0,3), rows: rrRows, screenshot: await shot(page, `s27_${RUN}_06_rerankers`) })

  record({ case: 'LLM_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`LLM SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('LLM ERROR:', e.message); process.exit(2) })
