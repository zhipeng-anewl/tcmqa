new Promise(async (resolve) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  const out = {}

  // ---- 图谱页：深链查一个录过的实体 ----
  location.hash = '#graph?q=' + encodeURIComponent('人参')
  await sleep(2500)
  out.graph = (function () {
    const page = document.querySelector('.page')
    if (!page) return null
    const meta = page.querySelector('.graph-meta span')
    const card = page.querySelector('.node-card-head b')
    return {
      meta: meta ? meta.textContent.trim() : '',
      card: card ? card.textContent.trim() : '',
      shapes: page.querySelectorAll('canvas').length,
    }
  })()

  // ---- 识药页：文本检索 ----
  location.hash = '#vision'
  await sleep(1500)
  const input = document.querySelector('.vision-search input')
  if (input) {
    input.value = '红色的果实'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    const btn = document.querySelector('.vision-search .el-button')
    if (btn) btn.click()
    await sleep(2000)
  }
  out.vision = {
    cards: document.querySelectorAll('.vcard').length,
    first: (document.querySelector('.vcard .vname') || {}).textContent || null,
    progress: document.querySelectorAll('.vcard .el-progress').length,
  }

  // ---- 指标页 ----
  location.hash = '#metrics'
  await sleep(2500)
  out.metrics = {
    stats: document.querySelectorAll('.metric').length,
    charts: document.querySelectorAll('.chart canvas').length,
  }

  resolve(out)
})
