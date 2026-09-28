// S27 STORE: 文件上传(.txt 正常 + .doc 边界应 422) + 过滤 + 存储后端
const fs = require('fs')
const path = require('path')
const { launch, realFormLogin, shot, record, check, toasts, apiWatcher } = require('./s27_lib')
const RUN = 's27store_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, ok, extra = {}) => { ok ? p++ : f++; record({ case: c, pass: !!ok, ...extra }); return ok }

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // 准备上传文件
  const tmp = path.join('/home/hermes/hermes-workspace/projects/agent-joker/05-temp/s27')
  const txt = path.join(tmp, `s27_${RUN}.txt`)
  const doc = path.join(tmp, `s27_${RUN}.doc`)
  fs.writeFileSync(txt, 'S27 store test file ' + Date.now())
  fs.writeFileSync(doc, 'S27 legacy doc ' + Date.now())

  await page.goto('http://localhost:8080/storage/files', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const listReq = await page.waitForResponse((x) => x.url().includes('/api/storage/files') || x.url().includes('/api/files'), { timeout: 15000 }).catch(() => null)
  const rows0 = await page.locator('.el-table__row').count()
  const listShot = await shot(page, `s27_${RUN}_01_files_list`)
  check('STORE-01 文件列表渲染', rows0 > 0, `rows=${rows0}`)
  R('STORE-01 文件列表', rows0 > 0, { rows: rows0, screenshot: listShot })

  // 上传 .txt（正常路径）
  const upTxt = page.waitForResponse((x) => x.url().includes('/api/storage/files') && x.request().method() === 'POST', { timeout: 30000 }).catch(() => null)
  await page.setInputFiles('input[type="file"]', txt)
  const r1 = await upTxt
  const t1 = await toasts(page, 1500)
  await page.waitForTimeout(800)
  // 过滤：按文件名
  await page.fill('input[placeholder="文件名模糊"]', `s27_${RUN}.txt`)
  await page.click('button:has-text("刷新")').catch(() => {})
  await page.waitForTimeout(1000)
  const filtered = await page.locator('.el-table__row').count()
  const upShot = await shot(page, `s27_${RUN}_02_txt_uploaded`)
  const ok1 = (r1 && r1.status() === 200) || t1.some((t) => t.includes('已上传'))
  check('STORE-02 上传 .txt + 过滤', ok1 && filtered >= 1, `api=${r1 ? r1.status() : 'n/a'} toast=${JSON.stringify(t1)} filteredRows=${filtered}`)
  R('STORE-02 上传 .txt(正常)', ok1 && filtered >= 1, { api: r1 ? r1.status() : null, toasts: t1, filteredRows: filtered, screenshot: upShot })

  // 上传 .doc（边界：应 422 拒绝并提示转 .docx）
  const upDoc = page.waitForResponse((x) => x.url().includes('/api/storage/files') && x.request().method() === 'POST', { timeout: 30000 }).catch(() => null)
  await page.setInputFiles('input[type="file"]', doc)
  const r2 = await upDoc
  const t2 = await toasts(page, 2000)
  const docShot = await shot(page, `s27_${RUN}_03_doc_rejected`)
  const rejected = (r2 && r2.status() === 422) || t2.some((t) => /unsupported|\.doc|转/i.test(t))
  check('STORE-03 上传 .doc 被拒(BUG-09 回归)', rejected, `api=${r2 ? r2.status() : 'n/a'} toast=${JSON.stringify(t2)}`)
  R('STORE-03 上传 .doc(边界,BUG-09 回归)', rejected, { api: r2 ? r2.status() : null, toasts: t2, screenshot: docShot })

  // 存储后端
  await page.goto('http://localhost:8080/storage/backends', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const bRows = await page.locator('.el-table__row').count()
  const localShown = await page.locator('text=/local/i').count()
  const bShot = await shot(page, `s27_${RUN}_04_backends`)
  check('STORE-04 存储后端列表(local 当前)', bRows > 0 && localShown > 0, `rows=${bRows} local=${localShown}`)
  R('STORE-04 存储后端配置', bRows > 0 && localShown > 0, { rows: bRows, local: localShown, screenshot: bShot })

  record({ case: 'STORE_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`STORE SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('STORE ERROR:', e.message); process.exit(2) })
