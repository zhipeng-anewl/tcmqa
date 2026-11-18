import { reactive } from 'vue'

/**
 * 全局界面状态：当前在哪个视图。
 * 单独抽成 store 是为了让导航栏、首页卡片、拍照识药的「追问」都能切视图，
 * 不必层层 emit。
 *
 * 同时用 URL hash 做路由（#chat / #graph ...），好处：
 * 1. 页面可以分享、可以收藏、刷新不丢；
 * 2. 支持 #chat?q=问题 直接带着问题进来（拍照识药的追问也能变成链接）。
 * 这里不引入 vue-router：只有 6 个平级视图、没有嵌套和参数，一个 hash 足够。
 */

export const ui = reactive({ tab: 'home' })

export const TABS = [
  { key: 'home', label: '首页' },
  { key: 'chat', label: '智能问答' },
  { key: 'graph', label: '知识图谱' },
  { key: 'vision', label: '拍照识药' },
  { key: 'metrics', label: '运行指标' },
  { key: 'about', label: '关于' },
]

const KEYS = new Set(TABS.map((t) => t.key))

function parseHash() {
  const raw = decodeURIComponent(String(location.hash || '').replace(/^#\/?/, ''))
  const [key, query = ''] = raw.split('?')
  let question = ''
  try {
    question = new URLSearchParams(query).get('q') || ''
  } catch (e) {
    question = ''
  }
  return { key: KEYS.has(key) ? key : 'home', question }
}

export function setTab(key, { silent = false } = {}) {
  if (!KEYS.has(key)) return
  ui.tab = key
  if (!silent && location.hash.replace(/^#\/?/, '').split('?')[0] !== key) {
    history.replaceState(null, '', '#' + key)
  }
}

/** 进入某个对话问题：切换视图并把问题交给对话区（由 App 消费） */
export function goAsk(question) {
  setTab('chat')
  const text = String(question || '').trim()
  history.replaceState(
    null,
    '',
    '#' + (text ? `chat?q=${encodeURIComponent(text)}` : 'chat')
  )
}

/** 首屏从 hash 恢复视图；返回需要自动提问的内容（仅 chat 视图才返回问题） */
export function syncFromHash() {
  const { key, question } = parseHash()
  setTab(key, { silent: true })
  return key === 'chat' ? question : ''
}
