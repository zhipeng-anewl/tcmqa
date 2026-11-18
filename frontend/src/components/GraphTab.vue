<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from '../plugins/element-components'
import { api } from '../api/client'
import { openLightbox } from '../stores/lightbox'
import { graphStore } from '../stores/graph'
import { ui } from '../stores/ui'
import { nodeId, TYPE_COLOR, TYPE_LABEL, toNetworkModel } from '../utils/graph'
import GraphCanvas from './GraphCanvas.vue'

const props = defineProps({
  active: Boolean,
  /* 只有独立的图谱页才响应 #graph?q=，问答页侧栏不跟着整句问题自动搜索 */
  deepLink: { type: Boolean, default: false },
  /* 侧栏容器窄，画布要限制最小缩放、限制节点数 */
  compact: { type: Boolean, default: false },
})

/* 图上的节点上限：防止点着点着把几千个邻居全拉进来 */
const MAX_NODES = 60
/* 每次展开最多拉几个邻居 */
const EXPAND_LIMIT = 12
/* 侧栏里的节点上限：太多必然「字看不清」或「被裁掉」 */
const COMPACT_MAX_NODES = 9

const canvasRef = ref(null)
const query = ref('')
const searching = ref(false)
const errorText = ref('')
const selected = ref(null)
const nodes = ref([])
const edges = ref([])
const expandedIds = ref(new Set())

const typeLegend = Object.entries(TYPE_LABEL).map(([type, label]) => ({
  type,
  label,
  color: TYPE_COLOR[type],
}))

const empty = computed(() => nodes.value.length === 0)

