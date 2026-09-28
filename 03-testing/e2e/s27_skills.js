// S27 Skills: 列表 / 内联创建 / 空名(边界) / 文件上传 / 删除
const fs = require('fs')
const path = require('path')
const { launch, realFormLogin, shot, record, check, toasts } = require('./s27_lib')
const RUN = 's27skill_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, ok, extra = {}) => { ok ? p++ : f++; record({ case: c, pass: !!ok, ...extra }); return ok }

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })

  // SKILL-01a 列表
  const skW = { hits: [] }; page.on('response', (r) => { if (r.url().includes('/api/skills') && r.request().method() === 'GET') skW.hits.push(r.status()) })
  await page.goto('http://localhost:8080/skills', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const skRows = await page.locator('.el-table__row').count()
  check('SKILL-01a Skill 列表', skW.hits.includes(200) && skRows > 0, `api=${JSON.stringify(skW.hits.slice(0,3))} rows=${skRows}`)
  R('SKILL-01a Skill 列表', skW.hits.includes(200) && skRows > 0, { api: skW.hits.slice(0,3), rows: skRows, screenshot: await shot(page, `s27_${RUN}_01_skills`) })

  // SKILL-01b 内联创建
  const skName = 's27_skill_' + RUN
  await page.click("button:has-text('内联创建')")
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  const dlg = page.locator('.el-dialog:visible')
  await dlg.locator('input').nth(0).fill(skName)
  await dlg.locator('input').nth(1).fill('S27 skill description')
  await dlg.locator('textarea').fill('# S27 Skill\n\nThis is a test skill content for S27 full browser regression.\n')
  const skPost = page.waitForResponse((x) => x.url().includes('/api/skills') && x.request().method() === 'POST', { timeout: 20000 }).catch(() => null)
  await page.click('.el-dialog button:has-text("保存")')
  const rSk = await skPost
  const skToasts = await toasts(page, 1500)
  const okSk = (rSk && (rSk.status() === 200 || rSk.status() === 201)) || skToasts.includes('已保存')
  check('SKILL-01b 内联创建 Skill', okSk, `api=${rSk ? rSk.status() : 'n/a'} toast=${JSON.stringify(skToasts)}`)
  R('SKILL-01b 内联创建 Skill', okSk, { api: rSk ? rSk.status() : null, toasts: skToasts, screenshot: await shot(page, `s27_${RUN}_02_skill_created`) })
  await page.waitForTimeout(800)

  // SKILL-01c 空名(边界)
  await page.click("button:has-text('内联创建')")
  await page.locator('.el-dialog:visible').waitFor({ timeout: 10000 })
  const dlg2 = page.locator('.el-dialog:visible')
  await dlg2.locator('input').nth(1).fill('empty name test')
  await dlg2.locator('textarea').fill('content only, no name\n')
  const skPost2 = page.waitForResponse((x) => x.url().includes('/api/skills') && x.request().method() === 'POST', { timeout: 15000 }).catch(() => null)
  await page.click('.el-dialog button:has-text("保存")')
  const rSk2 = await skPost2
  const skToasts2 = await toasts(page, 1500)
  const emptyRejected = (rSk2 && rSk2.status() >= 400) || skToasts2.some((t) => /name|required|名称|必填/i.test(t))
  check('SKILL-01c 空名(边界)', emptyRejected, `api=${rSk2 ? rSk2.status() : 'n/a'} toast=${JSON.stringify(skToasts2)}`)
  R('SKILL-01c 空名(边界)', emptyRejected, { api: rSk2 ? rSk2.status() : null, toasts: skToasts2, screenshot: await shot(page, `s27_${RUN}_03_skill_empty_name`) })
  await page.click('.el-dialog button:has-text("取消")').catch(() => {})

  // SKILL-01d 文件上传（.md）
  const mdFile = path.join('/home/hermes/hermes-workspace/projects/agent-joker/05-temp/s27', `s27_${RUN}.md`)
  fs.writeFileSync(mdFile, '# S27 uploaded skill\n\nMulti-file upload test content.\n')
  const mdUp = page.waitForResponse((x) => x.url().includes('/api/skills') && x.request().method() === 'POST', { timeout: 20000 }).catch(() => null)
  await page.setInputFiles('input[type="file"]', mdFile)
  const rMd = await mdUp
  const mdToasts = await toasts(page, 2000)
  const okMd = (rMd && (rMd.status() === 200 || rMd.status() === 201)) || mdToasts.some((t) => /已上传|已保存|上传成功/.test(t))
  check('SKILL-01d 文件上传(.md)', okMd, `api=${rMd ? rMd.status() : 'n/a'} toast=${JSON.stringify(mdToasts)}`)
  R('SKILL-01d Skill 文件上传(.md)', okMd, { api: rMd ? rMd.status() : null, toasts: mdToasts, screenshot: await shot(page, `s27_${RUN}_04_skill_upload`) })
  await page.waitForTimeout(800)

  // SKILL-01e 删除内联创建 skill（清理）
  const skRow = page.locator('.el-table__row', { hasText: skName }).first()
  if (await skRow.count()) {
    const delResp = page.waitForResponse((x) => x.url().includes('/api/skills') && x.request().method() === 'DELETE', { timeout: 15000 }).catch(() => null)
    await skRow.locator("button:has-text('删除')").click()
    await page.waitForTimeout(500)
    const cbtn = page.locator('.el-message-box__btns button:has-text("确定"), .el-message-box__btns button:has-text("确认")').first()
    if (await cbtn.count()) await cbtn.click()
    const rDel = await delResp
    await page.waitForTimeout(1200)
    const stillThere = await page.locator('.el-table__row', { hasText: skName }).count()
    const okDel = (rDel && rDel.status() === 200) && stillThere === 0
    check('SKILL-01e 删除 Skill(清理)', okDel, `api=${rDel ? rDel.status() : 'n/a'} still=${stillThere}`)
    R('SKILL-01e 删除 Skill(清理)', okDel, { api: rDel ? rDel.status() : null, stillThere, screenshot: await shot(page, `s27_${RUN}_05_skill_deleted`) })
  } else {
    R('SKILL-01e 删除 Skill(清理)', false, { note: 'row not found' })
  }

  record({ case: 'SKILLS_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`SKILLS SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('SKILLS ERROR:', e.message); process.exit(2) })
