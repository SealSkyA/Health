<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { reportApi, tplApi, aiApi, aiApi2, medApi } from '../api'
import { fileToDataUrl } from '../utils/file'
import { hasPerm } from '../utils/perm'
import { mdToHtml } from '../utils/md'
import NameCombo from '../components/NameCombo.vue'
import TrendChart from '../components/TrendChart.vue'
import PinchZoom from '../components/PinchZoom.vue'
import MobilePager from '../components/MobilePager.vue'

const md = mdToHtml  // 模板内暴露：AI 分析结果按 Markdown 渲染

const docNames = ref([])               // 历史报告名称（当前账号可见，去重）
async function loadDocNames() {
  try { docNames.value = (await reportApi.docNames()) || [] } catch (e) { docNames.value = [] }
}

// ---- 检查项趋势 / 关注 ----
const trendMdl = ref(false)
const trendName = ref('')
const trendScope = ref('quarter')      // year / quarter / recent3，默认季度
const trendData = ref(null)
const trendLoading = ref(false)
const interests = ref([])              // 当前账号已关注的检查项 [{ name, doc_id }]
const groupMode = ref(false)           // 查看报告时：勾选后关注项合并到本报告一张图

const keyOf = (name, docId) => name + '#' + (docId || 0)
const interestedIn = (name, docId) => interests.value.some((i) => keyOf(i.name, i.doc_id || 0) === keyOf(name, docId || 0))
const interested = (name) => interests.value.some((i) => i.name === name)

async function loadTrend() {
  trendLoading.value = true
  try {
    trendData.value = await reportApi.trend(trendName.value.trim(), trendScope.value)
  } catch (e) {
    trendData.value = null
    toast('趋势加载失败：' + (e.response?.data?.detail || e.message))
  } finally { trendLoading.value = false }
}

function openTrend(name) {
  trendName.value = name || ''
  trendScope.value = 'quarter'
  trendData.value = null
  trendMdl.value = true
  loadTrend()
}

function setScope(s) { trendScope.value = s; loadTrend() }

async function toggleInterest(name) {
  if (!name || !name.trim()) { toast('该项名称无效'); return }
  const docId = groupMode.value && viewRow.value ? viewRow.value.id : null
  const on = interestedIn(name, docId || 0)
  try {
    if (on) {
      await reportApi.interestRemove(name, docId || undefined)
      interests.value = interests.value.filter((i) => keyOf(i.name, i.doc_id || 0) !== keyOf(name, docId || 0))
      toast('已取消关注「' + name + '」')
    } else {
      await reportApi.interestAdd(name, docId)
      if (!interestedIn(name, docId || 0)) interests.value.push({ name, doc_id: docId })
      toast(docId
        ? '已加入本报告组合图（与同报告其它关注项对照显示）'
        : '已关注「' + name + '」，可到首页查看走势')
    }
  } catch (e) { toast('操作失败：' + (e.response?.data?.detail || e.message)) }
}

async function loadInterests() {
  try {
    const d = await reportApi.interests()
    const arr = []
    for (const s of d.singles || []) arr.push({ name: s.name, doc_id: null })
    for (const g of d.groups || []) for (const s of g.series || []) arr.push({ name: s.name, doc_id: g.doc_id })
    interests.value = arr
  } catch (e) { interests.value = [] }
}

const rows = ref([])
const total = ref(0)
// 移动端分页：默认显示 10 条，“加载更多”每次 +10
const visibleCount = ref(10)
const pagedRows = computed(() => rows.value.slice(0, visibleCount.value))
watch(() => rows.value.length, () => { visibleCount.value = 10 })
const query = ref('')
const showMdl = ref(false)
const saving = ref(false)
const toastMsg = ref('')
const selected = ref([])
const startDate = ref('')
const endDate = ref('')
const selCat = ref('')

function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

const form = ref({ category: '体检', checked_at: '', addr: '', doctor: '', report_count: 0, note: '' })

// ---- 报告（子级）新增 / 编辑 / 查看 ----
const docMdl = ref(false)
const docForm = ref({ rid: 0, id: 0, name: '', note: '', items: [] })
const selTpl = ref('')
const templates = ref([])
const viewMdl = ref(false)
const viewRow = ref(null)
// 查看弹窗右侧：该检查记录绑定的用药记录（无绑定则不显示右栏）
const viewMeds = ref([])
const viewMedsLoading = ref(false)

// 父级展开 / 收起：展开区显示该检查记录下的报告列表
const expanded = ref({})
const docsMap = ref({})
// 弹窗放大 / 还原
const maxMdl = ref(false)
// 报告附件图片：待上传的本地文件 + 预览 / 已有附件图 / 大图查看
const pendingImg = ref(null)
const pendingImgUrl = ref('')
const editingImage = ref('')
const imgMdl = ref(false)
const imgUrl = ref('')
// 报告附件：待上传本地清单 / 已保存附件（在线清单）
const pendingAtts = ref([]) // { file, name, size }
const savedAtts = ref([])   // { name, path, size, mime }
const attBusy = ref(false)

function fmtSize(n) {
  if (!n) return '—'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}
function onPickAtts(ev) {
  const files = Array.from(ev.target.files || [])
  ev.target.value = ''
  for (const f of files) {
    if (f.size > 10 * 1024 * 1024) { toast('附件超过 10MB 限制：' + f.name); continue }
    // 已选同名文件视为替换：移除旧的待传项
    const dup = pendingAtts.value.findIndex((a) => a.name === f.name)
    if (dup >= 0) pendingAtts.value.splice(dup, 1)
    pendingAtts.value.push({ file: f, name: f.name, size: f.size })
  }
}
function dropAtt(i) { pendingAtts.value.splice(i, 1) }
async function uploadAtts(rid, did) {
  // 保存报告后把待传附件逐个上传（新建报告时 did 刚生成）
  for (const a of pendingAtts.value) {
    attBusy.value = true
    try {
      const dataUrl = await fileToDataUrl(a.file)
      const res = await reportApi.docAttachJson(rid, did, { name: a.name, file: dataUrl, mime: a.file.type || '' })
      savedAtts.value = res.attachments || []
    } finally {
      attBusy.value = false
    }
  }
  pendingAtts.value = []
}
async function removeAtt(idx) {
  if (attBusy.value) return
  attBusy.value = true
  try {
    const res = await reportApi.docAttachRemove(docForm.value.rid, docForm.value.id, idx)
    savedAtts.value = res.attachments || []
    toast('附件已删除')
  } catch (e) {
    toast('删除附件失败')
  } finally {
    attBusy.value = false
  }
}

function newRepItem() { return { name: '', ref_range: '', unit: '', value: '' } }
function addRepRow() { docForm.value.items.push(newRepItem()) }
function delRepRow(i) { docForm.value.items.splice(i, 1) }

// ---- OCR 识别 ----
const ocrBusy = ref(false)
const ocrLines = ref([]) // { name, value, unit, ref, checked }

async function onOcrFile(ev) {
  const f = ev.target.files && ev.target.files[0]
  ev.target.value = ''
  if (!f) return
  // 记录原图作为报告附件
  pendingImg.value = f
  if (pendingImgUrl.value) URL.revokeObjectURL(pendingImgUrl.value)
  pendingImgUrl.value = URL.createObjectURL(f)
  ocrBusy.value = true
  ocrLines.value = []
  try {
    const dataUrl = await fileToDataUrl(f)
    const r = await reportApi.ocrJson({ image: dataUrl, filename: f.name })
    const lines = (r.lines || []).map((s) => String(s).trim()).filter(Boolean)
    if (!lines.length) { toast('未识别到文字，图片已附加，可直接保存或换更清晰的图'); return }
    ocrLines.value = buildTable(r)
  } catch (e) {
    toast('识别失败：' + (e.response?.data?.detail || e.message))
  } finally {
    ocrBusy.value = false
  }
}

function removePendingImg() {
  pendingImg.value = null
  if (pendingImgUrl.value) URL.revokeObjectURL(pendingImgUrl.value)
  pendingImgUrl.value = ''
}

function viewImg(doc) {
  const src = typeof doc === 'string' ? doc : ((doc?.cover || doc?.image) ? '/static/' + (doc.cover || doc.image) : '')
  if (!src) return
  imgUrl.value = src
  imgMdl.value = true
}

