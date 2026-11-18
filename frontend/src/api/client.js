/* 后端 API 小封装。上传接口不要用它（multipart 必须让浏览器自己设 boundary）。 */

import { demoApi, isDemo } from '../demo'

export async function api(path, options = {}) {
  // 演示模式：没有后端，所有接口从静态 JSON 里取
  if (isDemo) return demoApi(path, options)

  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.slice(0, 200)}`)
  }
  return res.json()
}

export function postJSON(path, body) {
  return api(path, { method: 'POST', body: JSON.stringify(body) })
}
