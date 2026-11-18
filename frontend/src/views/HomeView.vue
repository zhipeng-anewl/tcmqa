<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { demoQuestionList, isDemo } from '../demo'
import { setTab } from '../stores/ui'

const emit = defineEmits(['ask'])

const EXAMPLES = [
  '人参含有哪些化学成分？',
  '有哪些清热解毒的中药？',
  '为什么麻黄能治疗哮喘？',
  '槲皮素作用于哪些靶点？',
  '治疗乳腺癌的中药有多少味？',
]

/* 演示模式下换成「确实录过」的问题，避免首页点了示例没反应 */
const demoList = ref([])
const exampleList = computed(() =>
  isDemo && demoList.value.length ? demoList.value.slice(0, 5).map((it) => it.question) : EXAMPLES
)

const q = ref('')
const overview = ref(null)
const vision = ref(null)

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())

/* 实体规模卡片：对标 TCMKD 首页的分类计数，数字全部来自图谱实测 */
const stats = computed(() => {
  const labels = overview.value?.stats?.labels || {}
  const rels = overview.value?.stats?.relationships
  return [
    {
      label: '中药',
      value: fmt(labels.Herb),
      note: '含功效分类与药材图',
      hint: '图谱收录的中药实体数量，点击进入关系图浏览',
    },
    {
      label: '化学成分',
      value: fmt(labels.Ingredient),
      note: '分子量与 ADME 参数',
      hint: '中药中被鉴定的化合物，带分子量与 ADME 五规则参数',
    },
    {
      label: '靶点蛋白',
      value: fmt(labels.Target),
      note: '成分作用的蛋白',
      hint: '成分直接作用或关联的蛋白，是机制链里的中间节点',
    },
    {
      label: '疾病',
      value: fmt(labels.Disease),
      note: 'ICD-9 / ICD-10',
      hint: '按 ICD-9 / ICD-10 编码记录，与中药存在 TREATS / INDICATED_FOR 关系',
    },
    {
      label: '关联关系',
      value: fmt(rels),
      note: '6 类有向关系',
      hint: 'CONTAINS / TARGETS / TREATS / INDICATED_FOR / HAS_ADME / INVOLVED_IN',
    },
    {
      label: '药材图片',
      value: fmt(vision.value?.images),
      note: 'Chinese-CLIP 可检索',
      hint: '已入库的药材实物图，可用于拍照识药',
    },
  ]
})

const features = [
  {
    title: '意图路由',
    text: '先判断问题属于关系查询、聚合统计还是功效语义，再决定走图谱还是走向量，避免答非所问。',
  },
  {
    title: 'Text2Cypher',
    text: '自然语言直接生成只读 Cypher；执行报错或返回空结果时，把原因回灌给模型重写。',
  },
  {
    title: '混合检索',
    text: '向量与 BM25 双路召回后用 RRF 融合，既认「红色果实」这类描述，也认精确药名。',
  },
  {
    title: '拍照识药',
    text: 'Chinese-CLIP 把药材照片与中文描述映射到同一向量空间，以图搜药或按外观找药。',
  },
  {
    title: '证据可溯',
    text: '每个结论都带 [E1] 标号，点开即可看到原始 Cypher 与返回行，结论能被核对。',
  },
  {
    title: '成本可测',
    text: '逐次记录分阶段耗时、token 与费用，并做精确缓存与语义缓存，重复问题秒回。',
  },
]

onMounted(async () => {
  if (isDemo) {
    try {
      demoList.value = await demoQuestionList()
    } catch (e) {
      /* 演示数据缺失不影响页面 */
    }
  }
  try {
    overview.value = await api('/api/graph/overview')
  } catch (e) {
    /* 后端未就绪时首页仍然可用 */
  }
  try {
    vision.value = await api('/api/vision/stats')
  } catch (e) {
    /* 图像索引可能未构建 */
  }
})

function submit() {
  const text = q.value.trim()
  if (!text) return
  q.value = ''
  emit('ask', text)
}

function ask(text) {
  emit('ask', text)
}
</script>

<template>
  <section class="home">
    <div class="home-inner">
      <div class="hero">
        <span class="eyebrow">知识图谱 · GraphRAG · 跨模态检索</span>
        <h1>从一味药，问到一条完整的<br class="br" />作用链路</h1>
        <p class="lede">
          覆盖中药、化学成分、靶点蛋白与疾病的知识图谱，用自然语言提问即可得到带证据的回答：
          每句结论都能回溯到原始查询与返回结果，而不是一段无法核对的文字。
        </p>

        <form class="hero-search" @submit.prevent="submit">
          <input
            v-model="q"
            placeholder="例如：为什么麻黄能治疗哮喘？"
            aria-label="输入问题"
          />
          <button type="submit">提问</button>
        </form>

        <div class="chips">
          <button v-for="e in EXAMPLES" :key="e" class="chip-link" @click="ask(e)">
            {{ e }}
          </button>
        </div>
      </div>

      <div class="stat-grid">
        <el-tooltip
          v-for="s in stats"
          :key="s.label"
          :content="s.hint"
          placement="top"
          :show-after="250"
        >
          <button class="stat-card" @click="setTab('graph')">
            <span class="stat-num">{{ s.value }}</span>
            <span class="stat-label">{{ s.label }}</span>
            <span class="stat-note">{{ s.note }}</span>
          </button>
        </el-tooltip>
      </div>

      <div class="feature-head">
        <h2>能做什么</h2>
        <p>图谱负责事实，模型负责理解与表达，两者不混为一谈。</p>
      </div>
      <div class="feature-grid">
        <article v-for="f in features" :key="f.title" class="feature-card">
          <h3>{{ f.title }}</h3>
          <p>{{ f.text }}</p>
        </article>
      </div>

      <div class="home-cta">
        <div>
          <h2>直接从问题开始</h2>
          <p>不用先学会查图谱——描述你想知道的，系统会自己选检索路径。</p>
        </div>
        <div class="cta-actions">
          <button class="btn primary" @click="setTab('chat')">进入问答</button>
          <button class="btn" @click="setTab('vision')">拍照识药</button>
        </div>
      </div>
    </div>
  </section>
</template>