// 按坐标把 OCR 散行重组回表格：找表头定位四列，按 y 聚类成数据行，
// 名称列内多碎片（单元格折行）按 y 顺序拼接
function buildTable(r) {
  const lines = r.lines || []
  const boxes = r.boxes || []
  const items = []
  for (let i = 0; i < lines.length; i++) {
    const text = String(lines[i] || '').trim()
    if (!text) continue
    const b = boxes[i]
    items.push(b
      ? { text, cx: (b[0][0] + b[2][0]) / 2, cy: (b[0][1] + b[2][1]) / 2 }
      : { text, cx: 0, cy: 0 })
  }
  if (!items.length) return []
  // 按 y 聚类成候选行
  const sorted = [...items].sort((a, b) => a.cy - b.cy)
  const rows = []
  for (const it of sorted) {
    const last = rows[rows.length - 1]
    if (last && Math.abs(it.cy - last[last.length - 1].cy) < 45) last.push(it)
    else rows.push([it])
  }
  // 找表头行（含 ≥2 个表头词）
  const kw = ['检验项目', '参考范围', '结果', '单位']
  let hdr = null
  for (const g of rows) {
    const n = g.filter((x) => kw.some((w) => x.text.includes(w))).length
    if (n >= 2) { hdr = g; break }
  }
  if (!hdr) {
    // 无表头：退回逐行文本模式
    return items.map((x) => ({ name: x.text, value: '', unit: '', ref: '', checked: true }))
  }
  const col = { name: null, value: null, unit: null, ref: null }
  for (const x of hdr) {
    if (x.text.includes('检验项目') || x.text.includes('项目')) col.name = x.cx
    else if (x.text.startsWith('结果')) col.value = x.cx
    else if (x.text.startsWith('单位')) col.unit = x.cx
    else if (x.text.includes('参考')) col.ref = x.cx
  }
  const inCol = (x, cx) => cx != null && Math.abs(x.cx - cx) < 130
  // 每数据行锚点 = 结果列（或单位列）的 cy
  const anchors = []
  for (const g of rows) {
    if (g === hdr) continue
    const hit = g.find((x) => inCol(x, col.value)) || g.find((x) => inCol(x, col.unit))
    if (hit) anchors.push(hit.cy)
  }
  const out = []
  for (const acy of anchors) {
    const rowItems = items.filter((x) => Math.abs(x.cy - acy) < 45)
    const nameCells = rowItems.filter((x) => inCol(x, col.name)).sort((a, b) => a.cy - b.cy)
    const valueCell = rowItems.find((x) => inCol(x, col.value)) || null
    const unitCell = rowItems.find((x) => inCol(x, col.unit)) || null
    const refCell = rowItems.find((x) => inCol(x, col.ref)) || null
    const name = nameCells.map((x) => x.text).join('').replace(/[\s·]+/g, '').trim()
    const value = valueCell ? valueCell.text.trim() : ''
    if (!name && !value) continue
    out.push({
      name,
      value,
      unit: unitCell ? unitCell.text.trim() : '',
      ref: refCell ? refCell.text.trim() : '',
      checked: true,
    })
  }
  return out
}

const ocrAllChecked = computed(() => ocrLines.value.length > 0 && ocrLines.value.every((l) => l.checked))
function toggleOcrAll() {
  const on = !ocrAllChecked.value
  ocrLines.value.forEach((l) => (l.checked = on))
}

// 勾选行填入明细
function applyOcrLines() {
  const picked = ocrLines.value.filter((l) => l.checked && (l.name && l.name.trim() || l.value && l.value.trim()))
  if (!picked.length) { toast('请先勾选识别出的行'); return }
  let added = 0
  for (const it of picked) {
    const name = (it.name || '').trim()
    if (!name) continue
    const value = (it.value || '').trim()
    const unit = (it.unit || '').trim()
    const ref = (it.ref || '').trim()
    const dup = docForm.value.items.find((x) => x.name === name && !x.value)
    if (dup) { dup.value = value || dup.value; dup.unit = unit || dup.unit; dup.ref_range = ref || dup.ref_range; added++ }
    else { docForm.value.items.push({ name, ref_range: ref, unit, value }); added++ }
  }
  if (!added) { toast('没有可填入的内容，请检查勾选'); return }
  toast('已填入 ' + added + ' 项，请核对参考范围/单位')
  ocrLines.value = []
}

// 查看报告弹窗：主 Tab（检验结果 / 用药记录 / 关联文件）
const viewMain = ref('items')
// 查看报告：所有项 / 异常项 切页
const viewTab = ref('all')
const viewAbnItems = computed(() => (viewRow.value?.items_detail || []).filter((it) => ['high', 'low', 'abnormal'].includes(it.result)))
// 录入 / 编辑报告：明细表切页（异常项带原数组索引，便于删除）
const docTab = ref('all')
const docAbnItems = computed(() => docForm.value.items
  .map((it, idx) => ({ it, idx }))
  .filter(({ it }) => ['high', 'low', 'abnormal'].includes(calcStatus(it))))

// 参考范围展示：优先 ref_range，旧数字数据拼 lo~hi
function rangeOf(it) {
  if (it.ref_range) return it.ref_range
  const parts = [it.ref_min, it.ref_max].filter(Boolean)
  return parts.length ? parts.join('~') : ''
}

// 前端实时判定（与后端算法一致）：normal / high / low / abnormal / ''
function calcStatus(it) {
  let v = (it.value || '').trim()
  const r = (it.ref_range || '').trim()
  if (!v || !r) return ''
  v = v.replace(/\s*[↑⇧↓⇩]\s*$/, '').trim() // OCR 尾巴箭头
  const num = (s) => { const n = parseFloat(s); return isNaN(n) ? null : n }
  let n = num(v)
  if (n === null) {
    const pm = v.match(/^\s*([><])\s*([\d.]+)\s*$/)
    if (pm) return pm[1] === '>' ? 'high' : 'low'
  }
  const m = r.match(/^[\s（(]*(-?[\d.]+)[\s~\-—～]+(-?[\d.]+)[)）\s]*$/)
  if (m) {
    const lo = num(m[1]), hi = num(m[2])
    if (n === null) return 'abnormal'
    if (n < lo) return 'low'
    if (n > hi) return 'high'
    return 'normal'
  }
  let m2 = r.match(/^[≤<]+\s*(-?[\d.]+)\s*$/)
  if (m2) { const b = num(m2[1]); if (n === null) return 'abnormal'; return n <= b ? 'normal' : 'high' }
  m2 = r.match(/^[≥>]+\s*(-?[\d.]+)\s*$/)
  if (m2) { const b = num(m2[1]); if (n === null) return 'abnormal'; return n >= b ? 'normal' : 'low' }
  return v === r ? 'normal' : 'abnormal'
}

const canWrite = hasPerm('op.report.write')
function fmtDt(v) {
  return v ? String(v).replace('T', ' ').slice(0, 16) : '—'
}
function statusText(s) {
  if (s === 'high') return '偏高'
  if (s === 'low') return '偏低'
  if (s === 'abnormal') return '异常'
  if (s === 'normal') return '正常'
  return ''
}

async function openDocMdl(r, doc) {
  docTab.value = 'all'
  removePendingImg()
  if (!docNames.value.length) await loadDocNames()   // 首次打开时加载历史名称
  editingImage.value = doc?.image ? '/static/' + doc.image : ''
  savedAtts.value = doc?.attachments || []
  pendingAtts.value = []
  docForm.value = doc
    ? {
        rid: r.id, id: doc.id, name: doc.name || '', note: doc.note || '',
        items: (doc.items_detail || []).map((it) => ({
          name: it.name || '', ref_range: it.ref_range || '', unit: it.unit || '', value: it.value || '',
        })),
      }
    : { rid: r.id, id: 0, name: '', note: '', items: [] }
  if (!doc && !docForm.value.name) {
    const cnt = (docsMap.value[r.id] || []).length
    docForm.value.name = '报告' + (cnt ? ' ' + (cnt + 1) : '')
  }
  if (!docForm.value.items.length) docForm.value.items = [newRepItem(), newRepItem()]
  if (!templates.value.length) {
    try { templates.value = await tplApi.list({ limit: 100 }) } catch (e) { templates.value = [] }
  }
  selTpl.value = ''
  ocrLines.value = []
  docMdl.value = true
}

function applyTpl() {
  const t = templates.value.find((x) => String(x.id) === String(selTpl.value))
  if (!t) return
  const detail = t.items_detail || []
  if (!detail.length) { toast('该模板没有结构化明细，无法套用'); return }
  docForm.value.items = detail.map((it) => ({
    name: it.name || '', ref_range: rangeOf(it), unit: it.unit || '', value: '',
  }))
  toast('已套用模板：' + t.name)
}

async function saveDoc() {
  const name = docForm.value.name.trim()
  if (!name) { toast('请填写报告名称'); return }
  const items = docForm.value.items.filter((it) => it.name && it.name.trim())
  if (!items.length) { toast('请至少填写一条检验结果'); return }
  saving.value = true
  try {
    const payload = { name, note: docForm.value.note, items }
    let savedId = docForm.value.id
    if (savedId) await reportApi.docUpdate(docForm.value.rid, savedId, payload)
    else { savedId = (await reportApi.docCreate(docForm.value.rid, payload)).id; docForm.value.id = savedId }
    // 有附件图片则上传保存（后端按报告 id 覆盖旧图）
    if (pendingImg.value && savedId) {
      const dataUrl = await fileToDataUrl(pendingImg.value)
      await reportApi.docImageJson(docForm.value.rid, savedId, {
        image: dataUrl,
        filename: pendingImg.value.name || 'img.png',
      })
    }
    // 有未上传附件则逐个上传
    if (pendingAtts.value.length && savedId) await uploadAtts(docForm.value.rid, savedId)
    removePendingImg()
    toast('报告已保存'); docMdl.value = false
    // 新名称登记进建议列表（去重），下次新增立即可选
    if (name && !docNames.value.includes(name)) docNames.value.push(name)
    docsMap.value = { ...docsMap.value, [docForm.value.rid]: await reportApi.docs(docForm.value.rid) }
    expanded.value = { ...expanded.value, [docForm.value.rid]: true }
    await load()
  } catch (e) { toast('保存失败：' + (e.response?.data?.detail || e.message)) } finally { saving.value = false }
}

