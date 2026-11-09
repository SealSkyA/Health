<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { tplApi, reportApi } from '../api'
import { hasPerm } from '../utils/perm'
import { fileToDataUrl } from '../utils/file'
import MobilePager from '../components/MobilePager.vue'

const canWrite = hasPerm('op.tpl.write')
const rows = ref([])
const total = ref(0)
// 移动端分页：默认显示 10 条，“加载更多”每次 +10
const visibleCount = ref(10)
const pagedRows = computed(() => rows.value.slice(0, visibleCount.value))
watch(() => rows.value.length, () => { visibleCount.value = 10 })
const query = ref('')
const showMdl = ref(false)
const saving = ref(false)
const editId = ref(0)
const viewMdl = ref(false)
const viewRow = ref(null)
const toastMsg = ref('')
const selected = ref([])

function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

const form = ref({ name: '', items: [], creator: '', note: '' })

function newItem() {
  return { name: '', ref_range: '', unit: '' }
}

function addRow() { form.value.items.push(newItem()) }
function delRow(i) { form.value.items.splice(i, 1) }

// ---- OCR 识别（新增/编辑模板时识别检验单图片）----
const ocrBusy = ref(false)
const ocrLines = ref([])
const ocrFileInput = ref(null)

async function onOcrFile(ev) {
  const f = ev.target.files && ev.target.files[0]
  ev.target.value = ''
  if (!f) return
  ocrBusy.value = true
  ocrLines.value = []
  try {
    const dataUrl = await fileToDataUrl(f)
    const r = await reportApi.ocrJson({ image: dataUrl, filename: f.name })
    const lines = (r.lines || []).map((s) => String(s).trim()).filter(Boolean)
    if (!lines.length) { toast('未识别到文字，可换更清晰的图片重试'); return }
    ocrLines.value = buildTable(r)
  } catch (e) {
    toast('识别失败：' + (e.response?.data?.detail || e.message))
  } finally {
    ocrBusy.value = false
  }
}

// 按坐标把 OCR 散行重组回表格（与检查报告同一算法）
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
  const sorted = [...items].sort((a, b) => a.cy - b.cy)
  const rows = []
  for (const it of sorted) {
    const last = rows[rows.length - 1]
    if (last && Math.abs(it.cy - last[last.length - 1].cy) < 45) last.push(it)
    else rows.push([it])
  }
  const kw = ['检验项目', '参考范围', '结果', '单位']
  let hdr = null
  for (const g of rows) {
    const n = g.filter((x) => kw.some((w) => x.text.includes(w))).length
    if (n >= 2) { hdr = g; break }
  }
  if (!hdr) {
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

// 勾选行填入模板明细（模板不需要结果值，只取名称/单位/参考范围）
function applyOcrLines() {
  const picked = ocrLines.value.filter((l) => l.checked && (l.name && l.name.trim() || l.value && l.value.trim()))
  if (!picked.length) { toast('请先勾选识别出的行'); return }
  let added = 0
  for (const it of picked) {
    const name = (it.name || '').trim()
    if (!name) continue
    const unit = (it.unit || '').trim()
    const ref = (it.ref || '').trim()
    const dup = form.value.items.find((x) => x.name === name)
    if (dup) { dup.unit = unit || dup.unit; dup.ref_range = ref || dup.ref_range; added++ }
    else { form.value.items.push({ name, ref_range: ref, unit }); added++ }
  }
  if (!added) { toast('没有可填入的内容，请检查勾选'); return }
  toast('已填入 ' + added + ' 项，请核对参考范围/单位')
  ocrLines.value = []
}

// 参考范围展示：优先 ref_range，旧数字数据拼 ref_min ~ ref_max
function rangeOf(it) {
  if (it.ref_range) return it.ref_range
  const parts = [it.ref_min, it.ref_max].filter(Boolean)
  return parts.length ? parts.join('~') : ''
}

// 创建时间显示：2026年10月10日 10:10（与表格同源字符串，不做时区转换）
function fmtMeta(s) {
  if (!s) return '—'
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T?(\d{2}):(\d{2})/)
  if (!m) return s.replace('T', ' ').slice(0, 16)
  return m[1] + '年' + +m[2] + '月' + +m[3] + '日 ' + m[4] + ':' + m[5]
}

