/**
 * 演示模式：没有后端也能跑的前端。
 *
 * 用途：把真实问答录成静态 JSON，部署到 EdgeOne Pages / GitHub Pages 这类
 * 纯静态托管上，让人点开链接就能看到完整效果，而不用为这个项目长期租服务器。
 *
 * 开关：构建时带 --mode demo（读取 .env.demo 里的 VITE_DEMO=true）。
 * 正常构建（npm run build）不受任何影响。
 */

const BASE = import.meta.env.BASE_URL || '/'

export const isDemo = import.meta.env.VITE_DEMO === 'true'

/* demo 里能查的实体，用于拼错误提示 */
let searchIndex = null

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 去掉标点和空白，用于宽松匹配问题 */
export function normalize(text) {
  return String(text || '')
    .replace(/[\s，。？！、；：,?!.;:"'“”‘’（）()《》]/g, '')
    .toLowerCase()
}

async function getJSON(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`演示数据缺失：${path}`)
  return res.json()
}

let indexPromise = null

export function loadDemoIndex() {
  if (!indexPromise) indexPromise = getJSON('demo/index.json')
  return indexPromise
}

export async function findFixture(question) {
  const idx = await loadDemoIndex()
  const q = normalize(question)
  return idx.questions.find((it) => normalize(it.question) === q) || null
}

export async function loadEvents(slug) {
  return getJSON(`demo/qa/${slug}.json`)
}

/**
 * 回放录下来的 SSE 事件流。
 * token 事件会被切成若干帧，做出打字机效果；固定总时长约 2.4 秒，
 * 不看原始 token 数量——录的时候已经合并成整段了。
 */
export async function replayEvents(events, onEvent, { totalMs = 2400 } = {}) {
  const frames = 48
  for (const ev of events) {
    if (ev.type !== 'token') {
      onEvent(ev)
      await sleep(140)
      continue
    }
    const text = ev.data || ''
    const chunk = Math.max(1, Math.ceil(text.length / frames))
    const delay = totalMs / Math.max(1, Math.ceil(text.length / chunk))
    for (let i = 0; i < text.length; i += chunk) {
      onEvent({ type: 'token', data: text.slice(i, i + chunk) })
      await sleep(delay)
    }
  }
}

/* ------------------------------------------------------------------ */
/* 把后端的接口映射到静态 JSON，api() 在 demo 模式下走这里              */
/* ------------------------------------------------------------------ */

async function loadSearchIndex() {
  if (!searchIndex) {
    const data = await getJSON('demo/search.json')
    searchIndex = data.items || []
  }
  return searchIndex
}

function jsonResponse(data) {
  return Promise.resolve(data)
}

export async function demoApi(path) {
  const url = new URL(path, location.origin)
  const p = url.pathname.replace(/^\/+/, '')
  const q = url.searchParams.get('q') || ''

  if (p === 'api/health') {
    return {
      status: 'ok',
      checks: { neo4j: { ok: true }, llm: { model: 'demo（离线快照）' } },
      demo: true,
    }
  }
  if (p === 'api/graph/overview') return getJSON('demo/overview.json')
  if (p === 'api/vision/stats') return getJSON('demo/vision-stats.json')
  if (p === 'api/metrics') return getJSON('demo/metrics.json')
  if (p === 'api/feedback') return jsonResponse({ ok: true })

  if (p === 'api/graph/search') {
    const items = await loadSearchIndex()
    const needle = normalize(q)
    const hits = items
      .filter((it) => normalize(it.name).includes(needle) || (it.alias && it.alias.includes(needle)))
      .map((it) => ({ name: it.name, label: it.label, id: it.id, alias: it.alias || '' }))
    return { query: q, results: hits }
  }

  if (p === 'api/graph/node') {
    const name = url.searchParams.get('name') || ''
    const items = await loadSearchIndex()
    const known = items.some((it) => it.name === name)
    if (!known) {
      const names = items.map((it) => it.alias || it.name).join('、')
      throw new Error(`演示版只收录了 ${names}，换一个试试`)
    }
    return getJSON(`demo/node/${encodeURIComponent(name)}.json`)
  }

  if (p === 'api/media/resolve') {
    const names = (url.searchParams.get('names') || '').split(',').filter(Boolean)
    const data = await getJSON('demo/media.json')
    const items = {}
    const missing = []
    for (const n of names) {
      const hit = data.items[n] || data.items[n.toLowerCase()]
      if (hit) items[n] = hit
      else missing.push(n)
    }
    return { items, missing }
  }

  if (p === 'api/vision/search-text') {
    // 两个录好的示例：含「红」走第一个，其余走第二个
    return getJSON(q.includes('红') ? 'demo/vision/t1.json' : 'demo/vision/t2.json')
  }

  throw new Error('演示版不包含这个操作')
}

export async function demoQuestionList() {
  const idx = await loadDemoIndex()
  return idx.questions || []
}