// 展开 / 收起检查记录，加载其下报告
async function toggleExpand(r) {
  const on = !expanded.value[r.id]
  expanded.value = { ...expanded.value, [r.id]: on }
  if (on && !docsMap.value[r.id]) {
    try { docsMap.value = { ...docsMap.value, [r.id]: await reportApi.docs(r.id) } }
    catch (e) { docsMap.value = { ...docsMap.value, [r.id]: [] } }
  }
}

function openViewDoc(r, doc) {
  viewTab.value = 'all'
  groupMode.value = false
  viewRow.value = { ...doc, parent: r }
  viewMdl.value = true
  // 加载绑定在该检查记录下的用药记录（右边栏）
  viewMedsLoading.value = true
  viewMeds.value = []
  medApi.list({ report_id: r.id, limit: 50 }).then((res) => {
    if (viewRow.value?.parent?.id === r.id) viewMeds.value = Array.isArray(res) ? res : []
  }).catch(() => {
    if (viewRow.value?.parent?.id === r.id) viewMeds.value = []
  }).finally(() => { viewMedsLoading.value = false })
}

async function delDoc(r, doc) {
  if (!confirm('确定删除该报告？')) return
  try {
    await reportApi.docRemove(r.id, doc.id)
    toast('报告已删除')
    docsMap.value = { ...docsMap.value, [r.id]: await reportApi.docs(r.id) }
    await load()
  } catch (e) { toast('删除失败：' + (e.response?.data?.detail || e.message)) }
}

async function load() {
  try {
    rows.value = await reportApi.list({
      q: query.value,
      category: selCat.value || undefined,
      start_date: startDate.value || undefined,
      end_date: endDate.value || undefined,
    })
    // 保留用户自定义的展开/折叠状态：仅清理已不存在的行，不重置
    const ids = new Set(rows.value.map((r) => r.id))
    expanded.value = Object.fromEntries(
      Object.entries(expanded.value).filter(([k]) => ids.has(Number(k)))
    )
    docsMap.value = Object.fromEntries(
      Object.entries(docsMap.value).filter(([k]) => ids.has(Number(k)))
    )
  } catch (e) { rows.value = [] }
  loadAllDocs()
}

function search() {
  if (startDate.value && endDate.value && startDate.value > endDate.value) {
    toast('开始日期不能晚于结束日期'); return
  }
  load()
}

let editId = 0  // 当前弹窗编辑的检查记录 id（0 = 新增）

function openMdl(r) {
  if (r) {
    editId = r.id
    form.value = {
      category: r.category || '体检',
      checked_at: r.checked_at ? r.checked_at.slice(0, 16) : '',
      addr: r.addr || '', doctor: r.doctor || '', note: r.note || '',
    }
  } else {
    editId = 0
    form.value = { category: '体检', checked_at: '', addr: '', doctor: '', note: '' }
  }
  showMdl.value = true
}

async function save() {
  if (!form.value.addr) { toast('请填写检查地址'); return }
  saving.value = true
  try {
    if (editId) await reportApi.update(editId, { ...form.value })
    else await reportApi.create({ ...form.value })
    toast('检查记录已保存'); showMdl.value = false; await load()
  } catch (e) { toast('保存失败：' + (e.response?.data?.detail || e.message)) } finally { saving.value = false }
}

async function del(r) {
  if (!confirm('确定删除该检查记录？其下所有报告将一并删除')) return
  try { await reportApi.remove(r.id); toast('检查记录已删除'); await load() } catch (e) { toast('删除失败') }
}

// 多选 / 批量删除
const allChecked = computed(() => rows.value.length > 0 && selected.value.length === rows.value.length)

function toggleSel(id) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(id)
}

function toggleAll() {
  if (allChecked.value) selected.value = []
  else selected.value = rows.value.map((r) => r.id)
}

async function batchDel() {
  if (!selected.value.length) { toast('请先勾选要删除的数据'); return }
  try {
    await reportApi.batchRemove(selected.value)
    toast('已删除 ' + selected.value.length + ' 条记录')
    selected.value = []
    await load()
  } catch (e) { toast('批量删除失败：' + (e.response?.data?.detail || e.message)) }
}

onMounted(async () => {
  await load()
  loadInterests()
  try { const c = await reportApi.count(); total.value = c.total || 0 } catch (e) {}
})

// ---- 移动端卡片（检查记录 + 报告轮播）----
const isMobileCard = ref(window.matchMedia ? window.matchMedia('(max-width: 560px)').matches : false)
const swIdx = ref({})           // 每条记录的轮播当前索引：{ rid: idx }
const slidesEl = ref({})        // 每条记录轮播容器 DOM：{ rid: el }

function fmtCt(s) {
  if (!s) return '—'
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T?(\d{2}):(\d{2})/)
  if (!m) return s.replace('T', ' ').slice(0, 16)
  return m[1] + '年' + +m[2] + '月' + +m[3] + '日 ' + m[4] + ':' + m[5]
}

const docsOf = (r) => docsMap.value[r.id] || []
const itemCount = (d) => (d.items_detail || []).length

// 移动端：点击左区域弹出的操作菜单（新增/编辑/AI 分析/删除）
const sheetRow = ref(null)
function actSheet(r) { sheetRow.value = r }
function closeSheet() { sheetRow.value = null }

// 移动端：列表加载后并行拉取所有检查记录下的报告（供轮播）
async function loadAllDocs() {
  if (!isMobileCard.value) return
  const map = {}
  await Promise.all(rows.value.map(async (r) => {
    try { map[r.id] = await reportApi.docs(r.id) } catch (e) { map[r.id] = [] }
  }))
  docsMap.value = { ...docsMap.value, ...map }
}

function setSlidesRef(rid, el) {
  if (el) slidesEl.value[rid] = el
}

function onSwipe(r, e) {
  const el = e.target
  const idx = el.scrollWidth > 0 ? Math.round(el.scrollLeft / el.clientWidth) : 0
  if (swIdx.value[r.id] !== idx) swIdx.value = { ...swIdx.value, [r.id]: idx }
}

function dotTo(r, i) {
  const el = slidesEl.value[r.id]
  if (!el) return
  el.scrollTo({ left: i * el.clientWidth, behavior: 'smooth' })
  swIdx.value = { ...swIdx.value, [r.id]: i }
}

// ---- AI 分析 ----
const aiMdl = ref(false)
const aiScope = ref(null)       // { kind: 'record' | 'doc', record, doc? }
const aiBusy = ref(false)
const aiQ = ref('')
const aiGroups = ref([])        // [{ alias, items: [{ id, name, enabled }] }]
const aiAlias = ref('')
const aiModel = ref('')
const aiHist = ref([])          // 当前范围历史
const aiExpanded = ref({})      // 历史展开行
const aiResult = ref('')        // 本次分析结果（流式追加）
const aiRetry = ref('')         // 限流自动重试提示

const aiScopeTitle = computed(() => {
  const s = aiScope.value
  if (!s) return ''
  if (s.kind === 'doc') return `AI 分析 · 报告「${s.doc?.name || '未命名'}」（所属记录 #${s.record.id}）`
  return `AI 分析 · 整条检查记录 #${s.record.id}（${s.record.addr || '—'}）`
})

async function loadAiModels() {
  if (aiGroups.value.length) return
  try {
    const list = await aiApi.list({ limit: 100 })
    const map = {}
    for (const m of list) {
      if (!m.enabled) continue
      if (!map[m.alias]) map[m.alias] = { alias: m.alias, items: [] }
      map[m.alias].items.push({ id: m.id, name: m.name, enabled: m.enabled })
    }
    aiGroups.value = Object.values(map)
    if (aiGroups.value.length) {
      aiAlias.value = aiGroups.value[0].alias
      const g = aiGroups.value[0]
      if (g.items.length) aiModel.value = g.items[0].name
    }
  } catch (e) { aiGroups.value = [] }
}

function pickAlias() {
  const g = aiGroups.value.find((x) => x.alias === aiAlias.value)
  aiModel.value = (g && g.items.length) ? g.items[0].name : ''
}

async function openAiMdl(scope) {
  aiScope.value = scope
  aiQ.value = ''
  aiResult.value = ''
  await loadAiModels()
  aiExpanded.value = {}
  await loadAiHist()
  aiMdl.value = true
}

