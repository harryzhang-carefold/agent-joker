// S27 smoke: 验证真实表单登录 + 截图 + API 捕获链路
const { launch, realFormLogin, shot, record, check, toasts } = require('./s27_lib')

;(async () => {
  const { browser, page } = await launch()
  const r = await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })
  check('smoke 真实表单登录 200 + URL 变化到 /users', r.ok && r.url.includes('/users'), `status=${r.status} url=${r.url}`)
  const msgs = await toasts(page)
  console.log('toasts:', JSON.stringify(msgs))
  // 登录后首屏（/users 用户管理）截图
  const s = await shot(page, 'smoke_home_users')
  record({ case: 'smoke-login', pass: r.ok && r.url.includes('/users'), status: r.status, url: r.url, screenshot: s })
  await browser.close()
  process.exit(r.ok && r.url.includes('/users') ? 0 : 1)
})().catch((e) => { console.error('SMOKE ERROR:', e.message); process.exit(2) })
