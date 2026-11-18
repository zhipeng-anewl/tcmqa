<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { fmtMs, intentLabel } from '../utils/format'
import { graphStore } from '../stores/graph'
import { demoQuestionList, findFixture, isDemo, loadEvents, replayEvents } from '../demo'
import Composer from './Composer.vue'
import AssistantMessage from './AssistantMessage.vue'

const EXAMPLES = [
  '人参含有哪些化学成分？',
  '槲皮素作用于哪些靶点？',
  '有哪些清热解毒的中药？',
  '为什么麻黄能治疗哮喘？',
  '治疗乳腺癌的中药有多少味？',
  '手脚冰凉适合吃什么中药？',
  '柴胡和人参有没有共同成分？',
]

/* 演示模式下，示例全部换成「真录过的问题」，避免点了没反应 */
const demoList = ref([])
const exampleList = computed(() =>
  isDemo && demoList.value.length ? demoList.value.slice(0, 7).map((it) => it.question) : EXAMPLES
)

onMounted(async () => {
  if (!isDemo) return
  try {
    demoList.value = await demoQuestionList()
  } catch (e) {
    /* 演示数据缺失时不阻塞页面 */
  }
})

const messages = ref([])
const sessionId = ref(null)
const streaming = ref(false)
const messagesEl = ref(null)
let seq = 0
let controller = null // 当前流式请求，清空会话时要主动中断

const sessionLabel = computed(() =>
  sessionId.value ? '会话 ' + sessionId.value.slice(0, 8) : '新会话'
)

function scrollBottom() {
  nextTick(() => {
    const box = messagesEl.value
    if (box) box.scrollTop = box.scrollHeight
  })
}

async function ask(question) {
  const q = (question || '').trim()
  if (!q || streaming.value) return
  streaming.value = true

  messages.value.push({ id: ++seq, role: 'user', text: q })

  // 必须是 reactive：流式事件会在推入数组后直接改这个对象
  const msg = reactive({
    id: ++seq,
    role: 'assistant',
    text: '',
    finished: false,
    plan: null,
    retrieval: null,
    evidence: [],
    citations: null,
    chips: [],
    traceId: null,
    detail: null,
    feedbackGiven: 0,
  })
  messages.value.push(msg)
  scrollBottom()

  try {
    if (isDemo) {
      await replayDemo(q, msg)
    } else {
      await streamAnswer(q, msg)
    }
  } catch (err) {
    if (err.name !== 'AbortError') msg.text = `请求失败：${err.message}`
  } finally {
    msg.finished = true
    streaming.value = false
    scrollBottom()
  }
}

/*
 * 演示模式：从静态 fixture 里回放录制好的 SSE 事件流。
 * 没录过的问题给出明确提示，并列出可以点的示例——比一句「演示版不可用」体验好。
 */
async function replayDemo(question, msg) {
  const fixture = await findFixture(question)
  if (!fixture) {
    const list = await demoQuestionList()
    const hints = list.slice(0, 6).map((it) => `· ${it.question}`).join('\n')
    msg.text =
      '这是**离线演示版**，只回放提前录制好的问答。\n\n' +
      '换个问法试试，下面这些都有完整结果：\n\n' +
      hints
    return
  }
  const events = await loadEvents(fixture.id)
  await replayEvents(events, (ev) => handleEvent(ev, msg))
}

function handleEvent(event, msg) {
  const data = event.data
  switch (event.type) {
    case 'meta':
      sessionId.value = data.session_id
      msg.traceId = data.trace_id
      break
    case 'plan':
      msg.plan = data
      msg.chips.push({ tone: 'accent', text: intentLabel(data.intent) })
      break
    case 'retrieval':
      msg.retrieval = data
      break
    case 'evidence':
      msg.evidence = data
      break
    case 'token':
      msg.text += data
      scrollBottom()
      break
    case 'citations':
      msg.citations = data
      break
    case 'cached':
      msg.chips.push({ tone: 'warn', text: '缓存命中' })
      break
    case 'error':
      msg.text = data
      break
    case 'done':
      finish(msg, data)
      break
  }
}

async function streamAnswer(question, msg) {
  controller = new AbortController()
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      session_id: sessionId.value,
      use_cache: true,
    }),
    signal: controller.signal,
  })
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sep
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const line = raw.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      let event
      try {
        event = JSON.parse(line.slice(5).trim())
      } catch (e) {
        continue
      }
      handleEvent(event, msg)
    }
  }
}

function finish(msg, data) {
  msg.finished = true

  msg.chips.push({ tone: '', text: fmtMs(data.latency_ms) })
  if (data.trace?.total_tokens) {
    msg.chips.push({ tone: '', text: data.trace.total_tokens + ' tokens' })
  }
  if (data.cached) msg.chips.push({ tone: 'warn', text: '缓存' })

  msg.traceId = data.trace_id || msg.traceId
  msg.detail = {
    evidence: data.evidence || [],
    cypher: data.cypher || '',
    attempts: data.attempts || [],
    links: data.links || [],
    vectorHits: data.vector_hits || [],
    trace: data.trace || null,
  }
  graphStore.set(msg.detail.evidence, msg.detail.links)
  scrollBottom()
}

function newSession() {
  controller?.abort()
  controller = null
  messages.value = []
  sessionId.value = null
  streaming.value = false
  graphStore.reset()
}

defineExpose({ ask })
</script>

<template>
  <section class="chat-panel">
    <div ref="messagesEl" class="messages">
      <div v-if="!messages.length" class="chat-empty">
        <h2>直接提问</h2>
        <p>问题会先判定意图，再决定走图谱查询还是语义检索；答案附带可核对的证据。</p>
        <div class="chips">
          <button v-for="q in exampleList" :key="q" class="chip-link" @click="ask(q)">
            {{ q }}
          </button>
        </div>
      </div>

      <template v-for="m in messages" :key="m.id">
        <div v-if="m.role === 'user'" class="msg user">
          <div class="bubble">{{ m.text }}</div>
        </div>
        <AssistantMessage v-else :message="m" />
      </template>
    </div>

    <Composer :disabled="streaming" @send="ask" />
    <div class="composer-hint">
      <span>{{ sessionLabel }}</span>
      <button class="link-btn" @click="newSession">清空对话</button>
    </div>
  </section>
</template>
