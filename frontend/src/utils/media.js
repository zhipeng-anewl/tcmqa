import { reactive } from 'vue'
import { api } from '../api/client'

/* 名称 → 缩略图信息。用 reactive Map 让模板里的 get/has 也参与依赖追踪。 */
export const mediaCache = reactive(new Map())

export async function resolveMedia(names) {
  const todo = [...names].filter((n) => n && !mediaCache.has(n)).slice(0, 40)
  if (todo.length) {
    try {
      const res = await api(`/api/media/resolve?names=${encodeURIComponent(todo.join(','))}`)
      for (const [k, v] of Object.entries(res.items || {})) mediaCache.set(k, v)
      for (const k of res.missing || []) mediaCache.set(k, null)
    } catch (e) {
      /* 没有图不影响主流程 */
    }
  }
  return mediaCache
}

/**
 * 一条证据该配哪张图。
 * 文档类证据用标题；图谱类证据优先取成分（结构式各不相同，信息量更大），其次取中药。
 */
export function pickEntityName(e) {
  if (!e) return null
  if (e.kind === 'herb' || e.kind === 'ingredient') return e.title || null
  const p = e.payload || {}
  for (const key of ['ingredient', 'herb']) {
    if (typeof p[key] === 'string' && p[key]) return p[key]
  }
  return null
}
