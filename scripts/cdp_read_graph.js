(() => {
  const page = document.querySelector('.page')
  if (!page) return { error: 'no .page' }
  const meta = page.querySelector('.graph-meta span')
  const card = page.querySelector('.node-card-head b')
  const note = page.querySelector('.node-card-body .muted')
  return {
    meta: meta ? meta.textContent.trim() : '',
    card: card ? card.textContent.trim() : '',
    note: note ? note.textContent.trim() : '',
  }
})()