async function load() {
  try { rows.value = await tplApi.list({ q: query.value }) } catch (e) { rows.value = [] }
}

function openMdl() {
  editId.value = 0
  form.value = { name: '', items: [newItem(), newItem()], creator: '', note: '' }
  showMdl.value = true
}

function openEdit(r) {
  editId.value = r.id
  const arr = r.items_detail && r.items_detail.length ? r.items_detail : [newItem()]
  form.value = {
    name: r.name,
    items: arr.map((it) => ({
      name: it.name || '',
      ref_range: rangeOf(it),
      unit: it.unit || '',
    })),
    creator: r.creator || '',
    note: r.note || '',
  }
  showMdl.value = true
}

function openView(r) { viewRow.value = r; viewMdl.value = true }

async function save() {
  if (!form.value.name) { toast('请填写模板名称'); return }
  const items = form.value.items.filter((it) => it.name && it.name.trim())
  if (!items.length) { toast('请至少添加一条检验项目'); return }
  form.value.items = items
  saving.value = true
  try {
    if (editId.value) await tplApi.update(editId.value, form.value)
    else await tplApi.create(form.value)
    toast(editId.value ? '模板已更新' : '模板已保存')
    showMdl.value = false
    await load()
  } catch (e) { toast('保存失败：' + (e.response?.data?.detail || e.message)) } finally { saving.value = false }
}

async function del(id) {
  try { await tplApi.remove(id); toast('模板已删除'); await load() } catch (e) { toast('删除失败') }
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
    await tplApi.batchRemove(selected.value)
    toast('已删除 ' + selected.value.length + ' 条模板')
    selected.value = []
    await load()
  } catch (e) { toast('批量删除失败：' + (e.response?.data?.detail || e.message)) }
}

