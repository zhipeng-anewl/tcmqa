<script setup>
defineProps({ active: Boolean })
</script>

<template>
  <div v-show="active" class="tab-body" id="tab-about">
    <p>
      <b>这是什么</b><br />基于 Neo4j 中医药知识图谱的问答系统。问题先经规划器判断意图，
      再按需走向图谱查询（Text2Cypher）或向量检索，最后用证据约束生成答案。
    </p>
    <p>
      <b>为什么不是纯向量 RAG</b><br />「人参含哪些成分」「哪些药治疗糖尿病」是精确关系查询，
      向量检索答不准；反过来「手脚冰凉吃什么」没有明确实体，只能用语义检索。
      所以做了意图路由 + 混合检索。
    </p>
    <p>
      <b>可信度</b><br />每个结论都带 [E1] 形式的证据编号，点开可以看到原始查询和结果。
    </p>
    <p class="disclaimer">本系统仅用于知识检索演示，不构成任何诊疗建议。</p>
  </div>
</template>
