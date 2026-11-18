<script setup>
import GraphTab from './GraphTab.vue'
import { setTab } from '../stores/ui'
</script>

<template>
  <aside class="dock">
    <div class="dock-head">
      <h2>证据链</h2>
      <span>随回答更新</span>
    </div>
    <GraphTab :active="true" compact />
    <button class="dock-foot" @click="setTab('graph')">在知识图谱中打开 →</button>
  </aside>
</template>
