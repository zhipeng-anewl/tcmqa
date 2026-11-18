<script setup>
import AboutTab from '../components/AboutTab.vue'
</script>

<template>
  <section class="page">
    <div class="page-inner">
      <header class="page-head">
        <h1>关于</h1>
        <p>这个系统解决什么问题、边界在哪里。</p>
      </header>
      <div class="panel">
        <AboutTab :active="true" />
      </div>
    </div>
  </section>
</template>
