// RAG 切分策略（RAG-04，5 策略工厂）+ 参数定义（供建库/上传/重切分/对比表单共用）。
export const SPLIT_STRATEGIES = {
  fixed: {
    label: '定长 (fixed)',
    fields: [
      { key: 'chunk_size', label: 'chunk_size', type: 'number', def: 500 },
      { key: 'overlap', label: 'overlap', type: 'number', def: 50 },
    ],
  },
  parent_child: {
    label: '父子 (parent_child)',
    fields: [
      { key: 'parent_size', label: 'parent_size', type: 'number', def: 2000 },
      { key: 'child_size', label: 'child_size', type: 'number', def: 500 },
      { key: 'overlap', label: 'overlap', type: 'number', def: 50 },
    ],
  },
  semantic: {
    label: '语义 (semantic)',
    fields: [
      { key: 'threshold', label: 'threshold', type: 'number', def: 0.25, step: 0.01 },
      { key: 'chunk_size', label: 'chunk_size', type: 'number', def: 500 },
    ],
  },
  structured_tree: {
    label: '结构化文档树 (structured_tree)',
    fields: [
      { key: 'chunk_size', label: 'chunk_size', type: 'number', def: 500 },
      { key: 'overlap', label: 'overlap', type: 'number', def: 50 },
    ],
  },
  table: {
    label: '表格 (table)',
    fields: [
      { key: 'max_table_chars', label: 'max_table_chars', type: 'number', def: 4000 },
      { key: 'row_group', label: 'row_group', type: 'number', def: 50 },
    ],
  },
}

export function strategyLabel(s) {
  return (SPLIT_STRATEGIES[s] && SPLIT_STRATEGIES[s].label) || s || '默认'
}

// 默认参数（按策略）
export function defaultParams(strategy) {
  const f = (SPLIT_STRATEGIES[strategy] || SPLIT_STRATEGIES.fixed).fields
  const o = {}
  for (const x of f) o[x.key] = x.def
  return o
}

// pos 坐标结构解释（按文档类型，供切分对比/高亮消费，ARCH §2.2.1）
// 返回人类可读的位置描述。
export function describePos(pos, docType) {
  if (!pos) return '-'
  try {
    const p = typeof pos === 'string' ? JSON.parse(pos) : pos
    const parts = []
    if (p.page != null && docType !== 'txt') parts.push(`第 ${p.page} 页`)
    if (Array.isArray(p.section_path) && p.section_path.length) parts.push('节: ' + p.section_path.join(' / '))
    if (p.char_start != null && p.char_end != null) parts.push(`字符 [${p.char_start}, ${p.char_end})`)
    if (p.table_row) {
      const t = p.table_row
      parts.push(`表格: ${t.sheet || ''}#${t.table || ''} 行[${t.row_start}-${t.row_end}]`)
    }
    if (docType === 'png' || docType === 'jpg') parts.push('整图')
    return parts.length ? parts.join(' · ') : JSON.stringify(p)
  } catch {
    return String(pos)
  }
}
