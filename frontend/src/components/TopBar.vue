<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { isDemo } from '../demo'
import { TABS, setTab, ui } from '../stores/ui'

const health = ref('checking') // checking | ok | offline
const nodes = ref(null)

const healthText = computed(
  () => ({ checking: '检测中', ok: '服务在线', offline: '离线' })[health.value]
)

onMounted(async () => {
  try {
    const data = await api('/api/graph/overview')
    nodes.value = data.stats?.nodes ?? 0
    health.value = 'ok'
  } catch (e) {
    health.value = 'offline'
  }
})
</script>

<template>
  <header class="appbar">
    <div class="appbar-inner">
      <button class="brand" title="回到首页" @click="setTab('home')">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="30" height="30">
            <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" stroke-width="1.6" />
            <path
              d="M16 5c4 4.4 4 8.6 0 11-4-2.4-4-6.6 0-11Z"
              fill="currentColor"
              opacity=".9"
            />
            <path
              d="M16 27c-4-4.4-4-8.6 0-11 4 2.4 4 6.6 0 11Z"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
            />
          </svg>
        </span>
        <span class="brand-text">
          <strong>岐黄问答</strong>
          <small>中医药知识图谱智能问答</small>
        </span>
      </button>

      <nav class="nav" aria-label="主导航">
        <button
          v-for="t in TABS"
          :key="t.key"
          class="nav-item"
          :class="{ active: ui.tab === t.key }"
          @click="setTab(t.key)"
        >{{ t.label }}</button>
      </nav>

      <div class="appbar-meta">
        <span v-if="isDemo" class="demo-badge" title="这是离线快照版：数据来自真实运行录制，问题只能从示例里选">
          离线演示
        </span>
        <span v-if="nodes != null" class="meta-num">
          <b>{{ nodes.toLocaleString() }}</b> 节点
        </span>
        <span class="health" :class="health">
          <i></i>{{ healthText }}
        </span>
      </div>
    </div>
  </header>
</template>
