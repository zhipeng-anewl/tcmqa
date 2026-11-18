export function fmtMs(ms) {
  if (ms == null) return '—'
  return ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms) + 'ms'
}

const INTENT_LABELS = {
  lookup: '属性查询',
  relation: '关系查询',
  aggregate: '聚合统计',
  mechanism: '机制推理',
  semantic: '语义检索',
  chitchat: '闲聊',
  out_of_scope: '超范围',
  blocked: '已拦截',
}

export function intentLabel(intent) {
  return INTENT_LABELS[intent] || intent || '未知'
}
