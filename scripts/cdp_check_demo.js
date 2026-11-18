new Promise(async (resolve) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  location.hash = '#chat'
  await sleep(1200)

  const chip = document.querySelector('.chat-empty .chip-link')
  if (!chip) {
    resolve({ error: 'no chip', html: document.body.innerText.slice(0, 200) })
    return
  }
  const question = chip.textContent.trim()
  chip.click()

  await sleep(7000)

  const bubble = document.querySelector('.msg.assistant .bubble')
  const text = bubble ? bubble.textContent.trim() : ''
  const chips = Array.prototype.slice
    .call(document.querySelectorAll('.msg.assistant .chip'))
    .map((c) => c.textContent.trim())
  const evidenceItems = document.querySelectorAll('.msg.assistant .ev-item, .msg.assistant .evidence-row')

  resolve({
    question,
    textLength: text.length,
    head: text.slice(0, 90),
    chips,
    evidenceNodes: evidenceItems.length,
    images: document.querySelectorAll('.msg.assistant img').length,
    dockGraph: (function () {
      const el = document.querySelector('#tab-graph .graph-meta span')
      return el ? el.textContent.trim() : null
    })(),
  })
})
