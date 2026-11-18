<script setup>
const year = new Date().getFullYear()
</script>

<template>
  <footer class="appfooter">
    <div class="appfooter-inner">
      <p class="foot-disclaimer">
        <b>免责声明</b> 本系统仅用于中医药知识检索与演示，输出为图谱关联结果的归纳，
        不构成诊断、处方或用药建议；具体用药请咨询执业中医师。
      </p>
      <p class="foot-meta">
        <span>数据来源 Neo4j 中医药知识图谱</span>
        <span class="dot">·</span>
        <span>GraphRAG + Text2Cypher + Chinese-CLIP</span>
        <span class="dot">·</span>
        <span>© {{ year }}</span>
      </p>
    </div>
  </footer>
</template>
