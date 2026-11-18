<script setup>
import GraphTab from '../components/GraphTab.vue'
</script>

<template>
  <section class="page">
    <div class="page-inner">
      <header class="page-head">
        <h1>知识图谱</h1>
        <p>
          搜索任意中药、成分、靶点或疾病，查看它的邻居与关系类型。
          在「智能问答」里提问后，回答对应的证据链也会同步到这里。
        </p>
      </header>
      <div class="panel">
        <GraphTab :active="true" :deep-link="true" />
      </div>
    </div>
  </section>
</template>
