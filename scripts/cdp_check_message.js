new Promise((resolve) => {
  const page = document.querySelector('.page')
  if (!page) {
    resolve({ error: 'no .page' })
    return
  }
  const buttons = Array.prototype.slice.call(page.querySelectorAll('.graph-actions .el-button'))
  const exportBtn = buttons.find((b) => b.textContent.indexOf('PNG') >= 0)
  if (!exportBtn) {
    resolve({ error: 'no export button', found: buttons.map((b) => b.textContent.trim()) })
    return
  }
  exportBtn.click()
  setTimeout(() => {
    const msg = document.querySelector('.el-message')
    resolve({
      messageShown: Boolean(msg),
      text: msg ? msg.textContent.trim() : null,
      buttons: buttons.map((b) => b.textContent.trim()),
      tags: document.querySelectorAll('.legend .el-tag').length,
    })
  }, 1600)
})
