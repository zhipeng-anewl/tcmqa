import { reactive } from 'vue'
import { api } from '../api/client'

export const lightbox = reactive({
  visible: false,
  name: '',
  kindText: '',
  id: '',
  src: '',
  strip: [],
  activeIndex: 0,
})

export async function openLightbox(name, info = {}) {
  lightbox.name = name
  lightbox.id = info.id || ''
  lightbox.kindText = info.label === 'Ingredient' ? '化学成分' : '中药'
  lightbox.src = info.orig || info.thumb || ''
  lightbox.strip = []
  lightbox.activeIndex = 0
  lightbox.visible = true

  // 中药通常有多张：拉一次图库，最多展示 12 张
  if (info.label === 'Herb' && info.gallery > 1 && info.id) {
    try {
      const gal = await api(`/api/media/herb/${encodeURIComponent(info.id)}/images`)
      const list = (gal.images || []).slice(0, 12)
      if (list.length) {
        lightbox.strip = list
        lightbox.src = list[0].url
        lightbox.activeIndex = 0
      }
    } catch (e) {
      /* 图库失败就只看封面 */
    }
  }
}

export function selectLightboxImage(index) {
  const item = lightbox.strip[index]
  if (!item || !item.url) return
  lightbox.src = item.url
  lightbox.activeIndex = index
}

export function closeLightbox() {
  lightbox.visible = false
  lightbox.src = ''
  lightbox.strip = []
  lightbox.activeIndex = 0
}
