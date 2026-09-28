// S27 BASE: 登录/登出 + 用户/角色/scope/租户 权限边界（真实表单登录，每步截图）
const { launch, realFormLogin, shot, record, check, toasts, apiWatcher, confirmDialog } = require('./s27_lib')
const RUN = 's27base_' + Date.now().toString().slice(-6)

;(async () => {
  const { browser } = await launch()
  let page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  let p = 0, f = 0
  const R = (c, pass, extra = {}) => { const ok = !!pass; ok ? p++ : f++; record({ case: c, pass: ok, ...extra }); return ok }

  // ---- 登录负路径 ----
  let r = await realFormLogin(page, { tenant: 'acme', username: 'admin', password: 'wrong-password-xyz' })
  const msgs = await toasts(page)
  check('BASE-04a 错误密码登录被拒', r.status !== 200 && !r.url.includes('/users'), `status=${r.status} toast=${JSON.stringify(msgs)}`)
  R('BASE-04a 登录失败(错误密码)', r.status !== 200, { status: r.status, toasts: msgs, screenshot: r.shot })
  await page.close()
  let page2 = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  page = page2
  r = await realFormLogin(page, { tenant: 'notexist-tenant', username: 'admin', password: '123456' })
  const msgs2 = await toasts(page)
  check('BASE-04c 错误租户登录被拒', r.status !== 200 && !r.url.includes('/users'), `status=${r.status} toast=${JSON.stringify(msgs2)}`)
  R('BASE-04c 登录失败(错误租户)', r.status !== 200, { status: r.status, toasts: msgs2, screenshot: r.shot })

  // ---- 登录正路径 ----
  r = await realFormLogin(page, { tenant: 'acme', username: 'admin', password: '123456' })
  check('BASE-04b 正确登录跳转 /users', r.ok && r.url.includes('/users'), `status=${r.status} url=${r.url}`)
  const homeShot = await shot(page, `s27_${RUN}_01_home_users`)
  R('BASE-04b 正确登录', r.ok && r.url.includes('/users'), { status: r.status, url: r.url, screenshot: homeShot })

  // 受保护页直达 → 应被路由守卫送回登录页（未登录态）
  const page3 = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  await page3.goto('http://localhost:8080/users', { waitUntil: 'domcontentloaded' })
  await page3.waitForTimeout(1500)
  const guarded = page3.url().includes('/login')
  const guardShot = await shot(page3, `s27_${RUN}_02_guarded_redirect_login`)
  check('BASE-06 未登录直访 /users 重定向 /login', guarded, `url=${page3.url()}`)
  R('BASE-06 未登录直访受保护页重定向', guarded, { url: page3.url(), screenshot: guardShot })
  await page3.context().close()

  // ---- 用户管理 ----
  const w = apiWatcher(page, 'users', ['/api/users'])
  const uname = 'qa_s27_' + RUN
  await page.click("button:has-text('新建用户')")
  await page.locator('.el-dialog').waitFor()
  await page.fill('.el-dialog input[placeholder="≥6 位"]', 'Passw0rd!')
  await page.fill('.el-dialog input:nth-of-type(1)', uname)
  // 用户名 input：对话框第一个非密码 input（username 字段）
  const usernameInput = page.locator('.el-dialog input').first()
  if ((await usernameInput.inputValue()) !== uname) await usernameInput.fill(uname)
  const usersReq = page.waitForResponse((x) => x.url().includes('/api/users') && x.request().method() === 'POST', { timeout: 20000 }).catch(() => null)
  await page.click('.el-dialog button:has-text("保存")')
  const ureq = await usersReq
  const uapi = w.hits.find((h) => h.method === 'POST')
  const umsgs = await toasts(page)
  check('BASE-01a 新建用户', (uapi && uapi.status === 201) || umsgs.includes('已创建'), `api=${JSON.stringify(uapi)} toast=${JSON.stringify(umsgs)}`)
  const uShot = await shot(page, `s27_${RUN}_03_user_created`)
  R('BASE-01a 新建用户', (uapi && uapi.status === 201) || umsgs.includes('已创建'), { api: uapi, toasts: umsgs, screenshot: uShot })
  await page.click('.el-dialog button:has-text("取消")').catch(() => {})
  await page.waitForTimeout(400)

  // 短密码边界
  await page.click("button:has-text('新建用户')")
  await page.locator('.el-dialog').waitFor()
  await page.locator('.el-dialog input').first().fill('qa_s27_short_' + RUN)
  await page.fill('.el-dialog input[placeholder="≥6 位"]', '123')
  await page.click('.el-dialog button:has-text("保存")')
  const shortMsgs = await toasts(page, 1200)
  const shortStillOpen = await page.locator('.el-dialog:visible').count()
  check('BASE-01b 短密码前端拦截', shortMsgs.some((t) => t.includes('6 位')) && shortStillOpen >= 1, `toast=${JSON.stringify(shortMsgs)} dialogOpen=${shortStillOpen}`)
  const shortShot = await shot(page, `s27_${RUN}_04_user_short_pw`)
  R('BASE-01b 短密码(边界)', shortMsgs.some((t) => t.includes('6 位')) && shortStillOpen >= 1, { toasts: shortMsgs, screenshot: shortShot })
  await page.click('.el-dialog button:has-text("取消")').catch(() => {})

  // ---- 角色管理 ----
  await page.goto('http://localhost:8080/roles', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  const rolesReq = page.waitForResponse((x) => x.url().includes('/api/roles') && x.request().method() === 'GET', { timeout: 15000 }).catch(() => null)
  await page.waitForTimeout(600)
  const rn = 'qa_s27_role_' + RUN
  await page.click("button:has-text('新建角色')")
  await page.locator('.el-dialog').waitFor()
  await page.locator('.el-dialog input').first().fill(rn)
  const roleReq = page.waitForResponse((x) => x.url().includes('/api/roles') && x.request().method() === 'POST', { timeout: 20000 }).catch(() => null)
  await page.click('.el-dialog button:has-text("保存")')
  const rapi = await roleReq
  const rmsgs = await toasts(page)
  check('BASE-02d 新建角色', (rapi && rapi.status() === 201) || rmsgs.includes('已保存'), `api=${rapi ? rapi.status() : 'n/a'} toast=${JSON.stringify(rmsgs)}`)
  const roleShot = await shot(page, `s27_${RUN}_05_role_created`)
  R('BASE-02d 新建角色', (rapi && rapi.status() === 201) || rmsgs.includes('已保存'), { api: rapi ? { status: rapi.status(), url: rapi.url() } : null, toasts: rmsgs, screenshot: roleShot })

  // scope 列表
  await page.goto('http://localhost:8080/scopes', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const scopeRows = await page.locator('.el-table__row').count()
  const scopeShot = await shot(page, `s27_${RUN}_06_scopes_list`)
  check('BASE-03a scope 列表渲染', scopeRows > 0, `rows=${scopeRows}`)
  R('BASE-03a 权限(scope)列表', scopeRows > 0, { rows: scopeRows, screenshot: scopeShot })

  // ---- 租户权限边界：admin(acme) 访问 /tenants 应 403 ----
  await page.goto('http://localhost:8080/tenants', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const t403 = await page.locator('text=/无权限|403|权限不足/').count()
  const tShot = await shot(page, `s27_${RUN}_07_tenants_forbidden_admin`)
  check('BASE-02a admin 访问租户管理 403 兜底', t403 > 0, `forbiddenText=${t403}`)
  R('BASE-02a admin 租户管理 403(BUG-07 回归)', t403 > 0, { forbiddenText: t403, screenshot: tShot })

  // ---- 登出 ----
  await page.goto('http://localhost:8080/users', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  // 打开右上角用户菜单（dropdown），点击「退出登录」→ 先确认弹窗 → 再捕获 logout API
  await page.click('.user-menu, span.user-menu')
  await page.waitForTimeout(700)
  const logoutApiP = page.waitForResponse((x) => x.url().includes('/api/auth/logout'), { timeout: 15000 }).catch(() => null)
  await page.click('.el-dropdown-menu__item:has-text("退出登录")')
  await page.waitForTimeout(400)
  await confirmDialog(page)          // 先确认，logout 请求才发出
  const lo = await logoutApiP        // 再等响应
  await page.waitForTimeout(1500)
  const logoutUrl = page.url()
  const logoutShot = await shot(page, `s27_${RUN}_08_logout`)
  check('BASE-05 登出', (lo && lo.status() === 200) && logoutUrl.includes('/login'), `api=${lo ? lo.status() : 'n/a'} url=${logoutUrl}`)
  R('BASE-05 登出', (lo && lo.status() === 200) && logoutUrl.includes('/login'), { api: lo ? lo.status() : null, url: logoutUrl, screenshot: logoutShot })

  record({ case: 'BASE_SUMMARY', pass: f === 0, pass_count: p, fail_count: f })
  console.log(`BASE SUMMARY: ${p} PASS / ${f} FAIL`)
  await browser.close()
  process.exit(f === 0 ? 0 : 1)
})().catch((e) => { console.error('BASE ERROR:', e.message); process.exit(2) })
