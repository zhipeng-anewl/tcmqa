<script setup>
import { ref } from 'vue'
import { api } from '../api/client'
import { isDemo } from '../demo'
import { openLightbox } from '../stores/lightbox'

defineProps({ active: Boolean })
const emit = defineEmits(['ask'])

const busy = ref(false)
const status = ref('')
const statusError = ref(false)
const results = ref([])
const queryType = ref('')
const textQuery = ref('')
const searching = ref(false)
const searched = ref(false)

/* el-upload 在 auto-upload=false 时通过 change 事件把文件交给我们 */
function onUploadChange(file) {
  const raw = file?.raw
  if (raw) searchImage(raw)
}

async function searchImage(file) {
  if (busy.value) return
  // 演示版没有后端，图像推理跑不了；引导去用已经录好的文本检索
  if (isDemo) {
    statusError.value = false
    status.value = '演示版不接收上传图片，请用下方的外观描述检索（如「红色的果实」）'
    return
  }
  busy.value = true
  statusError.value = false
  status.value = '正在提取图像特征…'
  results.value = []

  try {
    const form = new FormData()
    form.append('file', file)
    // 注意：不能走 api()，它会强制 JSON 头，multipart 必须让浏览器自己设边界
    const res = await fetch('/api/vision/search-image?top_k=8', {
      method: 'POST',
      body: form,
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`${res.status} ${text.slice(0, 160)}`)
    }
    render(await res.json())
  } catch (err) {
    statusError.value = true
    status.value = '检索失败：' + err.message
  } finally {
    busy.value = false
    searched.value = true
  }
}

async function searchText() {
  const q = textQuery.value.trim()
  if (!q || searching.value) return
  searching.value = true
  statusError.value = false
  status.value = '正在匹配…'

  try {
    const data = await api(
      `/api/vision/search-text?q=${encodeURIComponent(q)}&top_k=8`
    )
    render(data)
  } catch (err) {
    statusError.value = true
    status.value = '检索失败：' + err.message
  } finally {
    searching.value = false
    searched.value = true
  }
}

function render(data) {
  results.value = data.results || []
  queryType.value = data.query_type || ''
  if (!results.value.length) {
    status.value = '没有找到相似药材'
    return
  }
  status.value =
    `${queryType.value === 'image' ? '以图搜药' : '以文搜图'} · ` +
    `${results.value.length} 个候选` +
    (data.disclaimer ? ' · 结果为相似度候选，非鉴定结论' : '')
}

function scorePct(it) {
  const top = results.value[0]?.score || 1
  return Math.max(6, Math.round((it.score / top) * 100))
}

function zoom(it) {
  openLightbox(it.name, {
    label: 'Herb',
    id: it.herb_id,
    thumb: it.cover,
    gallery: it.gallery || 0,
  })
}
</script>

<template>
  <div v-show="active" class="tab-body" id="tab-vision">
    <el-upload
      class="vision-upload"
      drag
      accept="image/*"
      :auto-upload="false"
      :show-file-list="false"
      :disabled="busy"
      :on-change="onUploadChange"
    >
      <div class="upload-inner">
        <p>{{ busy ? '正在提取图像特征…' : '拖入或点击上传药材照片' }}</p>
        <small>Chinese-CLIP 跨模态检索 · 返回相似候选，不是鉴定结论</small>
      </div>
    </el-upload>

    <div class="vision-search">
      <el-input
        v-model="textQuery"
        placeholder="或描述外观，如「红色的果实」"
        clearable
        @keyup.enter="searchText"
      >
        <template #append>
          <el-button :loading="searching" @click="searchText">搜索</el-button>
        </template>
      </el-input>
    </div>

    <div class="graph-legend" :class="{ 'error-text': statusError }">
      {{ status || '上传照片，或输入一句外观描述开始检索' }}
    </div>

    <div v-if="results.length" class="vision-results">
      <div v-for="it in results" :key="it.herb_id || it.name" class="vcard">
        <img
          :src="it.cover"
          :alt="it.name"
          :title="`${it.name}（点击看大图）`"
          loading="lazy"
          @click="zoom(it)"
        />
        <div class="vmeta">
          <div class="vname">{{ it.name }}</div>
          <div class="veffect">{{ it.effect || '未分类' }}</div>
          <el-tooltip
            :content="`相似度 ${Math.round((it.score || 0) * 100)}%`"
            placement="top"
            :show-after="200"
          >
            <div class="vscore">
              <el-progress
                :percentage="scorePct(it)"
                :show-text="false"
                :stroke-width="5"
                color="#2e6b50"
              />
            </div>
          </el-tooltip>
          <button class="vask" @click="emit('ask', it.followup)">追问这味药</button>
        </div>
      </div>
    </div>

    <el-empty
      v-else-if="searched && !busy && !searching"
      :image-size="72"
      description="没有找到相似药材，换个说法或换张照片试试"
    />
  </div>
</template>
