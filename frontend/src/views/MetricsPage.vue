<script setup>
import MetricsTab from '../components/MetricsTab.vue'
</script>

<template>
  <section class="page">
    <div class="page-inner">
      <header class="page-head">
        <h1>运行指标</h1>
        <p>
          提问数、延迟、token 与成本来自每次请求落库的轨迹；缓存与索引指标反映当前服务状态。
        </p>
      </header>
      <div class="panel">
        <MetricsTab :active="true" />
      </div>
    </div>
  </section>
</template>
