<script setup>
import { nextTick, ref } from 'vue'

const props = defineProps({
  disabled: Boolean,
})
const emit = defineEmits(['send'])

const input = ref('')
const ta = ref(null)

function resize() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 140) + 'px'
}

function submit() {
  const q = input.value.trim()
  if (!q || props.disabled) return
  emit('send', q)
  input.value = ''
  nextTick(resize)
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <textarea
      ref="ta"
      v-model="input"
      rows="1"
      maxlength="500"
      autocomplete="off"
      placeholder="输入问题，Enter 发送，Shift+Enter 换行…"
      @keydown="onKeydown"
      @input="resize"
    ></textarea>
    <button type="submit" :disabled="disabled" title="发送">发送</button>
  </form>
</template>
