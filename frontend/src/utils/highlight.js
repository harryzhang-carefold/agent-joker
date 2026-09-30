// S41: 渲染后 DOM 的「文本流」构建 + 最佳努力高亮。
// 用于 docx(docx-preview)/xlsx(SheetJS) 左栏：后端 chunk 文本按 docx/xlsx 解析后的
// 顺序切分，渲染后文本顺序与之一致，故按「文本位置」在渲染文本中匹配 chunk 内容。
// 匹配不到 → 仅显示原文不高亮（不报错）。
//
// 实现：遍历 root 内所有 text node（文档顺序），构建「空白归一化」字符串并保留
// 每个归一化字符 → (node, 原始下标) 的映射；在归一化串中搜索归一化后的 query，
// 命中则把命中的原始字符区间（可跨多个 text node）切分并用 <mark class="hl"> 包裹。

const HL_CLASS = 'hl'

function collectTextNodes(root) {
  const nodes = []
  if (!root) return nodes
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let n
  while ((n = walker.nextNode())) {
    if (n.nodeValue && n.nodeValue.length) nodes.push(n)
  }
  return nodes
}

// 构建归一化串 + 字符映射（map[i] = {node, i}，i 为该字符在 node 原始文本中的下标）
function buildNorm(root) {
  const nodes = collectTextNodes(root)
  let text = ''
  const map = []
  for (const node of nodes) {
    const raw = node.nodeValue
    let prevSpace = text === '' ? false : /\s$/.test(text)
    for (let i = 0; i < raw.length; i++) {
      const ch = raw[i]
      if (/\s/.test(ch)) {
        if (!prevSpace && text.length) {
          text += ' '
          map.push({ node, i })
        }
        prevSpace = true
      } else {
        text += ch
        map.push({ node, i })
        prevSpace = false
      }
    }
  }
  return { text, map }
}

function normQuery(q) {
  return String(q == null ? '' : q).replace(/\s+/g, ' ').trim()
}

// 把一个 text node 的 [s,e) 原始区间切分并用 <mark> 包裹
function splitAndMark(node, s, e) {
  const full = node.nodeValue
  const before = full.slice(0, s)
  const mid = full.slice(s, e)
  const after = full.slice(e)
  const parent = node.parentNode
  if (!parent) return
  const frag = document.createDocumentFragment()
  if (before) frag.appendChild(document.createTextNode(before))
  const mark = document.createElement('mark')
  mark.className = HL_CLASS
  mark.textContent = mid
  frag.appendChild(mark)
  if (after) frag.appendChild(document.createTextNode(after))
  parent.replaceChild(frag, node)
}

// 在 root 中按文本匹配 query 并高亮；命中返回 true
export function highlightQuery(root, query) {
  const q = normQuery(query)
  if (!root || !q) return false
  const { text, map } = buildNorm(root)
  const idx = text.indexOf(q)
  if (idx < 0) return false
  const end = idx + q.length
  // 命中的归一化区间 [idx,end) → 按 node 分组，求每个 node 的原始 [minI,maxI+1)
  const byNode = new Map()
  for (let k = idx; k < end; k++) {
    const m = map[k]
    if (!m) continue
    const arr = byNode.get(m.node) || []
    arr.push(m.i)
    byNode.set(m.node, arr)
  }
  if (!byNode.size) return false
  for (const [node, is] of byNode) {
    let minI = Infinity
    let maxI = -Infinity
    for (const i of is) {
      if (i < minI) minI = i
      if (i > maxI) maxI = i
    }
    splitAndMark(node, minI, maxI + 1)
  }
  return true
}

// 清除 root 内既有的 <mark class="hl">（合并回相邻 text node）
export function clearMarks(root) {
  if (!root) return
  const marks = Array.from(root.querySelectorAll(`mark.${HL_CLASS}`))
  for (const m of marks) {
    const parent = m.parentNode
    if (!parent) continue
    const textNode = document.createTextNode(m.textContent || '')
    parent.replaceChild(textNode, m)
    // 合并相邻 text node，保证下次 buildNorm 干净
    if (textNode.previousSibling && textNode.previousSibling.nodeType === Node.TEXT_NODE) {
      const prev = textNode.previousSibling
      prev.nodeValue += textNode.nodeValue
      parent.removeChild(textNode)
    }
  }
}