onMounted(async () => {
  await load()
  try { const c = await tplApi.count(); total.value = c.total || 0 } catch (e) {}
})
</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div class="left">
        <button class="pri" @click="openMdl" v-if="canWrite">＋ 新增模板</button>
        <button class="sm dan" @click="batchDel" v-if="canWrite">批量删除</button>
      </div>
      <div class="right">
        <div class="searchbox"><input type="search" v-model="query" placeholder="搜索模板名称 / 检验项" @keyup.enter="load"><svg class="lm" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4-4" stroke="currentColor" stroke-width="2"/></svg></div>
      </div>
    </div>

    <!-- 移动端：模板卡片列表（左图标 + 右名称/时间/操作人/按钮） -->
    <div class="tpl-cards">
      <div class="tpl-card" v-for="r in pagedRows" :key="r.id">
        <label class="chk" @click.stop><input type="checkbox" :checked="selected.includes(r.id)" @change="toggleSel(r.id)"><i></i></label>
        <div class="tc-ico">
          <svg viewBox="0 0 24 24" fill="none"><path d="M6 3h9l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v5h5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9 13h6M9 17h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </div>
        <div class="tc-body">
          <div class="tc-name">{{ r.name }}</div>
          <div class="tc-meta">{{ fmtMeta(r.created_at) }}<span class="tc-bar">|</span>{{ r.creator || '—' }}</div>
          <div class="tc-ops">
            <button class="mini" @click="openView(r)">查看</button>
            <button class="mini" @click="openEdit(r)" v-if="canWrite">编辑</button>
            <button class="mini dan" @click="del(r.id)" v-if="canWrite">删除</button>
          </div>
        </div>
      </div>
      <div class="t-mut" style="text-align:center;padding:28px" v-if="!rows.length">暂无模板，点「＋ 新增模板」创建</div>
    </div>

    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:36px"><label class="chk"><input type="checkbox" :checked="allChecked" @change="toggleAll"><i></i></label></th>
          <th>模板名称</th><th>检验项目</th><th>创建时间</th><th>创建人</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in pagedRows" :key="r.id">
            <td><label class="chk"><input type="checkbox" :checked="selected.includes(r.id)" @change="toggleSel(r.id)"><i></i></label></td>
            <td><b>{{ r.name }}</b></td>
            <td><span class="t-mut">{{ r.items || '—' }}</span></td>
            <td class="t-num">{{ r.created_at ? r.created_at.replace('T', ' ').slice(0, 16) : '—' }}</td>
            <td>{{ r.creator || '—' }}</td>
            <td><div class="ops">
              <button class="mini" @click="openView(r)">查看</button>
              <button class="mini" @click="openEdit(r)" v-if="canWrite">编辑</button>
              <button class="mini dan" @click="del(r.id)" v-if="canWrite">删除</button>
            </div></td>
          </tr>
          <tr v-if="!rows.length"><td colspan="6" class="t-mut" style="text-align:center;padding:28px">暂无模板，点「＋ 新增模板」创建</td></tr>
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
      <div class="modal wide">
        <h3>{{ editId ? '编辑报告模板' : '新增报告模板' }}</h3>
        <div class="msub">定义一类检查的报告模板与检验项目（含参考范围参数）</div>
        <div class="fgrid tpl-fg">
          <div class="field full"><div class="flabel">模板名称</div><input type="text" v-model="form.name" placeholder="例如 血常规全套（必填）"></div>
          <div class="field"><div class="flabel">创&#x3000;建人</div><input type="text" v-model="form.creator" placeholder="创建人"></div>
          <div class="field"><div class="flabel">备&#x3000;&#x3000;注</div><input type="text" v-model="form.note" placeholder="备注（可选）"></div>
        </div>

        <div style="display:flex;align-items:center;justify-content:space-between;margin:8px 0 8px;flex-wrap:wrap;gap:8px">
          <b style="font-size:13px">检验项目明细 <span class="t-mut" style="font-weight:400;font-size:12px">每项可填参考范围 / 单位</span></b>
          <div style="display:flex;gap:8px">
            <button class="sm" :disabled="ocrBusy" @click="ocrFileInput && ocrFileInput.click()">{{ ocrBusy ? '识别中…' : '识别检验单图片' }}</button>
            <button class="sm" @click="addRow">＋ 添加检验项</button>
          </div>
        </div>
        <input ref="ocrFileInput" type="file" accept="image/*" style="display:none" @change="onOcrFile">
        <div class="ocrbar" v-if="ocrBusy"><span class="spin"></span> 正在识别检验单图片（约 10 秒，请稍候）…</div>
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
            <div class="ocr-grid ocr-head" style="grid-template-columns:20px 1.4fr .7fr 1.1fr">
              <span></span><span>检验项名称</span><span>单位</span><span>参考范围</span>
            </div>
            <div v-for="(l, i) in ocrLines" :key="i" class="ocr-grid" style="grid-template-columns:20px 1.4fr .7fr 1.1fr">
              <input type="checkbox" v-model="l.checked">
              <input v-model="l.name" class="ocr-txt" placeholder="检验项名称">
              <input v-model="l.unit" class="ocr-txt" placeholder="单位">
              <input v-model="l.ref" class="ocr-txt" placeholder="参考范围">
            </div>
          </div>
        </div>
        <div class="tbl-wrap">
          <table class="med-tbl">
            <thead><tr>
              <th style="width:30px">#</th><th>检验项名称 <span style="color:var(--err)">*</span></th>
              <th>参考范围</th>
              <th style="width:110px">单位</th><th style="width:40px"> </th>
            </tr></thead>
            <tbody>
              <tr v-for="(it, i) in form.items" :key="i">
                <td class="t-mut">{{ i + 1 }}</td>
                <td><input v-model="it.name" placeholder="例如 白细胞计数"></td>
                <td><input v-model="it.ref_range" placeholder="如 3.5~9.5 / 阴性 / A,B,C"></td>
                <td><input v-model="it.unit" placeholder="如 ×10⁹/L"></td>
                <td><button class="mini dan" @click="delRow(i)">删</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="t-mut" style="font-size:11.5px;margin-top:6px">共 {{ form.items.length }} 项检验项目</div>
        <div class="modal-ft">
          <button @click="showMdl = false">取消</button>
          <button class="pri" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存模板' }}</button>
        </div>
      </div>
    </div>

    <!-- 查看模板详情 -->
    <div class="modal-mask" :class="{ show: viewMdl }">
      <div class="modal wide">
        <h3>查看报告模板</h3>
        <div class="msub">{{ viewRow?.name }}</div>
        <div class="fgrid">
          <div class="field"><div class="flabel">模板名称</div><div class="kv">{{ viewRow?.name || '—' }}</div></div>
          <div class="field"><div class="flabel">创建人</div><div class="kv">{{ viewRow?.creator || '—' }}</div></div>
          <div class="field"><div class="flabel">创建时间</div><div class="kv">{{ viewRow?.created_at ? viewRow.created_at.replace('T', ' ').slice(0, 16) : '—' }}</div></div>
          <div class="field full"><div class="flabel">备注</div><div class="kv">{{ viewRow?.note || '—' }}</div></div>
        </div>
          <div style="margin:8px 0 8px"><b style="font-size:13px">检验项目明细（{{ (viewRow?.items_detail || []).length }} 项）</b></div>
        <div class="tbl-wrap">
          <table class="med-tbl">
            <thead><tr>
              <th style="width:30px">#</th><th>检验项名称</th><th>参考范围</th><th>单位</th>
            </tr></thead>
            <tbody>
              <tr v-for="(it, i) in (viewRow?.items_detail || [])" :key="i">
                <td class="t-mut">{{ i + 1 }}</td>
                <td>{{ it.name || '—' }}</td>
                <td>{{ rangeOf(it) || '—' }}</td>
                <td>{{ it.unit || '—' }}</td>
              </tr>
              <tr v-if="!(viewRow?.items_detail || []).length"><td colspan="4" class="t-mut" style="text-align:center;padding:20px">该模板为旧格式文本，无结构化明细</td></tr>
            </tbody>
          </table>
        </div>
        <div class="modal-ft">
          <button class="pri" @click="viewMdl = false">关闭</button>
        </div>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>