async function loadAiHist() {
  const s = aiScope.value
  if (!s) return
  try {
    aiHist.value = await aiApi2.listAnalyses({
      record_id: s.record.id,
      doc_id: s.kind === 'doc' ? s.doc.id : undefined,
    })
  } catch (e) { aiHist.value = [] }
}

async function runAnalyze() {
  const s = aiScope.value
  if (!aiAlias.value || !aiModel.value) { toast('请先选择 AI 供应商和模型'); return }
  aiBusy.value = true
  aiResult.value = ''
  aiRetry.value = ''
  try {
    // 流式读取：AI 边生成边显示，限流自动重试实时提示
    const token = localStorage.getItem('token')
    const resp = await fetch('/api/ai/analyze-report-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
      body: JSON.stringify({
        record_id: s.record.id,
        doc_id: s.kind === 'doc' ? s.doc.id : undefined,
        alias: aiAlias.value,
        model: aiModel.value,
        question: aiQ.value || undefined,
      }),
    })
    if (!resp.ok) {
      let msg = 'HTTP ' + resp.status
      try { msg = (await resp.json()).detail || msg } catch (e) {}
      throw new Error(msg)
    }
    const reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const ev = buf.slice(0, idx); buf = buf.slice(idx + 2)
        if (!ev.startsWith('data: ')) continue
        let d
        try { d = JSON.parse(ev.slice(6)) } catch (e) { continue }
        if (d.delta) { aiResult.value += d.delta; aiRetry.value = '' }
        else if (d.retry) { aiRetry.value = d.message + '（第 ' + (d.attempt || 1) + ' 次）' }
        else if (d.error) { throw new Error(d.error) }
        else if (d.done) { /* 完成，无需额外处理 */ }
      }
    }
    if (!aiResult.value.trim()) aiResult.value = '（模型未返回内容）'
    await loadAiHist()
  } catch (e) { toast('分析失败：' + (e.message || e.response?.data?.detail)) }
  finally { aiBusy.value = false }
}

async function delAnalysis(a) {
  if (!confirm('删除这条 AI 分析记录？')) return
  try { await aiApi2.deleteAnalysis(a.id); toast('已删除'); await loadAiHist() }
  catch (e) { toast('删除失败') }
}

