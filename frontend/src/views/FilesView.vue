<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { fileApi } from '../api'
import { hasPerm } from '../utils/perm'
import { fileToDataUrl } from '../utils/file'
import MobilePager from '../components/MobilePager.vue'

const canWrite = hasPerm('op.files.write')
const files = ref([])
const total = ref(0)
// 移动端分页：默认显示 10 条，“加载更多”每次 +10
const visibleCount = ref(10)
const pagedFiles = computed(() => filteredFiles.value.slice(0, visibleCount.value))
watch(() => filteredFiles.value.length, () => { visibleCount.value = 10 })
const query = ref('')
const toastMsg = ref('')
const uploading = ref(false)
const elFile = ref(null)
const selected = ref([])
const filterType = ref('')
const typeOptions = [
  { value: '', label: '全部类型' },
  { value: '文档', label: '文档' },
  { value: '图片', label: '图片' },
  { value: '表格', label: '表格' },
]

function fileType(name) {
  const ext = (name || '').split('.').pop().toLowerCase()
  if (['doc', 'docx', 'txt', 'md', 'pdf'].includes(ext)) return '文档'
  if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) return '图片'
  if (['xls', 'xlsx', 'csv'].includes(ext)) return '表格'
  return '其他'
}

const filteredFiles = computed(() =>
  !filterType.value ? files.value : files.value.filter((f) => fileType(f.filename) === filterType.value),
)

function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

async function load() {
  try { files.value = await fileApi.list({ q: query.value }) } catch (e) { files.value = [] }
}

function humanSize(n) {
  if (!n && n !== 0) return '—'
  if (n < 1024) return n + ' B'
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1048576).toFixed(1) + ' MB'
}

function fileIcon(name) {
  const ext = (name || '').split('.').pop().toLowerCase()
  if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) return 'IMG'
  if (['xls', 'xlsx', 'csv'].includes(ext)) return 'CSV'
  if (['pdf'].includes(ext)) return 'PDF'
  if (['doc', 'docx', 'txt', 'md'].includes(ext)) return 'DOC'
  return name ? ext.toUpperCase().slice(0, 5) : 'FILE'
}

async function onPick(e) {
  const input = e.target
  if (!input.files || !input.files.length) return
  const file = input.files[0]
  uploading.value = true
  try {
    const dataUrl = await fileToDataUrl(file)
    await fileApi.uploadJson({ data: dataUrl, filename: file.name, content_type: file.type || 'application/octet-stream' })
    toast('文件已上传'); await load()
  } catch (err) {
    toast('上传失败：' + (err.response?.data?.detail || err.message))
  } finally {
    uploading.value = false
    input.value = ''
  }
}

async function del(id) {
  try { await fileApi.remove(id); toast('文件已删除'); await load() } catch (e) { toast('删除失败') }
}

// 多选 / 批量删除
function toggleSel(id) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(id)
}

async function batchDel() {
  if (!selected.value.length) { toast('请先勾选要删除的数据'); return }
  try {
    await fileApi.batchRemove(selected.value)
    toast('已删除 ' + selected.value.length + ' 个文件')
    selected.value = []
    await load()
  } catch (e) { toast('批量删除失败：' + (e.response?.data?.detail || e.message)) }
}

async function download(row) {
  try {
    const blob = await fileApi.download(row.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = row.filename; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { toast('下载失败') }
}

onMounted(async () => {
  await load()
  try { const c = await fileApi.count(); total.value = c.total || 0 } catch (e) {}
})
</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div class="left">
        <button class="pri" @click="elFile && elFile.click()" :disabled="uploading" v-if="canWrite">
          {{ uploading ? '上传中…' : '＋ 上传文件' }}
        </button>
        <input ref="elFile" type="file" style="display:none" @change="onPick" />
        <button class="sm dan" @click="batchDel" v-if="canWrite">批量删除</button>
      </div>
      <div class="right">
        <SearchSelect v-model="filterType" class="type-sel" style="width:96px" :options="typeOptions" placeholder="全部类型" />
        <div class="searchbox"><input type="search" v-model="query" placeholder="搜索文件名" @keyup.enter="load"><svg class="lm" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4-4" stroke="currentColor" stroke-width="2"/></svg></div>
      </div>
    </div>

    <div class="filegrid">
      <div class="file-card" v-for="f in pagedFiles" :key="f.id">
        <label class="chk" style="position:absolute;top:8px;left:8px">
          <input type="checkbox" :checked="selected.includes(f.id)" @change="toggleSel(f.id)"><i></i>
        </label>
        <span class="more" style="color:var(--mut);cursor:pointer">⋮</span>
        <div class="fi">{{ fileIcon(f.filename) }}</div>
        <div class="fn">{{ f.filename }}</div>
        <div class="fm">{{ (f.content_type || '文件') }} · {{ humanSize(f.size) }}</div>
        <div class="ops" style="justify-content:center;margin-top:8px">
          <button class="mini" @click="download(f)">下载</button>
          <button class="mini dan" @click="del(f.id)" v-if="canWrite">删除</button>
        </div>
      </div>
    </div>
    <div v-if="!filteredFiles.length" class="empty">暂无文件 / 无匹配类型</div>
    <MobilePager :total="filteredFiles.length" v-model:visible="visibleCount" unit="项" />
    <div class="pager">
      <div class="pg-left"><span class="pg-info">共 <b>{{ total }}</b> 项</span>
        <SearchSelect style="width:106px" :searchable="false" placeholder="20 条/页" :options="[{ value: 20, label: '20 条/页' }, { value: 50, label: '50 条/页' }, { value: 100, label: '100 条/页' }]" /></div>
      <div class="pg-right">
        <button class="pg-btn" disabled>首页</button><button class="pg-btn" disabled>‹ 上一页</button>
        <button class="pg-btn cur">1</button>
        <button class="pg-btn" disabled>下一页 ›</button><button class="pg-btn" disabled>末页</button>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>
