// S27 诊断3: 登出流程完整网络捕获，定位 logout API 是否真发
const { launch, realFormLogin, shot, record, confirmDialog } = require('./s27_lib')
const RUN = 'lg_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  const netLog = []
  page.on('response', (rs) => {
    const u = rs.url()
    if (u.includes('/api/auth/')) netLog.push({ ts: new Date().toISOString(), status: rs.status(), method: rs.request().method(), url: u.split('8080')[1] })
  })
  page.on('console', (msg) => { if (msg.type() === 'error') netLog.push({ ts: new Date().toISOString(), console_error: msg.text().slice(0, 200) }) })

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })
  await page.goto('http://localhost:8080/users', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)

  await page.click('.user-menu, span.user-menu')
  await page.waitForTimeout(700)
  const ddVisible = await page.locator('.el-dropdown-menu:visible').count()
  console.log('dropdown visible count:', ddVisible)
  // dump dropdown 菜单项
  const items = await page.locator('.el-dropdown-menu__item').allTextContents()
  console.log('dropdown items:', JSON.stringify(items))
  await shot(page, 'lg_dropdown_open_' + RUN)

  const before = netLog.length
  await page.click('.el-dropdown-menu__item:has-text("退出登录")')
  console.log('clicked 退出登录')
  await page.waitForTimeout(500)
  // 确认弹窗出现了吗
  const boxVisible = await page.locator('.el-message-box:visible').count()
  console.log('confirm box visible:', boxVisible)
  if (boxVisible) { await shot(page, 'lg_confirm_' + RUN); await confirmDialog(page) }
  await page.waitForTimeout(2000)
  console.log('final url:', page.url())
  console.log('auth net activity after click:', JSON.stringify(netLog.slice(before), null, 2))
  record({ case: 'DIAG_logout', items, before, after: netLog.length, netLog: netLog.slice(before), url: page.url() })
  await browser.close()
})().catch((e) => { console.error('DIAG3 ERROR:', e.message); process.exit(2) })