<style scoped>
/* ── 移动端报告模板卡片列表（默认隐藏，PC 表格不变）── */
.tpl-cards { display: none; }
@media (max-width: 560px) {
  .tpl-cards { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding-bottom: 8px; }
  .tpl-cards + .tbl-wrap { display: none; }
  .tpl-card {
    position: relative;
    display: flex; gap: 12px; align-items: flex-start;
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 12px 14px;
  }
  .tpl-card .chk { position: absolute; top: 12px; right: 12px; }
  .tc-ico {
    flex: 0 0 44px; width: 44px; height: 44px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    background: var(--card2); border: 1px solid var(--line); color: var(--acc);
  }
  .tc-ico svg { width: 24px; height: 24px; }
  .tc-body { flex: 1; min-width: 0; padding-right: 30px; }
  .tc-name {
    font-weight: 600; font-size: 15px; line-height: 1.45; color: var(--fg);
    overflow-wrap: anywhere; padding-right: 4px;
  }
  .tc-meta {
    font-size: 12px; color: var(--mut); margin-top: 6px; line-height: 1.5;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .tc-meta .tc-bar { margin: 0 6px; color: var(--line); }
  .tc-ops {
    display: flex; justify-content: flex-end; align-items: center; gap: 8px;
    margin-top: 10px; padding-top: 10px;
    border-top: 1px dashed var(--line);
  }
}
</style>