</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div class="left">
        <button class="pri" @click="openMdl" v-if="canWrite">＋ 新增检查记录</button>
        <button class="sm dan" @click="batchDel" v-if="canWrite">批量删除</button>
      </div>
    </div>

    <!-- 筛选区：上=时间区间，下=类型（小）+ 搜索框（右对齐内容） -->
    <div class="rp-filters">
      <div class="rf-row rf-dates">
        <span class="flabel" style="margin:0">时间区间</span>
        <input type="date" v-model="startDate" @change="search">
        <span class="rf-to">至</span>
        <input type="date" v-model="endDate" @change="search">
      </div>
      <div class="rf-row rf-actions">
        <SearchSelect v-model="selCat" class="cat-sel" @change="search" :options="[{ value: '', label: '全部类型' }, { value: '体检', label: '体检' }, { value: '专项', label: '专项' }, { value: '复查', label: '复查' }]" placeholder="全部类型" />
        <div class="searchbox rf-search"><input type="search" v-model="query" placeholder="搜索地址 / 负责人" @keyup.enter="search"><svg class="lm" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4-4" stroke="currentColor" stroke-width="2"/></svg></div>
      </div>
    </div>

    <!-- 移动端：检查记录卡片（左信息 + 右报告轮播） -->
    <div class="rp-cards">
      <div class="rp-card" v-for="r in pagedRows" :key="'c' + r.id">
        <div class="rp-left" @click="actSheet(r)">
          <div class="rp-row"><b>检查时间</b><span>{{ fmtCt(r.checked_at) }}</span></div>
          <div class="rp-row"><b>检查地址</b><span>{{ r.addr || '—' }}</span></div>
          <div class="rp-row"><b>负责人</b><span>{{ r.doctor || '—' }}</span></div>
          <div class="rp-row"><b>备注</b><span>{{ r.note || '—' }}</span></div>
          <div class="rp-tip">点此操作 ⋮</div>
        </div>
        <div class="rp-swipe">
          <template v-if="docsOf(r).length">
            <div class="rp-slides" :ref="(el) => setSlidesRef(r.id, el)" @scroll="onSwipe(r, $event)">
              <div class="rp-slide" v-for="(d, di) in docsOf(r)" :key="d.id">
                <div class="rp-imgbox">
                  <img v-if="d.cover" :src="'/static/' + d.cover" @click="viewImg(d)" loading="lazy" :alt="d.name">
                  <div v-else class="rp-noimg" @click="openViewDoc(r, d)">无附件图</div>
                </div>
                <div class="rp-name" @click="openViewDoc(r, d)">{{ d.name || '未命名报告' }}</div>
                <div class="rp-meta">{{ fmtCt(d.created_at) }}<span class="rp-bar">|</span>{{ itemCount(d) }} 项</div>
                <div class="rp-ops">
                  <button class="mini pri" @click="openViewDoc(r, d)">查看</button>
                  <button class="mini ai" @click="openAiMdl({ kind: 'doc', record: r, doc: d })">AI 分析</button>
                  <button class="mini" @click="openDocMdl(r, d)" v-if="canWrite">编辑</button>
                  <button class="mini dan" @click="delDoc(r, d)" v-if="canWrite">删除</button>
                </div>
              </div>
            </div>
            <div class="rp-dots" v-if="docsOf(r).length > 1">
              <i v-for="(d, di) in docsOf(r)" :key="d.id" :class="{ on: (swIdx[r.id] || 0) === di }" @click="dotTo(r, di)"></i>
            </div>
          </template>
          <div v-else class="rp-empty">
            <span>暂无报告</span>
            <button class="mini pri" @click="openDocMdl(r)" v-if="canWrite">＋ 新增</button>
          </div>
        </div>
      </div>
      <div v-if="!rows.length" class="t-mut" style="text-align:center;padding:28px">暂无检查记录，点「＋ 新增检查记录」创建</div>
    </div>

    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:36px"><label class="chk"><input type="checkbox" :checked="allChecked" @change="toggleAll"><i></i></label></th>
          <th style="width:36px"></th>
          <th style="width:76px">类别</th><th>检查时间</th><th>检查地址</th><th>负责人</th><th>已有报告</th><th>备注</th><th style="width:150px;white-space:nowrap">操作</th>
        </tr></thead>
        <tbody>
          <template v-for="r in pagedRows" :key="r.id">
          <tr :class="{ 'row-open': expanded[r.id] }">
            <td><label class="chk"><input type="checkbox" :checked="selected.includes(r.id)" @change="toggleSel(r.id)"><i></i></label></td>
            <td>
              <button class="mini exp" :class="{ on: expanded[r.id] }" @click="toggleExpand(r)" :title="expanded[r.id] ? '收起' : '展开报告列表'">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
            </td>
            <td><span class="badge info">{{ r.category || '未分类' }}</span></td>
            <td class="t-num">{{ r.checked_at ? r.checked_at.replace('T', ' ').slice(0, 16) : '—' }}</td>
            <td>{{ r.addr || '—' }}</td>
            <td>{{ r.doctor || '—' }}</td>
            <td class="t-num" :style="r.report_count ? 'color:var(--acc)' : ''">{{ r.report_count || 0 }}</td>
            <td class="t-mut" style="max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.note || '—' }}</td>
            <td><div class="ops">
              <button class="mini" @click="openMdl(r)" v-if="canWrite" title="编辑该检查记录">编辑</button>
              <button class="mini pri" @click="openDocMdl(r)" v-if="canWrite">新增</button>
              <button class="mini ai" @click="openAiMdl({ kind: 'record', record: r })">AI 分析</button>
              <button class="mini dan" @click="del(r)" v-if="canWrite">删除</button>
            </div></td>
          </tr>
          <!-- 展开区：该检查记录下的报告列表 -->
          <tr v-if="expanded[r.id]" class="exp-row">
            <td colspan="9" style="padding:0">
              <div class="docs-box">
                <template v-if="(docsMap[r.id] || []).length">
                  <div class="doc-head">报告列表（{{ docsMap[r.id].length }} 份）</div>
                  <table class="med-tbl">
                    <thead><tr>
                      <th style="width:30px">#</th><th>报告名称</th><th>备注</th><th>附件</th><th>检验项数</th><th>录入时间</th><th style="width:170px">操作</th>
                    </tr></thead>
                    <tbody>
                      <tr v-for="(doc, i) in docsMap[r.id]" :key="doc.id">
                        <td class="t-mut">{{ i + 1 }}</td>
                        <td><b>{{ doc.name || '未命名报告' }}</b></td>
                        <td class="t-mut">{{ doc.note || '—' }}</td>
                        <td>
                          <img v-if="doc.image" :src="'/static/' + doc.image" class="att-thumb" @click="viewImg(doc)" loading="lazy" :title="doc.name">
                          <span v-else class="t-mut">—</span>
                        </td>
                        <td class="t-num">{{ (doc.items_detail || []).length }} 项</td>
                        <td class="t-num">{{ doc.created_at ? doc.created_at.replace('T', ' ').slice(0, 16) : '—' }}</td>
                        <td><div class="ops">
                          <button class="mini" @click="openViewDoc(r, doc)">查看</button>
                          <button class="mini ai" @click="openAiMdl({ kind: 'doc', record: r, doc })">AI 分析</button>
                          <button class="mini" @click="openDocMdl(r, doc)" v-if="canWrite">编辑</button>
                          <button class="mini dan" @click="delDoc(r, doc)" v-if="canWrite">删除</button>
                        </div></td>
                      </tr>
                      <tr v-if="!(docsMap[r.id] || []).length"><td colspan="7" class="t-mut" style="text-align:center;padding:14px">暂无报告</td></tr>
                    </tbody>
                  </table>
                </template>
                <template v-else>
                  <div style="padding:14px;font-size:12.5px;color:var(--mut)">暂无报告，点「新增」为这条检查记录添加报告</div>
                </template>
              </div>
            </td>
          </tr>
          </template>
          <tr v-if="!rows.length"><td colspan="9" class="t-mut" style="text-align:center;padding:28px">暂无检查记录，点「＋ 新增检查记录」创建</td></tr>
        </tbody>
      </table>
    </div>
    <MobilePager :total="total" v-model:visible="visibleCount" unit="条" />
    <div class="pager">
      <div class="pg-left"><span class="pg-info">共 <b>{{ total }}</b> 条</span>
        <SearchSelect style="width:106px" :searchable="false" placeholder="20 条/页" :options="[{ value: 20, label: '20 条/页' }, { value: 50, label: '50 条/页' }, { value: 100, label: '100 条/页' }]" /></div>
      <div class="pg-right">
        <button class="pg-btn" disabled>首页</button><button class="pg-btn" disabled>‹ 上一页</button>
        <button class="pg-btn cur">1</button>
        <button class="pg-btn" disabled>下一页 ›</button><button class="pg-btn" disabled>末页</button>
      </div>
    </div>

    <div class="modal-mask" :class="{ show: showMdl }">
      <div class="modal panel" :class="{ full: maxMdl }">
        <div class="mbar">
          <h3>{{ editId ? '编辑检查记录' : '新增检查记录' }}</h3>
          <div class="mtools">
            <button v-if="!maxMdl" class="mt-btn" title="放大" @click="maxMdl = true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5"/><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M16 21h5v-5"/></svg></button>
            <button v-else class="mt-btn" title="还原" @click="maxMdl = false"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h5V3"/><path d="M21 8h-5V3"/><path d="M3 16h5v5"/><path d="M21 16h-5v5"/></svg></button>
            <button class="mt-btn" title="关闭" @click="showMdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">选择类别后登记一次检查，之后可在这条记录下新增多份报告</div>
        <div class="mbody">
        <div class="fgrid rp-fg">
          <div class="field"><div class="flabel">类别 <span style="color:var(--err)">*</span></div><span class="flc">：</span><SearchSelect v-model="form.category" :options="[{ value: '体检', label: '体检' }, { value: '专项', label: '专项' }, { value: '复查', label: '复查' }]" placeholder="选择类别" /></div>
          <div class="field"><div class="flabel">检查时间</div><span class="flc">：</span><input type="datetime-local" v-model="form.checked_at"></div>
          <div class="field"><div class="flabel">检查地址 <span style="color:var(--err)">*</span></div><span class="flc">：</span><input type="text" v-model="form.addr" placeholder="检查机构 / 地址"></div>
          <div class="field"><div class="flabel">负责人</div><span class="flc">：</span><input type="text" v-model="form.doctor" placeholder="负责人"></div>
          <div class="field span2"><div class="flabel">备注</div><span class="flc">：</span><input type="text" v-model="form.note" placeholder="备注（可选）"></div>
        </div>
        </div>
        <div class="modal-ft">
          <button @click="showMdl = false">取消</button>
          <button class="pri" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 新增 / 编辑报告 -->
    <div class="modal-mask" :class="{ show: docMdl }">
      <div class="modal wide panel" :class="{ full: maxMdl }">
        <div class="mbar">
          <h3>{{ docForm.id ? '编辑报告' : '新增报告' }}</h3>
          <div class="mtools">
            <button v-if="!maxMdl" class="mt-btn" title="放大" @click="maxMdl = true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5"/><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M16 21h5v-5"/></svg></button>
            <button v-else class="mt-btn" title="还原" @click="maxMdl = false"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h5V3"/><path d="M21 8h-5V3"/><path d="M3 16h5v5"/><path d="M21 16h-5v5"/></svg></button>
            <button class="mt-btn" title="关闭" @click="docMdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">为检查记录登记一份报告 · 检验结果自动对照参考范围判定</div>
        <div class="mbody">
        <div class="fgrid rp-fg">
          <div class="field span2"><div class="flabel">报告名称 <span style="color:var(--err)">*</span></div><span class="flc">：</span><NameCombo v-model="docForm.name" :options="docNames" placeholder="如：血常规 / 生化全套（输入或选择历史名称）"></NameCombo></div>
          <div class="field span2"><div class="flabel">备注</div><span class="flc">：</span><input type="text" v-model="docForm.note" placeholder="报告备注（可选）"></div>
        </div>
        <div class="rp-tpl">
          <div class="flabel">套用模板</div><span class="flc">：</span>
          <SearchSelect v-model="selTpl" @change="applyTpl" :options="[{ value: '', label: '— 选择报告模板 —' }, ...templates.map((t) => ({ value: t.id, label: t.name }))]" placeholder="选择报告模板" />
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px">
          <button class="sm" @click="addRepRow">＋ 添加检验项</button>
          <button class="sm" :disabled="ocrBusy" @click="$refs.ocrFile.click()">{{ ocrBusy ? '识别中…' : '识别报告图片' }}</button>
        </div>
        <input ref="ocrFile" type="file" accept="image/*" style="display:none" @change="onOcrFile">
        <div class="att-box" v-if="pendingImgUrl || editingImage">
          <img :src="pendingImgUrl || editingImage" class="att-preview" @click="viewImg(pendingImgUrl || editingImage)">
          <button v-if="pendingImgUrl" class="sm dan" @click="removePendingImg">移除</button>
          <span v-else class="t-mut" style="font-size:11.5px">已附加图片 · 选新图识别可替换</span>
        </div>
        <!-- 附件上传 -->
        <div style="margin:2px 0 10px">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <b style="font-size:12.5px">附件</b>
            <button class="sm" :disabled="attBusy" @click="$refs.attFile.click()">＋ 上传附件</button>
            <span class="t-mut" style="font-size:11px">任意文件 · 单个 ≤ 10MB · 保存报告时自动上传</span>
          </div>
          <input ref="attFile" type="file" style="display:none" multiple @change="onPickAtts">
          <div class="att-list" v-if="pendingAtts.length || savedAtts.length">
            <div class="att-item" v-for="(a, i) in savedAtts" :key="'s' + i">
              <a class="att-name" :href="'/static/' + a.path" target="_blank" rel="noopener" title="打开附件">{{ a.name }}</a>
              <span class="t-mut" style="font-size:11px">{{ fmtSize(a.size) }}</span>
              <button class="mini dan" :disabled="attBusy" @click="removeAtt(i)">删除</button>
            </div>
            <div class="att-item" v-for="(a, i) in pendingAtts" :key="'p' + i">
              <span class="att-name" style="color:var(--fg)">📎 {{ a.name }}<em class="t-mut" style="font-style:normal;font-size:11px">（待上传）</em></span>
              <span class="t-mut" style="font-size:11px">{{ fmtSize(a.size) }}</span>
              <button class="mini dan" @click="dropAtt(i)">移除</button>
            </div>
          </div>
        </div>
        <div class="ocrbar" v-if="ocrBusy"><span class="spin"></span> 正在识别报告图片（首次约 10 秒，请稍候）…</div>
        <div class="ocr-panel" v-if="!ocrBusy && ocrLines.length">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">
            <b style="font-size:12.5px">识别结果（已按表格自动重组，可直接修改）</b>
            <label style="font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer">
              <input type="checkbox" :checked="ocrAllChecked" @change="toggleOcrAll"> 全选
            </label>
            <button class="sm pri" @click="applyOcrLines">✓ 填入明细</button>
            <button class="sm" @click="ocrLines = []">清空</button>
            <span class="t-mut" style="font-size:11.5px">识别不准的字段可直接修改，勾选后填入下方明细表</span>
          </div>
          <div class="ocr-list">
            <div class="ocr-grid ocr-head">
              <span></span><span>检验项名称</span><span>单位</span><span>结果值</span><span>参考范围</span>
            </div>
            <div v-for="(l, i) in ocrLines" :key="i" class="ocr-grid">
              <input type="checkbox" v-model="l.checked">
              <input v-model="l.name" class="ocr-txt" placeholder="检验项名称">
              <input v-model="l.unit" class="ocr-txt" placeholder="单位">
              <input v-model="l.value" class="ocr-txt ocr-num" placeholder="结果值">
              <input v-model="l.ref" class="ocr-txt" placeholder="参考范围">
            </div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:12px;margin:2px 0 10px;flex-wrap:wrap">
          <div class="tabs">
            <button :class="{ on: docTab === 'all' }" @click="docTab = 'all'">所有项（{{ docForm.items.length }}）</button>
            <button :class="{ on: docTab === 'abn' }" @click="docTab = 'abn'">异常项（{{ docAbnItems.length }}）</button>
          </div>
          <span class="t-mut" style="font-size:11.5px">异常项按当前填写的值对照参考范围实时判定</span>
        </div>
        <div class="tbl-wrap">
          <table class="med-tbl">
            <thead><tr>
              <th style="width:30px">#</th><th>检验项名称 <span style="color:var(--err)">*</span></th><th style="width:90px">单位</th>
              <th style="width:130px">结果值</th><th>参考范围</th><th style="width:70px">判定</th><th style="width:40px"> </th>
            </tr></thead>
            <tbody>
              <template v-if="docTab === 'all'">
                <tr v-for="(it, i) in docForm.items" :key="i">
                  <td class="t-mut">{{ i + 1 }}</td>
                  <td><input v-model="it.name" placeholder="检验项名称"></td>
                  <td><input v-model="it.unit" placeholder="单位"></td>
                  <td><input v-model="it.value" placeholder="实测值"></td>
                  <td><input v-model="it.ref_range" placeholder="如 3.5~9.5 / 阴性"></td>
                  <td><span :class="'rs ' + calcStatus(it)">{{ statusText(calcStatus(it)) }}</span></td>
                  <td><button class="mini dan" @click="delRepRow(i)">删</button></td>
                </tr>
              </template>
              <template v-else>
                <tr v-for="(row, i) in docAbnItems" :key="i">
                  <td class="t-mut">{{ i + 1 }}</td>
                  <td><input v-model="row.it.name" placeholder="检验项名称"></td>
                  <td><input v-model="row.it.unit" placeholder="单位"></td>
                  <td><input v-model="row.it.value" placeholder="实测值"></td>
                  <td><input v-model="row.it.ref_range" placeholder="如 3.5~9.5 / 阴性"></td>
                  <td><span :class="'rs ' + calcStatus(row.it)">{{ statusText(calcStatus(row.it)) }}</span></td>
                  <td><button class="mini dan" @click="delRepRow(row.idx)">删</button></td>
                </tr>
                <tr v-if="!docAbnItems.length"><td colspan="7" class="t-mut" style="text-align:center;padding:18px">暂无异常项，全部在参考范围内</td></tr>
              </template>
            </tbody>
          </table>
        </div>
        <div class="t-mut" style="font-size:11.5px;margin-top:6px">共 {{ docForm.items.length }} 项检验结果 · 超出参考范围自动提醒：<span class="rs high">↑ 偏高</span> <span class="rs low">↓ 偏低</span> <span class="rs abnormal">异常</span></div>
        </div>
        <div class="modal-ft">
          <button @click="docMdl = false">取消</button>
          <button class="pri" @click="saveDoc" :disabled="saving">{{ saving ? '保存中…' : '保存报告' }}</button>
        </div>
      </div>
    </div>

    <!-- 查看报告 -->
    <div class="modal-mask" :class="{ show: viewMdl }">
      <div class="modal wide panel" :class="{ full: maxMdl }">
        <div class="mbar">
          <h3>查看报告</h3>
          <div class="mtools">
            <button v-if="!maxMdl" class="mt-btn" title="放大" @click="maxMdl = true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5"/><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M16 21h5v-5"/></svg></button>
            <button v-else class="mt-btn" title="还原" @click="maxMdl = false"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h5V3"/><path d="M21 8h-5V3"/><path d="M3 16h5v5"/><path d="M21 16h-5v5"/></svg></button>
            <button class="mt-btn" title="关闭" @click="viewMdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">{{ viewRow?.parent?.category || '' }}{{ viewRow?.parent?.addr ? ' · ' + viewRow.parent.addr : '' }}{{ viewRow?.parent?.checked_at ? ' · ' + viewRow.parent.checked_at.replace('T', ' ').slice(0, 16) : '' }}</div>
        <div class="mbody">
        <div class="view-tabs">
          <button :class="['vtab', { on: viewMain === 'items' }]" @click="viewMain = 'items'">检验结果</button>
          <button :class="['vtab', { on: viewMain === 'meds' }]" @click="viewMain = 'meds'">用药记录</button>
          <button :class="['vtab', { on: viewMain === 'files' }]" @click="viewMain = 'files'">关联文件</button>
        </div>
        <div class="view-cols" v-show="viewMain === 'items'"><div class="view-left">
        <div class="fgrid rp-fg">
          <div class="field"><div class="flabel">报告名称</div><span class="flc">：</span><div class="kv">{{ viewRow?.name || '—' }}</div></div>
          <div class="field"><div class="flabel">录入时间</div><span class="flc">：</span><div class="kv">{{ viewRow?.created_at ? viewRow.created_at.replace('T', ' ').slice(0, 16) : '—' }}</div></div>
          <div class="field"><div class="flabel">负责人</div><span class="flc">：</span><div class="kv">{{ viewRow?.parent?.doctor || '—' }}</div></div>
          <div class="field"><div class="flabel">检验项数</div><span class="flc">：</span><div class="kv">{{ (viewRow?.items_detail || []).length }} 项</div></div>
          <div class="field full"><div class="flabel">报告备注</div><span class="flc">：</span><div class="kv">{{ viewRow?.note || '—' }}</div></div>
        </div>
        <div v-if="viewRow?.image" style="margin:2px 0 12px;display:flex;align-items:center;gap:12px">
          <b style="font-size:13px">附件图片</b>
          <img :src="'/static/' + viewRow.image" class="view-img" @click="viewImg(viewRow)" loading="lazy">
        </div>
        <div v-if="viewRow?.attachments?.length" style="margin:0 0 12px">
          <b style="font-size:13px">附件</b>
          <div class="att-list" style="margin-top:6px">
            <div class="att-item" v-for="(a, i) in viewRow.attachments" :key="i">
              <a class="att-name" :href="'/static/' + a.path" target="_blank" rel="noopener" title="打开附件">{{ a.name }}</a>
              <span class="t-mut" style="font-size:11px">{{ fmtSize(a.size) }}</span>
            </div>
          </div>
        </div>
        <div style="margin:8px 0 10px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <b style="font-size:13px">检验结果</b>
          <div class="tabs">
            <button :class="{ on: viewTab === 'all' }" @click="viewTab = 'all'">所有项（{{ (viewRow?.items_detail || []).length }}）</button>
            <button :class="{ on: viewTab === 'abn' }" @click="viewTab = 'abn'">异常项（{{ viewAbnItems.length }}）</button>
          </div>
          <label class="grp-switch" :class="{ on: groupMode }" title="勾选后，本报告内关注的检查项会在首页合并到一张曲线图对照显示">
            <input type="checkbox" v-model="groupMode"><i></i><span>组合到本报告一张图</span>
          </label>
        </div>
        <div class="tbl-wrap">
          <table class="med-tbl">
            <thead><tr>
              <th style="width:30px">#</th><th>检验项名称</th><th>单位</th><th>实测值</th><th>参考范围</th><th>判定</th><th style="width:140px">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="(it, i) in (viewTab === 'abn' ? viewAbnItems : (viewRow?.items_detail || []))" :key="i">
                <td class="t-mut">{{ i + 1 }}</td>
                <td>{{ it.name || '—' }}</td>
                <td>{{ it.unit || '—' }}</td>
                <td><b :class="'rs ' + (it.result || '')">{{ it.value || '—' }}{{ it.result === 'high' ? ' ↑' : (it.result === 'low' ? ' ↓' : '') }}</b></td>
                <td>{{ it.ref_range || '—' }}</td>
                <td><span :class="'rs ' + (it.result || '')">{{ statusText(it.result) || '—' }}</span></td>
                <td><div class="ops">
                  <button class="mini" @click="openTrend(it.name)" title="查看历史趋势曲线">趋势</button>
                  <button class="mini star" :class="{ on: groupMode ? interestedIn(it.name, viewRow?.id || 0) : interested(it.name) }"
                    @click="toggleInterest(it.name)"
                    :title="groupMode ? (interestedIn(it.name, viewRow?.id || 0) ? '取消本报告组合关注' : '组合到本报告一张图（首页对照显示）') : (interested(it.name) ? '取消关注（首页展示）' : '关注该检查项（首页展示）')">
                    {{ groupMode ? (interestedIn(it.name, viewRow?.id || 0) ? '★已入组' : '☆加入组合') : (interested(it.name) ? '★已关注' : '☆关注') }}
                  </button>
                </div></td>
              </tr>
              <tr v-if="!(viewRow?.items_detail || []).length"><td colspan="7" class="t-mut" style="text-align:center;padding:20px">本报告暂无检验结果</td></tr>
              <tr v-else-if="viewTab === 'abn' && !viewAbnItems.length"><td colspan="7" class="t-mut" style="text-align:center;padding:20px">🎉 没有异常项，检验结果全部在参考范围内</td></tr>
            </tbody>
          </table>
        </div>
        <!-- AI 分析历史区 -->
        <div style="margin-top:16px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
            <b style="font-size:13px">AI 分析历史（{{ aiHist.filter((a) => a.doc_id === viewRow?.id).length }}）</b>
            <button class="sm ai" @click="openAiMdl({ kind: 'doc', record: viewRow?.parent, doc: viewRow })">＋ 开始分析</button>
          </div>
          <div v-if="!(aiHist.filter((a) => a.doc_id === viewRow?.id)).length" class="t-mut" style="font-size:12.5px;padding:8px 0">暂无分析记录，点「开始分析」让 AI 解读这份报告</div>
          <div v-for="a in aiHist.filter((x) => x.doc_id === viewRow?.id)" :key="a.id" style="border:1px solid var(--bd);border-radius:8px;padding:8px 12px;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
              <span class="t-mut" style="font-size:12px">{{ a.created_at ? a.created_at.replace('T', ' ').slice(0, 16) : '—' }}</span>
              <span class="badge info">{{ a.model || '—' }}</span>
              <span class="t-mut" style="font-size:12px;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ a.question || '' }}</span>
              <button class="mini" @click="aiExpanded[a.id] = !aiExpanded[a.id]">{{ aiExpanded[a.id] ? '收起' : '展开' }}</button>
              <button class="mini dan" @click="delAnalysis(a)" v-if="canWrite">删除</button>
            </div>
            <div v-if="aiExpanded[a.id]" class="ai-md" style="margin-top:6px;color:var(--tx);background:var(--bg2,#f7f8fa);border-radius:6px;padding:8px 10px" v-html="md(a.result)"></div>
          </div>
        </div>
        </div>
        <!-- Tab：用药记录 -->
        <div class="view-meds" v-show="viewMain === 'meds'">
          <div v-if="viewMedsLoading" class="t-mut" style="font-size:12.5px;padding:10px 0">加载中…</div>
          <template v-else-if="viewMeds.length">
            <div class="vs-head"><b>关联用药记录</b><span class="badge info">{{ viewMeds.length }} 条开方</span></div>
            <div class="rx-card" v-for="rx in viewMeds" :key="rx.id">
              <div class="rx-title">{{ rx.org_dept || '未知机构 / 科室' }}</div>
              <div class="fgrid rx-fg">
                <div class="field"><div class="flabel">患者</div><div class="kv">{{ rx.patient || '—' }}</div></div>
                <div class="field"><div class="flabel">医师</div><div class="kv">{{ rx.doctor || '—' }}</div></div>
                <div class="field"><div class="flabel">开方时间</div><div class="kv">{{ fmtDt(rx.prescribed_at) }}</div></div>
                <div class="field"><div class="flabel">药品</div><div class="kv">{{ (rx.items || []).length }} 种</div></div>
              </div>
              <div class="tbl-wrap rx-tbl">
                <table class="med-tbl">
                  <thead><tr>
                    <th>药品名称</th><th>规格</th><th>频次</th><th>用法</th><th style="width:58px">状态</th>
                  </tr></thead>
                  <tbody>
                    <tr v-for="(it, i) in (rx.items || [])" :key="i">
                      <td>{{ it.name || '—' }}</td>
                      <td>{{ it.spec || '—' }}</td>
                      <td>{{ it.frequency || '—' }}</td>
                      <td>{{ it.usage || '—' }}</td>
                      <td><span :class="'badge ' + (it.status === '进行中' ? 'normal' : (it.status === '已停药' ? 'warn' : 'info'))" style="font-size:10.5px;font-weight:600">{{ it.status || '—' }}</span></td>
                    </tr>
                    <tr v-if="!(rx.items || []).length"><td colspan="5" class="t-mut" style="text-align:center;padding:14px">无药品明细</td></tr>
                  </tbody>
                </table>
              </div>
              <div v-if="rx.note" class="rx-note">{{ rx.note }}</div>
            </div>
          </template>
          <div v-else class="t-mut" style="font-size:12.5px;padding:14px 0">该检查记录暂无绑定的用药记录</div>
        </div>
        <!-- Tab：关联文件（占位，功能未实施） -->
        <div class="view-files" v-show="viewMain === 'files'">
          <div class="vs-head"><b>关联文件</b></div>
          <div class="t-mut" style="font-size:12.5px;padding:16px 0;border:1px dashed var(--line);border-radius:10px;text-align:center">
            🔗 关联文件功能即将上线，敬请期待
          </div>
        </div>
        </div>
        </div>
        <div class="modal-ft">
          <button class="pri" @click="viewMdl = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 检查项趋势弹窗 -->
    <div class="modal-mask" :class="{ show: trendMdl }">
      <div class="modal wide panel">
        <div class="mbar">
          <h3>检查项趋势 · {{ trendName }}</h3>
          <div class="mtools">
            <button class="mt-btn" title="关闭" @click="trendMdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">该检查项在你可见范围内的历史结果走势（曲线图）</div>
        <div class="mbody">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
            <span class="flabel" style="margin:0">时间区间</span>
            <div class="tabs">
              <button :class="{ on: trendScope === 'year' }" @click="setScope('year')">今年</button>
              <button :class="{ on: trendScope === 'quarter' }" @click="setScope('quarter')">季度</button>
              <button :class="{ on: trendScope === 'recent3' }" @click="setScope('recent3')">最近三次</button>
            </div>
            <span class="t-mut" style="font-size:12px">{{ trendLoading ? '加载中…' : (trendData?.points?.length || 0) + ' 个数据点' + (trendData?.unit ? ' · 单位 ' + trendData.unit : '') }}</span>
          </div>

          <div v-if="trendData && trendData.points?.length" style="border:1px solid var(--line);border-radius:8px;padding:10px 14px 22px">
            <TrendChart :points="trendData.points" :unit="trendData.unit" />
          </div>
          <div v-else class="t-mut" style="text-align:center;padding:36px 0">{{ trendLoading ? '加载中…' : '该区间内暂无「' + trendName + '」的历史数据' }}</div>

          <table v-if="trendData?.points?.length" class="med-tbl" style="margin-top:16px">
            <thead><tr>
              <th>检查日期</th><th>结果值</th><th>单位</th><th>参考范围</th><th>判定</th>
            </tr></thead>
            <tbody>
              <tr v-for="(p, i) in trendData.points" :key="i">
                <td class="t-num">{{ p.checked_at || '—' }}</td>
                <td><b :class="'rs ' + (p.result || '')">{{ p.value ?? '—' }}{{ p.result === 'high' ? ' ↑' : (p.result === 'low' ? ' ↓' : '') }}</b></td>
                <td>{{ p.unit || '—' }}</td>
                <td>{{ p.ref_range || '—' }}</td>
                <td><span :class="'rs ' + (p.result || '')">{{ statusText(p.result) || '—' }}</span></td>
              </tr>
            </tbody>
          </table>
          <div style="margin-top:12px">
            <button class="mini star" :class="{ on: interested(trendName) }" @click="toggleInterest(trendName)">
              {{ interested(trendName) ? '★ 已关注（首页展示中）' : '☆ 关注该检查项（首页展示波动）' }}
            </button>
          </div>
        </div>
        <div class="modal-ft">
          <button @click="trendMdl = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- AI 分析弹窗 -->
    <div class="modal-mask" :class="{ show: aiMdl }">
      <div class="modal wide panel" :class="{ full: maxMdl }">
        <div class="mbar">
          <h3>{{ aiScopeTitle }}</h3>
          <div class="mtools">
            <button class="mt-btn" title="关闭" @click="aiMdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">选择 AI 供应商与模型，对报告数据做专业解读；分析结果会保留在本页面</div>
        <div class="mbody">
          <div class="fgrid">
            <div class="field">
              <div class="flabel">AI 供应商（别名）</div>
              <SearchSelect v-model="aiAlias" @change="pickAlias"
                :options="aiGroups.map((g) => ({ value: g.alias, label: g.alias + '（' + g.items.length + ' 模型）' }))"
                placeholder="选择供应商" />
            </div>
            <div class="field">
              <div class="flabel">模型</div>
              <SearchSelect v-model="aiModel"
                :options="(aiGroups.find((g) => g.alias === aiAlias)?.items || []).map((m) => ({ value: m.name, label: m.name }))"
                placeholder="选择模型" />
            </div>
            <div class="field span2">
              <div class="flabel">补充问题（可选）</div>
              <input type="text" v-model="aiQ" placeholder="如：重点看有哪些异常、需要注意什么">
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:10px;margin:10px 0 12px">
            <button class="pri" @click="runAnalyze" :disabled="aiBusy || !aiAlias || !aiModel">{{ aiBusy ? '分析中…（模型生成中）' : '开始分析' }}</button>
            <span v-if="!aiGroups.length" class="t-mut" style="font-size:12px">尚未配置 AI 供应商，请先到「AI 配置」页添加</span>
          </div>
          <div v-if="aiBusy" style="display:flex;align-items:center;gap:8px;color:var(--mut);font-size:12.5px;margin-bottom:8px">
            <span class="spin"></span>
            <span v-if="aiRetry">{{ aiRetry }}</span>
            <span v-else>正在生成分析，结果会实时显示在下方…</span>
          </div>
          <div v-if="aiRetry && aiResult" style="margin-bottom:8px;font-size:12px;color:var(--mut)">{{ aiRetry }}</div>
          <div v-if="aiResult" class="ai-md" style="border:1px solid var(--bd);border-radius:8px;padding:10px 12px;margin-bottom:14px;background:var(--bg2,#f7f8fa)" v-html="md(aiResult)"></div>

          <div style="display:flex;align-items:center;gap:10px;margin:10px 0 8px">
            <b style="font-size:13px">历史分析（{{ aiHist.length }}）</b>
          </div>
          <div v-if="!aiHist.length" class="t-mut" style="font-size:12.5px;padding:6px 0">暂无历史，分析结果会保存在这里，可随时回看/删除</div>
          <div v-for="a in aiHist" :key="a.id" style="border:1px solid var(--bd);border-radius:8px;padding:8px 12px;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
              <span class="t-mut" style="font-size:12px">{{ a.created_at ? a.created_at.replace('T', ' ').slice(0, 16) : '—' }}</span>
              <span class="badge info">{{ a.model || '—' }}</span>
              <span v-if="a.doc_id" class="badge">单份报告</span>
              <span v-else class="badge">整条记录</span>
              <span class="t-mut" style="font-size:12px;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ a.question || '' }}</span>
              <button class="mini" @click="aiExpanded[a.id] = !aiExpanded[a.id]">{{ aiExpanded[a.id] ? '收起' : '展开' }}</button>
              <button class="mini dan" @click="delAnalysis(a)" v-if="canWrite">删除</button>
            </div>
            <div v-if="aiExpanded[a.id]" class="ai-md" style="margin-top:6px;background:var(--bg2,#f7f8fa);border-radius:6px;padding:8px 10px" v-html="md(a.result)"></div>
          </div>
        </div>
        <div class="modal-ft">
          <button class="pri" @click="aiMdl = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 附件大图查看 -->
    <div class="modal-mask" :class="{ show: imgMdl }" @click.self="imgMdl = false">
      <div class="img-viewer">
        <PinchZoom v-if="imgMdl" :src="imgUrl" @close="imgMdl = false" />
        <button class="img-close" @click="imgMdl = false"><span style="font-size:15px">✕</span></button>
      </div>
    </div>

    <!-- 移动端：左区域操作菜单 -->
    <div class="rp-sheet-mask" v-if="sheetRow" @click.self="closeSheet">
      <div class="rp-sheet">
        <div class="rp-sheet-title">检查记录操作</div>
        <button @click="openDocMdl(sheetRow); closeSheet()" v-if="canWrite">＋ 新增报告</button>
        <button @click="openMdl(sheetRow); closeSheet()" v-if="canWrite">编辑</button>
        <button @click="openAiMdl({ kind: 'record', record: sheetRow }); closeSheet()">AI 分析</button>
        <button class="rp-sheet-del" @click="del(sheetRow); closeSheet()" v-if="canWrite">删除</button>
        <button class="rp-sheet-cancel" @click="closeSheet()">取消</button>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>

