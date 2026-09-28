// S27 诊断脚本: 浏览器 UI 新建用户，全新唯一名，完整捕获 API 请求/响应 + 表格行数前后对比。
// 用于判定 BASE-01a 的 409 是真实 bug 还是测试脚本伪影。
const { launch, realFormLogin, shot, record } = require('./s27_lib')
const RUN = 'diag_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()

  // 捕获所有 /api/users 请求的完整 body + 响应
  const reqLog = []
  page.on('request', (rq) => {
    if (rq.url().includes('/api/users') && rq.method() === 'POST') {
      reqLog.push({ ts: new Date().toISOString(), method: 'POST', url: rq.url(), body: rq.postData() })
    }
  })
  const respLog = []
  page.on('response', async (rs) => {
    if (rs.url().includes('/api/users') && rs.request().method() === 'POST') {
      let body = ''
      try { body = await rs.text() } catch { body = '<unreadable>' }
      respLog.push({ ts: new Date().toISOString(), status: rs.status(), body: body.slice(0, 300) })
    }
  })

  await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })
  await page.waitForTimeout(1000)

  // 登录后的用户表行数
  const beforeRows = await page.locator('.el-table__row').count()
  console.log('users table rows before:', beforeRows)

  // 全新唯一用户名
  const uname = 'qa_' + RUN + '_u1'
  console.log('creating user:', uname)
  await page.click("button:has-text('新建用户')")
  // 等待对话框出现且可见
  const dlg = page.locator('.el-dialog:visible')
  await dlg.waitFor({ timeout: 10000 })
  await page.waitForTimeout(300)
  // 填用户名（对话框第一个 input）+ 密码
  const inputs = dlg.locator('input')
  const inputCount = await inputs.count()
  console.log('dialog input count:', inputCount)
  await inputs.nth(0).fill(uname)
  await page.fill('.el-dialog input[type="password"]', 'Passw0rd!')
  await page.waitForTimeout(300)
  const usernameVal = await inputs.nth(0).inputValue()
  const pwVal = await page.locator('.el-dialog input[type="password"]').inputValue()
  console.log('username input value:', usernameVal, '| pw value:', pwVal)
  await shot(page, 'diag_before_save_' + RUN)

  await page.click('.el-dialog button:has-text("保存")')
  await page.waitForTimeout(2500)

  const afterRows = await page.locator('.el-table__row').count()
  console.log('users table rows after:', afterRows)
  const toasts = await page.locator('.el-message').allTextContents()
  console.log('toasts:', JSON.stringify(toasts))
  console.log('REQUESTS:', JSON.stringify(reqLog, null, 2))
  console.log('RESPONSES:', JSON.stringify(respLog, null, 2))
  await shot(page, 'diag_after_save_' + RUN)

  record({ case: 'DIAG_user_create', uname, beforeRows, afterRows, toasts, reqLog, respLog,
           screenshot: '/home/hermes/hermes-workspace/projects/agent-joker/03-testing/screenshots/s27/diag_after_save_' + RUN + '.png' })
  await browser.close()
})().catch((e) => { console.error('DIAG ERROR:', e.message); process.exit(2) })
