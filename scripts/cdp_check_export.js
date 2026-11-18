(() => {
  const host = document.querySelector('.graph-host')
  const canvases = host ? [...host.querySelectorAll('canvas')] : []
  const out = {
    canvases: canvases.length,
    sizes: canvases.map((c) => [c.width, c.height]),
    css: canvases.map((c) => [c.clientWidth, c.clientHeight]),
  }

  // 复用导出的合成逻辑，确认能产出一张有效 PNG（不真正触发下载）
  if (canvases.length) {
    const base = canvases[0]
    const cv = document.createElement('canvas')
    cv.width = base.width
    cv.height = base.height
    const ctx = cv.getContext('2d')
    ctx.fillStyle = '#fdfcf9'
    ctx.fillRect(0, 0, cv.width, cv.height)
    for (const c of canvases) {
      if (c.width === cv.width && c.height === cv.height) ctx.drawImage(c, 0, 0)
    }
    const url = cv.toDataURL('image/png')
    out.pngBytes = Math.round(url.length * 0.75)
  }

  const buttons = [...document.querySelectorAll('.graph-actions button')].map((b) =>
    b.textContent.trim()
  )
  const exportBtn = [...document.querySelectorAll('.graph-actions button')].find((b) =>
    b.textContent.includes('PNG')
  )
  out.buttons = buttons
  out.hasExportButton = Boolean(exportBtn)

  const card = document.querySelector('.node-card-body .muted')
  out.hint = card ? card.textContent.trim() : ''

  return out
})()