<style scoped>
/* ── 附件清单（编辑弹窗 / 查看弹窗共用）── */
.att-list{display:flex;flex-direction:column;gap:6px;margin-top:8px}
.att-item{display:flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:8px;padding:6px 8px;background:var(--card2)}
.att-name{flex:1;min-width:0;font-size:12px;color:var(--acc);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none}
/* 筛选区：上=时间区间，下=类型(小)+搜索框右对齐内容 */
.rp-filters { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px }
.rf-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap }
.rf-dates input[type="date"] { width: 136px; flex: 1 1 120px }
.rf-dates .flabel { flex: none }
.rf-to { color: var(--mut); font-size: 12.5px; flex: none }
.rf-actions .cat-sel { flex: none; width: 96px }
.rf-actions .rf-search { flex: 1; min-width: 0 }
/* ── 移动端：检查记录卡片（左信息 + 右报告轮播）── 默认隐藏，PC 表格不变 ── */
.rp-cards { display: none; }
@media (max-width: 560px) {
  .rp-cards { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding-bottom: 8px; }
  .rp-cards + .tbl-wrap { display: none; }
  .rp-card {
    display: flex; gap: 10px;
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 12px;
  }
  /* 左区域：检查时间 / 地址 / 负责人 / 备注 */
  .rp-left {
    flex: 0 0 96px; min-width: 0;
    display: flex; flex-direction: column; gap: 8px;
    border-right: 1px dashed var(--line); padding-right: 10px;
  }
  .rp-left .rp-row { display: flex; flex-direction: column; gap: 2px; text-align: left; }
  .rp-left .rp-row b { font-size: 11px; color: var(--mut); font-weight: 500; text-align: left; display: block; width: 100%; }
  .rp-left .rp-row span { font-size: 12px; color: var(--fg); line-height: 1.45; word-break: break-all; text-align: left; display: block; width: 100%; }
  .rp-left .rp-tip {
    margin-top: 2px; font-size: 10.5px; color: var(--acc);
    background: var(--card2); border: 1px dashed var(--line); border-radius: 6px;
    text-align: left; padding: 3px 6px; display: block;
  }
  /* ── 左区域操作菜单（底部滑出）── */
  .rp-sheet-mask {
    position: fixed; inset: 0; z-index: 900;
    background: rgba(8, 12, 20, .45);
    display: flex; align-items: flex-end; justify-content: center;
  }
  .rp-sheet {
    width: 100%; max-width: 560px;
    background: var(--card); border-radius: 16px 16px 0 0;
    padding: 12px 14px calc(14px + env(safe-area-inset-bottom));
    display: flex; flex-direction: column; gap: 8px;
    box-shadow: 0 -8px 30px rgba(8, 12, 20, .22);
    animation: rp-sheet-up .18s ease-out;
  }
  @keyframes rp-sheet-up {
    from { transform: translateY(30px); opacity: .4; }
    to { transform: translateY(0); opacity: 1; }
  }
  .rp-sheet-title { font-size: 13px; font-weight: 600; color: var(--mut); text-align: center; margin-bottom: 2px; }
  .rp-sheet button {
    border: 0; border-radius: 10px; padding: 12px 0; font-size: 14px;
    font-family: inherit; cursor: pointer; background: var(--card2); color: var(--fg);
  }
  .rp-sheet button:active { opacity: .72; }
  .rp-sheet .rp-sheet-del { color: var(--err); }
  .rp-sheet .rp-sheet-cancel { background: transparent; color: var(--mut); }
  /* 右区域：报告轮播 */
  .rp-swipe { flex: 1; min-width: 0; position: relative; }
  .rp-slides {
    display: flex; overflow-x: auto; white-space: nowrap;
    scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch;
    scrollbar-width: none; border-radius: 8px;
  }
  .rp-slides::-webkit-scrollbar { display: none; }
  .rp-slide {
    flex: 0 0 100%; scroll-snap-align: start;
    display: flex; flex-direction: column; min-width: 0;
  }
  .rp-imgbox {
    height: 108px; border-radius: 8px; overflow: hidden;
    background: var(--card2); border: 1px solid var(--line);
    display: flex; align-items: center; justify-content: center;
  }
  .rp-imgbox img { width: 100%; height: 100%; object-fit: cover; display: block; cursor: pointer; }
  .rp-noimg {
    font-size: 12px; color: var(--mut); padding: 8px 0;
  }
  .rp-name {
    margin-top: 7px; font-weight: 600; font-size: 13.5px; line-height: 1.4; color: var(--fg);
    overflow-wrap: anywhere; padding-right: 2px;
  }
  .rp-meta {
    margin-top: 4px; font-size: 11.5px; color: var(--mut);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .rp-bar { margin: 0 5px; color: var(--line); }
  .rp-ops {
    display: flex; justify-content: flex-end; align-items: center; gap: 6px;
    margin-top: 8px; padding-top: 8px; flex-wrap: wrap;
    border-top: 1px dashed var(--line);
  }
  .rp-ops .mini { font-size: 11.5px; }
  .rp-dots {
    display: flex; justify-content: center; gap: 5px; margin-top: 8px;
  }
  .rp-dots i {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--line); cursor: pointer; transition: all .2s;
  }
  .rp-dots i.on { width: 16px; border-radius: 3px; background: var(--acc); }
  .rp-empty {
    height: 130px; border: 1px dashed var(--line); border-radius: 8px;
    display: flex; flex-direction: column; gap: 8px; align-items: center; justify-content: center;
    font-size: 12.5px; color: var(--mut);
  }
}
</style>
