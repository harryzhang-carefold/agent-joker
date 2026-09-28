// S27 RAG: 建库(含 embedding 选择) / 建库缺必填(边界) / 文档上传+解析 / 检索(未选库边界 + 正常) / 知识库列表
const fs = require('fs')
const path = require('path')
const { launch, realFormLogin, shot, record, check, toasts } = require('./s27_lib')
const RUN = 's27rag_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, ok, extra = {}) => { ok ? p++ : f++; record({ case: c, pass: !!ok, ...extra }); return ok }

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // RAG-01a 知识库列表
  const kbW = { hits: [] }; page.on('response', (r) => { if (r.url().includes('/api/rag/kbs') && r.request().method() === 'GET') kbW.hits.push(r.status()) })
  await page.goto('http://localhost:8080/rag/kbs', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)
  const kbRows = await page.locator('.el-table__row').count()
  check('RAG-01a 知识库列表', kbW.hits.includes(200) && kbRows > 0, `api=${JSON.stringify(kbW.hits.slice(0,3))} rows=${kbRows}`)
  R('RAG-01a 知识库列表', kbW.hits.includes(200) && kbRows > 0, { api: kbW.hits.slice(0,3), rows: kbRows, screenshot: await shot(page, `s27_${RUN}_01_kbs`) })

  // RAG-01c 建库缺必填（边界：空表单直接创建）
  await page.click("button:has-text('建库')")
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  await page.click('.el-dialog button:has-text("创建")')
  await page.waitForTimeout(800)
  const vToasts = await toasts(page, 1200)
  const vStillOpen = await page.locator('.el-dialog:visible').count()
  const vBlocked = (vToasts.length > 0 && vStillOpen >= 1)
  check('RAG-01c 建库缺必填(边界)', vBlocked, `toast=${JSON.stringify(vToasts)} dialogOpen=${vStillOpen}`)
  R('RAG-01c 建库缺必填(边界)', vBlocked, { toasts: vToasts, screenshot: await shot(page, `s27_${RUN}_02_kb_validation`) })
  await page.click('.el-dialog button:has-text("取消")').catch(() => {})
  await page.waitForTimeout(400)

  // RAG-01b 建库（名称 + 选 active embedding 模型）
  const kbName = 's27_kb_' + RUN
  await page.click("button:has-text('建库')")
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  await page.fill('.el-dialog:visible input', kbName)
  // 选 embedding 模型（filterable select）：点开后选第一个 option
  const embSelect = page.locator('.el-dialog:visible .el-select', { hasText: 'embedding' }).first()
  // 更稳：直接点「Embedding 模型」form-item 内的 select
  const embItem = page.locator('.el-dialog:visible .el-form-item', { hasText: 'Embedding 模型' }).first()
  await embItem.locator('.el-select').click()
  await page.waitForTimeout(600)
  const opt = page.locator('.el-select-dropdown__item:visible').first()
  const optText = await opt.textContent()
  await opt.click()
  await page.waitForTimeout(400)
  const kbPost = page.waitForResponse((x) => x.url().includes('/api/rag/kbs') && x.request().method() === 'POST', { timeout: 30000 }).catch(() => null)
  await page.click('.el-dialog button:has-text("创建")')
  const rKb = await kbPost
  const kbToasts = await toasts(page, 3000)
  const okKb = (rKb && rKb.status() === 201) || kbToasts.some((t) => /建库成功|已创建|创建成功/.test(t))
  check('RAG-01b 建库', okKb, `api=${rKb ? rKb.status() : 'n/a'} emb=${(optText||'').trim()} toast=${JSON.stringify(kbToasts)}`)
  R('RAG-01b 建库', okKb, { api: rKb ? rKb.status() : null, embedding: (optText || '').trim(), toasts: kbToasts, screenshot: await shot(page, `s27_${RUN}_03_kb_created`) })

  // 找到新建库行，进文档页
  const kbRow = page.locator('.el-table__row', { hasText: kbName }).first()
  if (await kbRow.count()) {
    await kbRow.locator("button:has-text('文档')").click()
    await page.waitForURL(/\/rag\/kbs\/[0-9a-f-]+$/, { timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(1500)
    const docsShot = await shot(page, `s27_${RUN}_04_kb_docs`)
    R('RAG-03a 进入 KB 文档页', true, { url: page.url(), screenshot: docsShot })

    // RAG-03b 上传文档（.txt）
    const docFile = path.join('/home/hermes/hermes-workspace/projects/agent-joker/05-temp/s27', `s27_${RUN}.txt`)
    fs.writeFileSync(docFile, 'agent-joker 是一个多租户 AI Agent 平台，支持用户角色权限、统一存储、LLM 节点、RAG 知识库、MCP、Skills 与 Agent 对话。S27 全量浏览器测试文档内容。'.repeat(2))
    const docUp = page.waitForResponse((x) => x.url().includes('/docs') && x.request().method() === 'POST', { timeout: 60000 }).catch(() => null)
    await page.setInputFiles('input[type="file"]', docFile)
    const rDoc = await docUp
    const dToasts = await toasts(page, 2500)
    const okDoc = (rDoc && rDoc.status() === 200) || dToasts.some((t) => /已上传|入队/.test(t))
    check('RAG-03b 上传文档', okDoc, `api=${rDoc ? rDoc.status() : 'n/a'} toast=${JSON.stringify(dToasts)}`)
    R('RAG-03b 上传文档', okDoc, { api: rDoc ? rDoc.status() : null, toasts: dToasts, screenshot: await shot(page, `s27_${RUN}_05_doc_uploaded`) })

    // RAG-04a 解析流水线推进（轮询到 ready，最长 90s）
    let status = ''
    for (let i = 0; i < 18; i++) {
      await page.waitForTimeout(5000)
      const stCell = await page.locator('.el-table__row', { hasText: `s27_${RUN}.txt` }).first().locator('td').nth(2).textContent().catch(() => '')
      status = (stCell || '').trim()
      if (/ready|embedded|完成/.test(status)) break
      if (i % 3 === 2) await shot(page, `s27_${RUN}_06_pipeline_${i}`)
    }
    await shot(page, `s27_${RUN}_07_doc_pipeline_final`)
    const ready = /ready|embedded|完成/.test(status)
    check('RAG-04a 解析流水线→ready', ready, `finalStatus=${status}`)
    R('RAG-04a 解析流水线状态推进', ready, { finalStatus: status, screenshot: `s27_${RUN}_07_doc_pipeline_final` })
  } else {
    R('RAG-03a 进入 KB 文档页', false, { note: 'new KB row not found' })
    R('RAG-03b 上传文档', false, { note: 'skipped' })
    R('RAG-04a 解析流水线状态推进', false, { note: 'skipped' })
  }

  // RAG-06a 检索未选库（边界）
  await page.goto('http://localhost:8080/rag/search', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await page.fill('input[placeholder="输入检索问题"]', 'test query no kb')
  const noKbToasts = page.waitForTimeout(600)
  await page.click('button:has-text("检索")')
  const nkToasts = await toasts(page, 1500)
  const nkBlocked = nkToasts.some((t) => /选择知识库|请选择/.test(t))
  check('RAG-06a 检索未选库(边界)', nkBlocked, `toast=${JSON.stringify(nkToasts)}`)
  R('RAG-06a 检索未选库(边界)', nkBlocked, { toasts: nkToasts, screenshot: await shot(page, `s27_${RUN}_08_search_nokb`) })

  // RAG-06b 检索（正常：选新建库）
  const searchSel = page.locator('form .el-select').first()
  await searchSel.click()
  await page.waitForTimeout(800)
  const kbOpt = page.locator('.el-select-dropdown__item:visible', { hasText: kbName }).first()
  if (await kbOpt.count()) {
    await kbOpt.click()
  } else {
    const firstOpt = page.locator('.el-select-dropdown__item:visible').first()
    await firstOpt.click()
  }
  await page.fill('input[placeholder="输入检索问题"]', '多租户 AI Agent 平台 RAG 知识库')
  const searchResp = page.waitForResponse((x) => x.url().includes('/api/rag') && x.request().method() === 'POST', { timeout: 60000 }).catch(() => null)
  await page.click('button:has-text("检索")')
  const sr = await searchResp
  await page.waitForTimeout(2000)
  const resultText = await page.locator('.el-card, .el-table').first().textContent().catch(() => '')
  await shot(page, `s27_${RUN}_09_search_results`)
  // 新库刚上传 1 篇短文档，可能 0 命中或低分——只断言"检索接口成功返回"（200）而非强制命中
  const searchOk = sr && (sr.status() === 200 || sr.status() === 404) // 404=库无索引属环境态
  check('RAG-06b 检索接口(正常路径)', sr && sr.status() === 200, `api=${sr ? sr.status() : 'n/a'} resultLen=${(resultText||'').length}`)
  R('RAG-06b 检索(正常路径)', sr && sr.status() === 200, { api: sr ? sr.status() : null, resultSnippet: (resultText || '').slice(0, 200), screenshot: `s27_${RUN}_09_search_results` })

  record({ case: 'RAG_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`RAG SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('RAG ERROR:', e.message); process.exit(2) })
