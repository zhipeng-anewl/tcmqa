new Promise((resolve) => {
  const input = document.querySelector('.vision-search input')
  if (!input) {
    resolve({ error: 'no input' })
    return
  }
  input.value = '红色的果实'
  input.dispatchEvent(new Event('input', { bubbles: true }))

  const btn = document.querySelector('.vision-search .el-button')
  if (!btn) {
    resolve({ error: 'no button' })
    return
  }
  btn.click()

  setTimeout(() => {
    const cards = Array.prototype.slice.call(document.querySelectorAll('.vcard'))
    resolve({
      cards: cards.length,
      progressBars: document.querySelectorAll('.vcard .el-progress').length,
      first: cards[0] ? cards[0].querySelector('.vname').textContent : null,
      status: (document.querySelector('.graph-legend') || {}).textContent?.trim(),
      emptyShown: Boolean(document.querySelector('#tab-vision .el-empty')),
    })
  }, 7000)
})