function readQueryFromHash() {
  try {
    const raw = decodeURIComponent(location.hash.replace(/^#\/?/, ''))
    const qs = raw.split('?')[1] || ''
    return new URLSearchParams(qs).get('q') || ''
  } catch (e) {
    return ''
  }
}

function trimModel(model, maxNodes) {
  if (model.nodes.length <= maxNodes) return model
  const keep = new Set(model.nodes.slice(0, maxNodes).map((n) => n.id))
  return {
    nodes: model.nodes.filter((n) => keep.has(n.id)),
    edges: model.edges.filter((e) => keep.has(e.from) && keep.has(e.to)),
  }
}

/**
 * 证据 → 图数据行。
 * 注意：证据是 {id, kind, title, payload} 这种结构，真正的关系数据在 payload 里；
 * 直接把证据对象丢给图模型会造出名为 graph / E1 的假节点。
 * 语义检索命中的药材/成分/疾病文档没有 payload 关系，就用标题作为单节点补上。
 */
function evidenceToRows(evidence) {
  const rows = []
  const docKinds = new Set(['herb', 'ingredient', 'disease'])
  for (const e of evidence || []) {
    if (e.kind === 'graph' && e.payload) {
      rows.push(e.payload)
    } else if (docKinds.has(e.kind) && e.title) {
      rows.push({ [e.kind]: e.title })
    }
  }
  return rows
}

/* 把模型写进画布；anchor 用加粗描边标出来 */
function applyModel(model, anchorName = '') {
  const anchorKey = anchorName ? nodeId('herb', anchorName) : ''
  const trimmed = props.compact ? trimModel(model, COMPACT_MAX_NODES) : model
  nodes.value = trimmed.nodes.map((n) => ({ ...n, anchor: n.id === anchorKey }))
  edges.value = trimmed.edges
}

function mergeNeighbors(rootNode, neighbors, limit) {
  const byId = new Map(nodes.value.map((n) => [n.id, n]))
  byId.set(rootNode.id, { ...(byId.get(rootNode.id) || {}), ...rootNode, anchor: true })

  const edgeIds = new Set(edges.value.map((e) => e.id))
  const nextEdges = [...edges.value]

  for (const nb of neighbors.slice(0, limit)) {
    if (!nb.name || !nb.label) continue
    const kind = String(nb.label).toLowerCase()
    const id = nodeId(kind, nb.name)
    if (!byId.has(id)) {
      if (byId.size >= MAX_NODES) break
      byId.set(id, { id, label: nb.name, kind, type: nb.label })
    }
    const eid = `${rootNode.id}->${id}`
    if (!edgeIds.has(eid)) {
      edgeIds.add(eid)
      nextEdges.push({ id: eid, from: rootNode.id, to: id })
    }
  }

  nodes.value = [...byId.values()]
  edges.value = nextEdges
}

/* 查一个实体并把它和邻居画出来；reset=true 表示换一张新图 */
async function loadNode(name, type, { reset = false, limit = EXPAND_LIMIT } = {}) {
  const detail = await api(
    `/api/graph/node?name=${encodeURIComponent(name)}&label=${encodeURIComponent(type)}`
  )
  const kind = String(type).toLowerCase()
  const rootId = nodeId(kind, name)

  if (reset) {
    nodes.value = []
    edges.value = []
    expandedIds.value = new Set()
  }

  const rootNode = {
    id: rootId,
    label: name,
    kind,
    type,
    anchor: true,
    ref: detail.properties?.id || '',
  }
  mergeNeighbors(rootNode, detail.neighbors || [], limit)
  expandedIds.value = new Set([...expandedIds.value, rootId])

  selected.value = {
    id: rootId,
    name,
    type,
    ref: detail.properties?.id || '',
    // 疾病在图谱里是英文名，接口会带回中文别名，展示时优先用中文
    aliasZh: detail.alias_zh || '',
    neighborCount: detail.neighbor_count ?? (detail.neighbors || []).length,
  }
  return detail
}

async function searchNode() {
  const q = query.value.trim()
  if (!q || searching.value) return
  searching.value = true
  errorText.value = ''
  try {
    const found = await api(`/api/graph/search?q=${encodeURIComponent(q)}&limit=8`)
    if (!found.results?.length) {
      errorText.value = /[^\x00-\x7f]/.test(q)
        ? '没有找到匹配节点：疾病在图谱里用英文记录，可试试英文名（如 Diabetes）'
        : '没有找到匹配节点'
      return
    }
    const first = found.results[0]
    await loadNode(first.name, first.label, { reset: true })
    await nextTick()
    canvasRef.value?.fit()
  } catch (e) {
    errorText.value = '查询失败：' + e.message
  } finally {
    searching.value = false
  }
}

async function onSelect(id) {
  const node = nodes.value.find((n) => n.id === id)
  if (!node) return
  selected.value = {
    id: node.id,
    name: node.label,
    type: node.type,
    ref: node.ref || '',
    neighborCount: null,
  }
}

/* 邻域扩展：点了才拉，避免一点就把几十个节点全铺开 */
async function expandSelected() {
  const node = nodes.value.find((n) => n.id === selected.value?.id)
  if (!node || expandedIds.value.has(node.id)) return
  try {
    const detail = await loadNode(node.label, node.type, { limit: EXPAND_LIMIT })
    selected.value.neighborCount = detail.neighbor_count
    await nextTick()
    canvasRef.value?.stabilize()
  } catch (e) {
    errorText.value = '展开失败：' + e.message
  }
}

/* 双击节点：把它设为新的中心，重新拉一圈邻居 */
async function onActivate(id) {
  const node = nodes.value.find((n) => n.id === id)
  if (!node || searching.value) return
  searching.value = true
  errorText.value = ''
  try {
    await loadNode(node.label, node.type, { reset: true })
    await nextTick()
    canvasRef.value?.fit()
  } catch (e) {
    errorText.value = '切换中心失败：' + e.message
  } finally {
    searching.value = false
  }
}

/* 导出当前画布为 PNG，文件名带上中心实体名和日期 */
function exportPng() {
  const root = selected.value?.name || nodes.value[0]?.label || '关系图'
  const safe = String(root).replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 40)
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const ok = canvasRef.value?.exportPNG(`岐黄问答_${safe}_${stamp}.png`)
  if (ok) {
    ElMessage.success('已导出 PNG')
  } else {
    errorText.value = '导出失败：画布为空'
    ElMessage.error('导出失败：画布为空')
  }
}

function resetGraph() {
  nodes.value = []
  edges.value = []
  selected.value = null
  expandedIds.value = new Set()
  errorText.value = ''
}

function openCover() {
  const s = selected.value
  if (!s?.ref) return
  if (s.type === 'Herb') {
    openLightbox(s.name, {
      label: 'Herb',
      id: s.ref,
      thumb: `/media/covers/${s.ref}.webp`,
      gallery: 0,
    })
  } else if (s.type === 'Ingredient') {
    openLightbox(s.name, {
      label: 'Ingredient',
      id: s.ref,
      thumb: `/api/media/mol/${s.ref}`,
      gallery: 0,
    })
  }
}

const canExpand = computed(() => {
  const s = selected.value
  return Boolean(s && s.type && !expandedIds.value.has(s.id))
})

/* 对话产生新答案时，同步刷新图 */
watch(
  () => graphStore.revision,
  () => {
    const rows = evidenceToRows(graphStore.evidence)
    if (!rows.length) return
    const anchor = graphStore.links?.[0]?.candidates?.[0]?.name || ''
    applyModel(toNetworkModel(rows, anchor), anchor)
    selected.value = null
  }
)

watch(
  () => props.active,
  (v) => {
    if (v && nodes.value.length) nextTick(() => canvasRef.value?.fit())
  }
)

watch(
  () => ui.tab,
  (tab) => {
    if (!props.deepLink || tab !== 'graph') return
    const q = readQueryFromHash()
    if (q && q !== query.value) {
      query.value = q
      nextTick(searchNode)
    }
  }
)

onMounted(() => {
  if (props.deepLink) {
    const q = readQueryFromHash()
    if (q) {
      query.value = q
      nextTick(searchNode)
      return
    }
  }
  // 侧栏：把当前对话的证据直接画出来
  const rows = evidenceToRows(graphStore.evidence)
  if (rows.length) {
    const anchor = graphStore.links?.[0]?.candidates?.[0]?.name || ''
    applyModel(toNetworkModel(rows, anchor), anchor)
  }
})
</script>

<template>
  <div v-show="active" class="tab-body" id="tab-graph">
    <div class="graph-search">
      <el-input
        v-model="query"
        placeholder="搜索中药 / 成分 / 靶点 / 疾病"
        clearable
        @keyup.enter="searchNode"
      >
        <template #append>
          <el-button :loading="searching" @click="searchNode">搜索</el-button>
        </template>
      </el-input>
    </div>

    <div class="graph-stage">
      <GraphCanvas
        ref="canvasRef"
        :nodes="nodes"
        :edges="edges"
        :compact="compact"
        @select="onSelect"
        @activate="onActivate"
      />
      <div v-if="empty" class="graph-empty">
        <el-empty :image-size="56" description="搜索一个实体，或直接在左侧提问">
          <template #description>
            <p class="empty-title">搜索一个实体，或直接在左侧提问</p>
            <small>节点可拖拽、滚轮缩放；双击节点把它设为新的中心</small>
          </template>
        </el-empty>
      </div>
    </div>

    <div class="graph-bar">
      <div class="legend">
        <el-tag
          v-for="t in typeLegend"
          :key="t.type"
          size="small"
          effect="plain"
          :style="{ color: t.color, borderColor: t.color + '55' }"
        >{{ t.label }}</el-tag>
      </div>
      <div class="graph-actions">
        <el-tooltip content="缩放并居中显示全部节点" placement="top" :show-after="300">
          <el-button size="small" plain @click="canvasRef?.fit()">适应视图</el-button>
        </el-tooltip>
        <el-tooltip content="重新跑一遍力导向布局" placement="top" :show-after="300">
          <el-button size="small" plain @click="canvasRef?.stabilize()">重新布局</el-button>
        </el-tooltip>
        <el-tooltip content="导出当前视角为 PNG 图片" placement="top" :show-after="300">
          <el-button size="small" plain :disabled="empty" @click="exportPng">导出 PNG</el-button>
        </el-tooltip>
        <el-tooltip content="清空画布" placement="top" :show-after="300">
          <el-button size="small" plain :disabled="empty" @click="resetGraph">清空</el-button>
        </el-tooltip>
      </div>
    </div>

    <div class="graph-meta">
      <span>{{ nodes.length }} 个节点 / {{ edges.length }} 条边</span>
      <span v-if="errorText" class="error-text">{{ errorText }}</span>
    </div>

    <div v-if="selected" class="node-card">
      <div class="node-card-head">
        <span class="type-dot" :style="{ background: TYPE_COLOR[selected.type] }"></span>
        <b>{{ selected.aliasZh || selected.name }}</b>
        <el-tag size="small" effect="plain" :style="{ color: TYPE_COLOR[selected.type], borderColor: TYPE_COLOR[selected.type] + '55' }">
          {{ TYPE_LABEL[selected.type] || selected.type }}
        </el-tag>
        <span v-if="selected.ref" class="node-ref">{{ selected.ref }}</span>
      </div>
      <div v-if="selected.aliasZh" class="node-card-alias">
        图谱原名：{{ selected.name }}
      </div>
      <div class="node-card-body">
        <span v-if="selected.neighborCount != null" class="muted">
          共 {{ selected.neighborCount }} 个邻居 · 双击可设为新的中心
        </span>
        <span v-else class="muted">双击节点设为新的中心，或点「展开邻居」继续沿图走</span>
        <el-button v-if="canExpand" size="small" plain @click="expandSelected">展开邻居</el-button>
        <el-button v-if="selected.ref" size="small" plain @click="openCover">查看图片</el-button>
      </div>
    </div>
  </div>
</template>
