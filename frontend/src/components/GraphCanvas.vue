<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DataSet, Network } from 'vis-network/standalone'
import { TYPE_COLOR } from '../utils/graph'

/**
 * vis-network 封装：只负责把节点/边画出来并允许交互。
 * 布局参数、配色、扩展逻辑都在调用方，这里保持无业务。
 */
const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  /* 侧栏这类窄容器：限制最小缩放，否则十几个节点会被压成看不清的小字 */
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'activate'])

const host = ref(null)
const nodesDS = new DataSet([])
const edgesDS = new DataSet([])
let network = null

/* 每种实体一套配色：浅底 + 深色描边，和宣纸主题一致 */
const GROUPS = Object.fromEntries(
  Object.entries(TYPE_COLOR).map(([type, color]) => [
    type,
    {
      shape: 'box',
      color: {
        background: `${color}14`,
        border: color,
        highlight: { background: `${color}2e`, border: color },
        hover: { background: `${color}22`, border: color },
      },
      font: { color },
    },
  ])
)

const OPTIONS = {
  autoResize: true,
  groups: GROUPS,
  nodes: {
    shape: 'box',
    borderRadius: 8,
    borderWidth: 1.4,
    margin: { top: 7, bottom: 7, left: 11, right: 11 },
    font: {
      size: 13,
      face: '-apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif',
      color: '#23211c',
    },
    chosen: true,
  },
  edges: {
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    color: {
      color: 'rgba(139,128,108,.5)',
      highlight: '#2e6b50',
      hover: '#2e6b50',
      inherit: false,
    },
    smooth: { enabled: true, type: 'continuous', roundness: 0.3 },
    width: 1,
    selectionWidth: 1.6,
    hoverWidth: 1.4,
  },
  // 力导向：小图（十几个节点）用 forceAtlas2 比 barnesHut 更聚拢、更少乱飞
  physics: {
    enabled: true,
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {
      gravitationalConstant: -62,
      centralGravity: 0.006,
      springLength: 150,
      springConstant: 0.08,
      damping: 0.5,
      avoidOverlap: 0.9,
    },
    stabilization: { enabled: true, iterations: 420, updateInterval: 30, fit: true },
  },
  interaction: {
    hover: true,
    dragNodes: true,
    dragView: true,
    zoomView: true,
    tooltipDelay: 180,
    navigationButtons: false,
    keyboard: false,
  },
  layout: { improvedLayout: true, randomSeed: 7 },
}

function toVisNode(n) {
  return {
    id: n.id,
    label: n.label,
    group: n.type,
    // 中心/锚点实体加粗描边，一眼看出根节点
    borderWidth: n.anchor ? 2.4 : 1.4,
  }
}

function applyData(nodes, edges) {
  if (!network) return

  const keep = new Set(nodes.map((n) => n.id))
  for (const id of nodesDS.getIds()) {
    if (!keep.has(id)) nodesDS.remove(id)
  }
  if (nodes.length) nodesDS.update(nodes.map(toVisNode))

  const keepE = new Set(edges.map((e) => e.id))
  for (const id of edgesDS.getIds()) {
    if (!keepE.has(id)) edgesDS.remove(id)
  }
  if (edges.length) edgesDS.update(edges)
}

/** 自适应视野，但保证最小缩放：窄容器里 fit 会把字缩到看不见 */
function fitReadable() {
  if (!network) return
  network.fit({ animation: { duration: 320 } })
  const minScale = props.compact ? 0.78 : 0.7
  if (network.getScale() < minScale) {
    network.moveTo({ scale: minScale, animation: { duration: 300 } })
  }
}

/**
 * 跑一次布局并在稳定后关掉物理模拟。
 * 关物理的原因：问答页侧栏和知识图谱页各有一个实例，常驻的力模拟会一直吃 CPU；
 * 稳定后位置基本不再变，拖拽仍然可用（只是不再自动回弹）。
 */
function settleAndFit() {
  if (!network) return
  network.setOptions({ physics: { enabled: true } })
  network.stabilize()
  network.once('stabilizationIterationsDone', () => {
    network.setOptions({ physics: { enabled: false } })
    fitReadable()
  })
}

onMounted(() => {
  network = new Network(host.value, { nodes: nodesDS, edges: edgesDS }, OPTIONS)
  network.on('selectNode', (params) => {
    const id = params.nodes && params.nodes[0]
    if (id) emit('select', id)
  })
  // 双击节点：交给上层把它设为新的中心（双击空白处仍是 vis 默认的放大）
  network.on('doubleClick', (params) => {
    const id = params.nodes && params.nodes[0]
    if (id) emit('activate', id)
  })
  applyData(props.nodes, props.edges)
  if (props.nodes.length) settleAndFit()
})

watch(
  () => [props.nodes, props.edges],
  ([nodes, edges]) => {
    if (!network) return
    applyData(nodes, edges)
    if (nodes.length) settleAndFit()
  }
)

onBeforeUnmount(() => {
  network?.destroy()
  network = null
})

/**
 * 导出 PNG。
 * vis-network 把节点/边画在 canvas 上，直接 toDataURL 拿不到背景（透明），
 * 所以先铺一层纸色底，再把同尺寸的 canvas 叠上去。
 *
 * 注意：容器里可能同时存在 0×0 的辅助画布（实例被隐藏时就会这样），
 * 所以要先过滤掉零尺寸的，再挑面积最大的那张当底图，不能直接取第一个。
 */
function exportPNG(filename = 'graph.png') {
  const canvases = host.value ? [...host.value.querySelectorAll('canvas')] : []
  const usable = canvases.filter((c) => c.width > 0 && c.height > 0)
  if (!usable.length) return false

  let base = usable[0]
  for (const c of usable) {
    if (c.width * c.height > base.width * base.height) base = c
  }

  const out = document.createElement('canvas')
  out.width = base.width
  out.height = base.height
  const ctx = out.getContext('2d')
  ctx.fillStyle = '#fdfcf9'
  ctx.fillRect(0, 0, out.width, out.height)

  for (const c of usable) {
    if (c.width === out.width && c.height === out.height) {
      ctx.drawImage(c, 0, 0)
    }
  }

  const link = document.createElement('a')
  link.download = filename
  link.href = out.toDataURL('image/png')
  document.body.appendChild(link)
  link.click()
  link.remove()
  return true
}

defineExpose({
  fit: fitReadable,
  focus: (id) => network?.focus(id, { scale: 1.2, animation: true }),
  stabilize: settleAndFit,
  exportPNG,
})
</script>

<template>
  <div ref="host" class="graph-host"></div>
</template>
