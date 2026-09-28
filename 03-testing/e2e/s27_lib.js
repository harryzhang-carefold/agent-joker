// S27 防造假共享助手：真实表单登录 + 截图 + API 捕获 + 结果 JSONL。
// 硬规则：本文件与所有 s27 脚本中**绝不出现** in-page fetch 登录 / token 注入。
// 登录 = fill 租户/用户名/密码 input → click 登录按钮 → 等待 URL 变化（真实表单路径）。
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')

const ROOT = '/home/hermes/hermes-workspace/projects/agent-joker'
const SHOT_DIR = path.join(ROOT, '03-testing/screenshots/s27')
const RESULTS = path.join(ROOT, '05-temp/s27/results.jsonl')
fs.mkdirSync(SHOT_DIR, { recursive: true })
fs.mkdirSync(path.dirname(RESULTS), { recursive: true })
const BASE = 'http://localhost:8080'
const now = () => new Date().toISOString()

async function shot(page, name) {
  const p = path.join(SHOT_DIR, name + '.png')
  await page.screenshot({ path: p, fullPage: false })
  return p
}

function record(r) {
  const line = JSON.stringify({ ts: now(), ...r })
  fs.appendFileSync(RESULTS, line + '\n')
  console.log(line)
  return r
}

function check(label, cond, detail = '') {
  const ok = !!cond
  console.log(`${ok ? 'PASS' : 'FAIL'} | ${label}${detail ? ' | ' + detail : ''}`)
  return ok
}

// 真实表单登录：返回 {ok, status, url, shot}
// tenant/username/password 直接填入登录页三个 input（占位符定位），点击「登录」，等待 URL 变化。
async function realFormLogin(page, { tenant = 'acme', username = 'admin', password = '123456' } = {}) {
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.locator('input').first().waitFor({ timeout: 15000 })
  await page.screenshot({ path: path.join(SHOT_DIR, `${slug(tenant)}_${slug(username)}_login_form.png`) })
  // 登录表单三个 input：租户编码(placeholder 如 acme) / 用户名(placeholder admin) / 密码(type=password)
  await page.fill('input[placeholder="如 acme"]', tenant)
  await page.fill('input[placeholder="admin"]', username)
  await page.fill('input[type="password"]', password)
  const loginReq = page.waitForResponse(
    (r) => r.url().includes('/api/auth/login'),
    { timeout: 20000 }
  )
  await page.click("button:has-text('登录')")
  const resp = await loginReq
  const status = resp.status()
  let finalUrl = page.url()
  if (status === 200) {
    // 等待 URL 变化（表单登录成功后 router.replace('/users')）
    try {
      await page.waitForURL((u) => String(u).includes('/users'), { timeout: 15000 })
      finalUrl = page.url()
    } catch (e) {
      finalUrl = page.url() // 未跳转也如实记录
    }
    await page.waitForTimeout(800)
  } else {
    await page.waitForTimeout(1200) // 等错误 toast 渲染
  }
  const shotPath = await shot(page, `${slug(tenant)}_${slug(username)}_login_${status === 200 ? 'ok' : 'fail'}`)
  return { ok: status === 200, status, url: finalUrl, shot: shotPath, resp }
}

function slug(s) {
  return String(s).replace(/[^a-z0-9]+/gi, '_').slice(0, 40)
}

// 捕获指定 API 前缀的响应（UI 操作期间的接口双层证据）
function apiWatcher(page, tag, prefixes) {
  const hits = []
  page.on('response', (r) => {
    const u = r.url()
    if (prefixes.some((p) => u.includes(p))) {
      hits.push({ method: r.request().method(), url: u, status: r.status(), ts: now() })
    }
  })
  return { tag, hits, last: () => hits[hits.length - 1] }
}

// 读取 el-message toast 文本（成功/错误提示核对）
async function toasts(page, ms = 1500) {
  await page.waitForTimeout(ms)
  const texts = await page.locator('.el-message, .el-message--error, .el-message--success, .el-message--warning').allTextContents()
  return texts.map((t) => t.trim()).filter(Boolean)
}

async function launch() {
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  return { browser, ctx, page }
}

async function confirmDialog(page) {
  // el-message-box 确认
  const btn = page.locator('.el-message-box__btns button:has-text("确定"), .el-message-box__btns button:has-text("确认")').first()
  if (await btn.count()) await btn.click()
}

// 稳健点击：等待限流 toast 完全消退（QPS 窗口），移除遮罩，再点。失败重试。
async function robustClick(page, selector, { tries = 5, label = '' } = {}) {
  for (let i = 0; i < tries; i++) {
    // 等 QPS 窗口 + toast 消退
    await page.waitForTimeout(1500)
    for (let spin = 0; spin < 6; spin++) {
      const toasts = page.locator('.el-message:visible')
      const n = await toasts.count()
      if (n === 0) break
      for (let k = 0; k < n; k++) { try { await toasts.nth(k).evaluate((el) => el.remove()) } catch {} }
      await page.waitForTimeout(1200)
    }
    try {
      await page.locator(selector).first().click({ timeout: 10000 })
      return true
    } catch (e) {
      if (i === tries - 1) { console.log(`robustClick FAIL ${label || selector}: ${e.message.slice(0,120)}`); return false }
      await page.waitForTimeout(2000)
    }
  }
  return false
}

module.exports = { ROOT, SHOT_DIR, BASE, now, shot, record, check, realFormLogin, slug, apiWatcher, toasts, launch, confirmDialog, robustClick }
