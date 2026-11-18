<script setup>
import VisionTab from '../components/VisionTab.vue'

defineEmits(['ask'])
</script>

<template>
  <section class="page">
    <div class="page-inner">
      <header class="page-head">
        <h1>拍照识药</h1>
        <p>
          上传药材照片，或用一句中文描述外观，返回视觉上最接近的候选药材。
          结果是<strong>候选召回</strong>，不是鉴定结论——同名异物、同物异名在中药里很常见。
        </p>
      </header>
      <div class="panel">
        <VisionTab :active="true" @ask="$emit('ask', $event)" />
      </div>
    </div>
  </section>
</template>
