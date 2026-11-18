(() => {
  // 页面里有两个 .graph-host：问答页侧栏（隐藏）和知识图谱页（可见），取可见的那个
  const hosts = Array.prototype.slice.call(document.querySelectorAll('.graph-host'))
  const visible = hosts.filter((h) => h.clientWidth > 0)
  const host = visible[0] || hosts[0]

  const out = {
    hostCount: hosts.length,
    visibleHostCount: visible.length,
    hostSize: host ? [host.clientWidth, host.clientHeight] : null,
  }

  const canvases = host ? Array.prototype.slice.call(host.querySelectorAll('canvas')) : []
  out.canvasCount = canvases.length
  out.sizes = canvases.map((c) => [c.width, c.height])

  const usable = canvases.filter((c) => c.width > 0 && c.height > 0)
  if (!usable.length) {
    out.png = 'no usable canvas'
    return out
  }

  // 取面积最大的作为底图（vis 可能有辅助画布）
  let base = usable[0]
  for (const c of usable) {
    if (c.width * c.height > base.width * base.height) base = c
  }

  const cv = document.createElement('canvas')
  cv.width = base.width
  cv.height = base.height
  const ctx = cv.getContext('2d')
  ctx.fillStyle = '#fdfcf9'
  ctx.fillRect(0, 0, cv.width, cv.height)
  for (const c of usable) {
    if (c.width === cv.width && c.height === cv.height) ctx.drawImage(c, 0, 0)
  }

  const url = cv.toDataURL('image/png')
  out.pngBytes = Math.round(url.length * 0.75)
  out.pngPrefix = url.slice(0, 22)

  const buttons = Array.prototype.slice
    .call(document.querySelectorAll('.graph-actions button'))
    .map((b) => b.textContent.trim())
  out.buttons = buttons
  return out
})()
