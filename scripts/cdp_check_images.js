new Promise(async (resolve) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  location.hash = '#chat'
  await sleep(1500)
  const chip = document.querySelector('.chat-empty .chip-link')
  if (chip) chip.click()
  await sleep(7000)

  // 证据面板默认是折叠的，里面的 img 有 loading=lazy，不展开就不会加载
  const details = document.querySelectorAll('.msg.assistant details')
  details.forEach((d) => (d.open = true))
  await sleep(3000)

  const imgs = Array.prototype.slice.call(document.querySelectorAll('.msg.assistant img'))
  const loaded = imgs.filter((i) => i.complete && i.naturalWidth > 0)
  resolve({
    detailsOpened: details.length,
    images: imgs.length,
    loadedOk: loaded.length,
    broken: imgs.length - loaded.length,
    sample: imgs[0]
      ? { src: imgs[0].getAttribute('src'), w: imgs[0].naturalWidth, h: imgs[0].naturalHeight }
      : null,
  })
})
