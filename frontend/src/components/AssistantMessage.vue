<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { postJSON } from '../api/client'
import { ElMessage } from '../plugins/element-components'
import { fmtMs } from '../utils/format'
import { mediaCache, pickEntityName, resolveMedia } from '../utils/media'
import { openLightbox } from '../stores/lightbox'
import CiteText from './CiteText.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const root = ref(null)
const evidenceEl = ref(null)
const feedbackBusy = ref(false)

const detail = computed(() => props.message.detail)
const evidence = computed(() => detail.value?.evidence || [])
const attempts = computed(() => detail.value?.attempts || [])
const links = computed(() => detail.value?.links || [])
const vectorHits = computed(() => detail.value?.vectorHits || [])
const trace = computed(() => detail.value?.trace)

const stages = computed(() =>
  Object.entries(trace.value?.stage_ms || {}).sort((a, b) => b[1] - a[1])
)
const stageMax = computed(() => Math.max(...stages.value.map((s) => s[1]), 1))

/* 一条消息内同一张图只出现一次，避免连续多条证据重复 */
const evidenceThumbs = computed(() => {
  const map = {}
  const seen = new Set()
  for (const e of evidence.value) {
    const name = pickEntityName(e)
    const info = name ? mediaCache.get(name) : null
    if (!info?.thumb || seen.has(info.thumb)) continue
    seen.add(info.thumb)
    map[e.id] = { info, name }
  }
  return map
})

watch(
  () => evidence.value,
  (list) => {
    const names = new Set()
    for (const e of list) {
      const n = pickEntityName(e)
      if (n) names.add(n)
    }
    if (names.size) resolveMedia(names)
  },
  { immediate: true }
)

function onCite(id) {
  if (evidenceEl.value) evidenceEl.value.open = true
  nextTick(() => {
    const target = root.value?.querySelector(`.evidence-item[data-eid="${id}"]`)
    if (!target) return
    target.scrollIntoView({ block: 'center', behavior: 'smooth' })
    target.classList.remove('flash')
    void target.offsetWidth // 强制重排，保证连续点击也能重放动画
    target.classList.add('flash')
    setTimeout(() => target.classList.remove('flash'), 1300)
  })
}

function attemptLabel(a, i) {
  return a.ok
    ? `第 ${i + 1} 次：成功，返回 ${a.rows} 行`
    : `第 ${i + 1} 次：失败 — ${String(a.error || '').slice(0, 120)}`
}

function linkLine(l) {
  const matched = l.matched
    ? (l.candidates || []).map((c) => c.name).join('、')
    : '未匹配'
  return `${l.type}「${l.raw}」→ ${matched}`
}

async function sendFeedback(rating) {
  if (!props.message.traceId || feedbackBusy.value) return
  feedbackBusy.value = true
  try {
    await postJSON('/api/feedback', {
      trace_id: props.message.traceId,
      rating,
      comment: '',
    })
    props.message.feedbackGiven = rating
    ElMessage.success(rating > 0 ? '感谢反馈' : '已记录，我们会继续改进')
  } catch (e) {
    ElMessage.error('反馈提交失败，请稍后再试')
  } finally {
    feedbackBusy.value = false
  }
}
</script>

<template>
  <div ref="root" class="msg assistant">
    <div class="bubble" :class="{ cursor: !message.finished }">
      <!-- 首字还没回来时用骨架屏占位，比一个空气泡更像在思考 -->
      <el-skeleton v-if="!message.text && !message.finished" :rows="2" animated />
      <CiteText v-else :text="message.text" @cite="onCite" />
    </div>

    <div class="meta-row">
      <span
        v-for="(chip, i) in message.chips"
        :key="i"
        class="chip"
        :class="chip.tone"
      >{{ chip.text }}</span>

      <span v-if="message.traceId && !message.feedbackGiven" class="feedback">
        <button title="有帮助" @click="sendFeedback(1)">👍</button>
        <button title="没帮助" @click="sendFeedback(-1)">👎</button>
      </span>
      <span v-else-if="message.feedbackGiven" class="chip">
        {{ message.feedbackGiven > 0 ? '已记录 👍' : '已记录 👎' }}
      </span>
    </div>

    <template v-if="detail">
      <details v-if="evidence.length" ref="evidenceEl">
        <summary>证据（{{ evidence.length }} 条）</summary>
        <div>
          <div
            v-for="e in evidence"
            :key="e.id"
            class="evidence-item"
            :class="{ 'has-thumb': evidenceThumbs[e.id] }"
            :data-eid="e.id"
          >
            <img
              v-if="evidenceThumbs[e.id]"
              class="thumb"
              :class="{ mol: evidenceThumbs[e.id].info.label === 'Ingredient' }"
              :src="evidenceThumbs[e.id].info.thumb"
              :alt="evidenceThumbs[e.id].name"
              :title="`${evidenceThumbs[e.id].name}（点击查看大图）`"
              loading="lazy"
              @click="openLightbox(evidenceThumbs[e.id].name, evidenceThumbs[e.id].info)"
            />
            <div class="e-body">
              <span class="eid">[{{ e.id }}]</span>
              <span class="kind">{{ e.kind }}</span>
              <span>{{ e.title }}：{{ e.text }}</span>
            </div>
          </div>
        </div>
      </details>

      <details v-if="detail.cypher || attempts.length">
        <summary>图谱查询（Cypher）</summary>
        <div v-if="detail.cypher" class="code">{{ detail.cypher }}</div>
        <template v-if="attempts.length > 1">
          <div class="sub-label">执行过程：</div>
          <div
            v-for="(a, i) in attempts"
            :key="i"
            class="attempt"
            :class="a.ok ? 'ok' : 'fail'"
          >{{ attemptLabel(a, i) }}</div>
        </template>
        <template v-if="links.length">
          <div class="sub-label">实体链接：</div>
          <div class="code link-code">{{ links.map(linkLine).join('\n') }}</div>
        </template>
      </details>

      <details v-if="vectorHits.length">
        <summary>向量检索命中（{{ vectorHits.length }} 条）</summary>
        <div v-for="(hit, i) in vectorHits" :key="i" class="evidence-item">
          <span class="eid">{{ Number(hit.score || 0).toFixed(3) }}</span>
          <span class="kind">{{ hit.kind }}·{{ (hit.sources || []).join('+') }}</span>
          <span>{{ hit.title }}</span>
        </div>
      </details>

      <details v-if="trace && trace.stage_ms">
        <summary>执行轨迹</summary>
        <div v-for="[name, ms] in stages" :key="name" class="stage-bar">
          <span class="name">{{ name }}</span>
          <span class="track">
            <span class="fill" :style="{ width: (ms / stageMax) * 100 + '%' }"></span>
          </span>
          <span class="ms">{{ fmtMs(ms) }}</span>
        </div>
        <div class="trace-summary">
          总耗时 {{ fmtMs(trace.elapsed_ms) }} · 输入 {{ trace.prompt_tokens }} / 输出
          {{ trace.completion_tokens }} tokens · 估算 ¥{{
            Number(trace.cost_cny ?? 0).toFixed(4)
          }}
        </div>
      </details>
    </template>

    <div v-if="detail" class="trace-id">trace {{ message.traceId || '' }}</div>
  </div>
</template>
