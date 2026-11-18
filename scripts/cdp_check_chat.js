new Promise((resolve) => {
  setTimeout(() => {
    const bubble = document.querySelector('.page .bubble') || document.querySelector('.bubble')
    const msgs = document.querySelectorAll('.msg')
    const chips = Array.prototype.slice
      .call(document.querySelectorAll('.chip'))
      .map((c) => c.textContent.trim())
    const skeleton = document.querySelectorAll('.bubble .el-skeleton').length
    resolve({
      bubbleText: bubble ? bubble.textContent.trim().slice(0, 120) : null,
      bubbleLength: bubble ? bubble.textContent.trim().length : 0,
      hasCursor: bubble ? bubble.classList.contains('cursor') : null,
      messageCount: msgs.length,
      skeletons: skeleton,
      chips: chips.slice(0, 6),
      dockNodes: (function () {
        const el = document.querySelector('#tab-graph .graph-meta span')
        return el ? el.textContent.trim() : null
      })(),
    })
  }, 12000)
})
