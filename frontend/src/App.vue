<script setup>
import { defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import TopBar from './components/TopBar.vue'
import AppFooter from './components/AppFooter.vue'
import HomeView from './views/HomeView.vue'
import ChatPanel from './components/ChatPanel.vue'
import SidePanel from './components/SidePanel.vue'
import Lightbox from './components/Lightbox.vue'
import { goAsk, syncFromHash, ui } from './stores/ui'

// 这四个页面只有点进去才需要：异步加载可以把 vis-network / echarts 挪出首包
const GraphPage = defineAsyncComponent(() => import('./views/GraphPage.vue'))
const VisionPage = defineAsyncComponent(() => import('./views/VisionPage.vue'))
const MetricsPage = defineAsyncComponent(() => import('./views/MetricsPage.vue'))
const AboutPage = defineAsyncComponent(() => import('./views/AboutPage.vue'))

const chatRef = ref(null)

/* 首页示例、拍照识药的「追问」都走这里：先切到问答视图，再交给对话区 */
async function handleAsk(question) {
  if (!question) return
  goAsk(question)
  await nextTick() // 等 v-show 生效，否则滚动到底部时容器高度还是 0
  chatRef.value?.ask(question)
}

function onHashChange() {
  syncFromHash()
}

onMounted(async () => {
  const question = syncFromHash()
  if (question) await handleAsk(question)
  window.addEventListener('hashchange', onHashChange)
})

onBeforeUnmount(() => window.removeEventListener('hashchange', onHashChange))
</script>

<template>
  <TopBar />
  <main class="app-main">
    <!-- 首页与问答保留挂载：问答的消息在组件内部，卸载会丢 -->
    <HomeView v-show="ui.tab === 'home'" @ask="handleAsk" />
    <div v-show="ui.tab === 'chat'" class="workbench">
      <ChatPanel ref="chatRef" />
      <SidePanel />
    </div>

    <!-- 其余页面用 v-if：切走即卸载，避免两套 Canvas/图表同时占资源 -->
    <GraphPage v-if="ui.tab === 'graph'" />
    <VisionPage v-else-if="ui.tab === 'vision'" @ask="handleAsk" />
    <MetricsPage v-else-if="ui.tab === 'metrics'" />
    <AboutPage v-else-if="ui.tab === 'about'" />
  </main>
  <AppFooter />
  <Lightbox />
</template>
