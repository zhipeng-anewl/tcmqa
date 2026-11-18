/**
 * 证据行 → 图数据模型（纯数据，不含渲染）。
 *
 * 渲染交给 vis-network，这里只负责把「一行行证据」翻译成「节点 + 边」：
 * - 每一行的字段按 herb → ingredient → target → disease 的顺序连成一条链；
 * - 同一实体在多行里出现时合并成一个节点（用 `类型:名称` 做 id）；
 * - 没有明确实体字段的行（例如只有一个 ingredient 列）接到锚点实体上。
 */

const FIELD_ORDER = ['herb', 'ingredient', 'target', 'disease']

const KIND_TO_TYPE = {
  herb: 'Herb',
  ingredient: 'Ingredient',
  target: 'Target',
  disease: 'Disease',
}

export const TYPE_LABEL = {
  Herb: '中药',
  Ingredient: '成分',
  Target: '靶点',
  Disease: '疾病',
}

export const TYPE_COLOR = {
  Herb: '#2e6b50',
  Ingredient: '#2f6fa8',
  Target: '#8d6a2f',
  Disease: '#a8452f',
}

export const nodeId = (kind, name) => `${kind}:${name}`

/**
 * @param {Array} rows   证据里的 graph 行
 * @param {string|null} anchor 锚点实体名（问题里识别到的主实体）
 */
export function toNetworkModel(rows, anchor = null) {
  const nodes = new Map()
  const edges = new Map() // 用 id 去重，避免同一对节点画出多条重叠的边

  const addNode = (kind, name) => {
    const id = nodeId(kind, name)
    if (!nodes.has(id)) {
      nodes.set(id, {
        id,
        label: name,
        kind,
        type: KIND_TO_TYPE[kind] || 'Herb',
      })
    }
    return id
  }

  const addEdge = (from, to) => {
    if (!from || !to || from === to) return
    const id = `${from}->${to}`
    if (!edges.has(id)) edges.set(id, { id, from, to })
  }

  for (const row of rows || []) {
    if (!row || typeof row !== 'object') continue

    const present = FIELD_ORDER.filter((k) => typeof row[k] === 'string' && row[k])
    if (present.length === 0) {
      // 单值结果（如只有一个 ingredient 列），接到锚点上
      for (const [key, value] of Object.entries(row)) {
        if (typeof value !== 'string' || !value || value.length > 60) continue
        const id = addNode(key, value)
        if (anchor) addEdge(addNode('herb', anchor), id)
      }
      continue
    }

    let prev = null
    for (const field of present) {
      const id = addNode(field, row[field])
      if (prev) addEdge(prev, id)
      prev = id
    }
    if (present.length === 1 && anchor) {
      addEdge(addNode('herb', anchor), prev)
    }
  }

  return { nodes: [...nodes.values()], edges: [...edges.values()] }
}
