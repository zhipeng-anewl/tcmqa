<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api/client'
import { fmtMs, intentLabel } from '../utils/format'

// 按需注册：只引入用到的图表与组件，避免把整个 echarts 打进包里
// 注意 legend 属于 LegendComponent，漏注册的话 legend 配置会被静默忽略
echarts.use([PieChart, BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({ active: Boolean })

const metrics = ref(null)
const recent = ref([])

const pieEl = ref(null)
const barEl = ref(null)
let pieChart = null
let barChart = null

const PALETTE = ['#2e6b50', '#2f6fa8', '#8d6a2f', '#a8452f', '#6b7f76', '#9a8bb5', '#b98b3f']

async function load() {
  try {
    const m = await api('/api/metrics')
    metrics.value = m
    // 过滤掉没有问题的轨迹（历史数据里有少量空记录），否则列表会出现空行
    recent.value = (m.recent || []).filter((t) => t && t.question)
    await nextTick()
    renderCharts()
  } catch (e) {
    /* 指标失败不影响主流程 */
  }
}

const items = computed(() => {
  const m = metrics.value
  if (!m) return []
  const qa = m.qa || {}
  const cache = m.cache || {}
  const index = m.index || {}
  const fb = m.feedback || {}
  return [
    ['提问数', qa.questions ?? 0],
    ['平均延迟', fmtMs(qa.avg_latency_ms)],
    [
      '累计 token',
      ((qa.prompt_tokens ?? 0) + (qa.completion_tokens ?? 0)).toLocaleString(),
    ],
    ['单次成本', '¥' + Number(qa.cost_per_question_cny ?? 0).toFixed(4)],
    ['缓存条目', cache.entries ?? 0],
    ['缓存命中', cache.hits ?? 0],
    ['索引文档', index.documents ?? 0],
    ['好评/差评', `${fb.up ?? 0}/${fb.down ?? 0}`],
  ]
})

function renderCharts() {
  const m = metrics.value
  if (!m) return

  // ---- 意图分布 ----
  const intents = m.qa?.intents || {}
  if (pieEl.value) {
    pieChart = pieChart || echarts.init(pieEl.value)
    pieChart.setOption(
      {
        color: PALETTE,
        tooltip: { trigger: 'item', formatter: '{b}：{c} 次（{d}%）' },
        legend: {
          bottom: 0,
          itemWidth: 8,
          itemHeight: 8,
          textStyle: { color: '#857c6c', fontSize: 11 },
        },
        series: [
          {
            type: 'pie',
            radius: ['46%', '68%'],
            center: ['50%', '44%'],
            avoidLabelOverlap: true,
            itemStyle: { borderColor: '#fff', borderWidth: 2 },
            label: { show: false },
            emphasis: { label: { show: true, fontSize: 12, color: '#23211c' } },
            data: Object.entries(intents).map(([k, v]) => ({
              name: intentLabel(k),
              value: v,
            })),
          },
        ],
      },
      true
    )
  }

  // ---- 最近请求延迟 ----
  const rows = recent.value.slice(0, 10).slice().reverse()
  if (barEl.value) {
    barChart = barChart || echarts.init(barEl.value)
    barChart.setOption(
      {
        grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (p) => {
            const i = p[0]?.dataIndex ?? 0
            const q = rows[i]?.question || ''
            return `${q}<br/>${fmtMs(p[0]?.value)}`
          },
        },
        xAxis: {
          type: 'value',
          axisLabel: { color: '#857c6c', fontSize: 10, formatter: (v) => v + 'ms' },
          splitLine: { lineStyle: { color: '#efe9db' } },
        },
        yAxis: {
          type: 'category',
          data: rows.map((r) => {
            const q = String(r.question || '')
            return q.length > 10 ? q.slice(0, 10) + '…' : q
          }),
          axisLabel: { color: '#4b463c', fontSize: 11 },
          axisLine: { lineStyle: { color: '#e7e0d1' } },
          axisTick: { show: false },
        },
        series: [
          {
            type: 'bar',
            data: rows.map((r) => Number(r.elapsed_ms || 0)),
            barWidth: 9,
            itemStyle: { color: '#2e6b50', borderRadius: [0, 4, 4, 0] },
          },
        ],
      },
      true
    )
  }
}

function resizeCharts() {
  pieChart?.resize()
  barChart?.resize()
}

watch(
  () => props.active,
  (v) => {
    if (v) load()
  },
  { immediate: true }
)

onMounted(() => window.addEventListener('resize', resizeCharts))
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  pieChart?.dispose()
  barChart?.dispose()
  pieChart = null
  barChart = null
})
</script>

<template>
  <div v-show="active" class="tab-body" id="tab-metrics">
    <div class="metric-grid">
      <div v-for="[k, v] in items" :key="k" class="metric">
        <div class="k">{{ k }}</div>
        <div class="v">{{ v }}</div>
      </div>
    </div>

    <div class="chart-grid">
      <div class="chart-card">
        <h4>意图分布</h4>
        <div ref="pieEl" class="chart"></div>
      </div>
      <div class="chart-card">
        <h4>最近请求延迟</h4>
        <div ref="barEl" class="chart"></div>
      </div>
    </div>

    <h4>最近请求</h4>
    <div class="trace-list">
      <div v-if="!recent.length" class="row">暂无记录</div>
      <div v-for="(t, i) in recent" :key="i" class="row">
        <span class="q">{{ t.question || '' }}</span>
        <span class="t">{{ fmtMs(t.elapsed_ms) }}</span>
      </div>
    </div>
  </div>
</template>
