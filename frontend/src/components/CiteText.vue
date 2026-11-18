<script setup>
import { computed } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
})
const emit = defineEmits(['cite'])

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c])

/* 行内：**粗体**、`代码` */
function inline(s) {
  return s
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
}

/**
 * 极简 Markdown 渲染：标题、有序/无序列表、段落、粗体、行内代码。
 *
 * 为什么不用 marked / markdown-it：
 * 1. 模型输出的格式很有限，上面几种就够，没必要为它加一个依赖；
 * 2. 关键是要**先转义再拼 HTML**——自己写这条链路短，更容易保证不出现注入。
 *    如果以后要支持链接/图片，再考虑引入库 + DOMPurify。
 */
function render(src) {
  const lines = String(src || '').split('\n')
  const html = []
  let para = []
  let list = null
  let listTag = 'ul'

  const flushPara = () => {
    if (!para.length) return
    html.push(`<p>${para.join('<br>')}</p>`)
    para = []
  }
  const flushList = () => {
    if (!list) return
    html.push(`<${listTag}>${list.join('')}</${listTag}>`)
    list = null
  }
  const flushAll = () => {
    flushPara()
    flushList()
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    const heading = line.match(/^\s*#{1,6}\s+(.*)$/)
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/)

    if (heading) {
      flushAll()
      html.push(`<h4>${inline(escapeHtml(heading[1]))}</h4>`)
      continue
    }

    if (bullet || ordered) {
      flushPara()
      const tag = bullet ? 'ul' : 'ol'
      if (list && tag !== listTag) flushList()
      listTag = tag
      list = list || []
      list.push(`<li>${inline(escapeHtml((bullet || ordered)[1]))}</li>`)
      continue
    }

    if (!line.trim()) {
      flushAll()
      continue
    }

    flushList()
    para.push(inline(escapeHtml(line)))
  }
  flushAll()

  // 引用标记放在最后替换：此时 [E1] 还是纯文本，换成可点击 span 不会破坏已有标签
  return html
    .join('')
    .replace(/\[(E\d+)\]/g, '<span class="cite" data-eid="$1">[$1]</span>')
}

const html = computed(() => render(props.text))

/* 用事件委托处理引用点击，避免给每个 span 绑监听 */
function onClick(e) {
  const el = e.target.closest?.('.cite')
  const id = el?.dataset?.eid
  if (id) emit('cite', id)
}
</script>

<template>
  <div class="md" @click="onClick" v-html="html"></div>
</template>
