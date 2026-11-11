<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { medApi, reportApi } from '../api'
import { hasPerm } from '../utils/perm'
import MobilePager from '../components/MobilePager.vue'
import { watchBack } from '../utils/backstack'

const canWrite = hasPerm('op.med.write')
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
// 开方弹窗全屏（放大 / 还原）
const maxMdlDoc = ref(false)

// 新增 / 编辑 / 查看
const editingId = ref(null)
const viewMdl = ref(false)
const viewRow = ref(null)
// 关联检查记录（下拉选项）
const reports = ref([])
const filterStatus = ref('')
const linkedReport = computed(() => reports.value.find((r) => r.id === form.value.report_id) || null)
const linkOptions = computed(() => [
  { value: null, label: '— 不关联 —' },
  ...reports.value.map((rp) => ({
    value: rp.id,
    label: `${rp.category || '体检'} · ${rp.addr || '—'} · ${rp.checked_at ? rp.checked_at.slice(0, 10) : '—'}`,
  })),
])
const statusOptions = [
  { value: '进行中', label: '进行中' },
  { value: '已结束', label: '已结束' },
  { value: '已停药', label: '已停药' },
]

function toast(m) {
  toastMsg.value = m
  setTimeout(() => (toastMsg.value = ''), 1800)
}

function fmtDt(s) {
  return s ? String(s).replace('T', ' ').slice(0, 16) : '—'
}

// 表单（新增 / 编辑共用）
const form = ref({
  patient: '',
  org_dept: '',
  doctor: '',
  prescribed_at: '',
  start_date: '',
  end_date: '',
  report_id: null,
  note: '',
  items: [],
})

// 当前时间（datetime-local 值），开方时间默认显示当前时间、可手动改
function nowLocal() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

const mdlTitle = computed(() => (editingId.value ? '编辑开方' : '新增开方'))

function newItem() {
  return { name: '', spec: '', frequency: '', usage: '', start_date: '', end_date: '', status: '进行中' }
}

function blankForm() {
  return {
    patient: '', org_dept: '', doctor: '', prescribed_at: nowLocal(), start_date: '', end_date: '',
    report_id: null, note: '',
    items: [newItem(), newItem()],
  }
}

async function load() {
  try {
    const data = await medApi.list({ q: query.value, status: filterStatus.value, limit: 100 })
    rows.value = data
  } catch (e) {
    rows.value = []
  }
}

async function loadReports() {
  try {
    const data = await reportApi.list({ limit: 500 })
    reports.value = data || []
    // 新增模式且未手动选择时，默认选最新一条检查记录（列表按 id 倒序，第一条即最新）
    if (!editingId.value && !form.value.report_id && reports.value.length) {
      form.value.report_id = reports.value[0].id
    }
  } catch (e) {
    reports.value = []
  }
}

function openMdl() {
  editingId.value = null
  form.value = blankForm()
  showMdl.value = true
  loadReports()
}

// 复用上一次用药：把最近一次开方的患者/机构/医师/药品明细拉过来修改
async function reuseLast() {
  try {
    const data = await medApi.list({ limit: 1 })
    const last = data && data[0]
    if (!last) { toast('暂无上一次用药记录'); return }
    form.value = {
      patient: last.patient || '',
      org_dept: last.org_dept || '',
      doctor: last.doctor || '',
      prescribed_at: nowLocal(),    // 新开方默认当前时间，可手动改
      start_date: last.start_date || '',
      end_date: last.end_date || '',
      report_id: reports.value.length ? reports.value[0].id : null,  // 默认最新一条检查记录
      note: '',
      items: (last.items || []).map((it) => ({
        name: it.name || '', spec: it.spec || '', frequency: it.frequency || '', usage: it.usage || '',
        start_date: '', end_date: '', status: '进行中',
      })),
    }
    if (!form.value.items.length) form.value.items = [newItem()]
    toast(`已载入上次用药（${form.value.items.length} 种），可直接修改后保存`)
  } catch (e) {
    toast('拉取上次用药失败：' + (e.response?.data?.detail || e.message))
  }
}

async function openEdit(r) {
  try {
    const full = await medApi.get(r.id)
    editingId.value = r.id
    form.value = {
      patient: full.patient || '',
      org_dept: full.org_dept || '',
      doctor: full.doctor || '',
      prescribed_at: full.prescribed_at ? full.prescribed_at.slice(0, 16) : '',
      start_date: full.start_date || '',
      end_date: full.end_date || '',
      report_id: full.report_id ?? null,
      note: full.note || '',
      items: (full.items || []).map((it) => ({
        name: it.name || '', spec: it.spec || '', frequency: it.frequency || '', usage: it.usage || '',
        start_date: '', end_date: '', status: '进行中',
      })),
    }
    if (!form.value.items.length) form.value.items = [newItem()]
    showMdl.value = true
    loadReports()
  } catch (e) {
    toast('加载开方失败：' + (e.response?.data?.detail || e.message))
  }
}

function openView(r) {
  viewRow.value = r
  viewMdl.value = true
}

function addRow() { form.value.items.push(newItem()) }
function delRow(i) { form.value.items.splice(i, 1) }

async function save() {
  if (!form.value.patient || !form.value.items.length) { toast('请填写患者与至少一种药品'); return }
  saving.value = true
  const payload = { ...form.value, report_id: form.value.report_id || null }
  try {
    if (editingId.value) {
      await medApi.update(editingId.value, payload)
      toast('开方已更新')
    } else {
      await medApi.create(payload)
      toast('开方已保存，含多种药品')
    }
    showMdl.value = false
    await load()
  } catch (e) {
    toast('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function del(id) {
  try {
    await medApi.remove(id)
    toast('开方已删除')
    await load()
  } catch (e) { toast('删除失败') }
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
    await medApi.batchRemove(selected.value)
    toast('已删除 ' + selected.value.length + ' 个开方')
    selected.value = []
    await load()
  } catch (e) { toast('批量删除失败：' + (e.response?.data?.detail || e.message)) }
}

// 状态徽标 class
function badgeClass(st) {
  if (st === '已结束') return 'info'
  if (st === '已停药') return 'warn'
  return 'normal'
}

onMounted(async () => {
  await load()
  try { const c = await medApi.count(); total.value = c.total || 0 } catch (e) {}
})
// 系统返回键逐级返回：弹层进入返回栈
watchBack(() => viewMdl.value, () => { viewMdl.value = false })
watchBack(() => showMdl.value, () => { showMdl.value = false })
</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div class="left">
        <button class="pri" @click="openMdl" v-if="canWrite">＋ 新增开方</button>
        <button class="sm dan" @click="batchDel" v-if="canWrite">批量删除</button>

      </div>
      <div class="right">
        <SearchSelect v-model="filterStatus" class="stat-sel" style="width:96px" @change="load" :options="[{ value: '', label: '全部状态' }, ...statusOptions]" placeholder="全部状态" />
        <div class="searchbox"><input type="search" v-model="query" placeholder="搜索患者 / 医师 / 药品" @keyup.enter="load"><svg class="lm" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4-4" stroke="currentColor" stroke-width="2"/></svg></div>
      </div>
    </div>

    <!-- 移动端：用药记录卡片（左信息 + 右药品明细） -->
    <div class="md-cards">
      <div class="md-card" v-for="r in pagedRows" :key="'c' + r.id">
        <div class="md-main">
          <div class="md-left">
            <div class="md-row"><b>开方时间</b><span>{{ r.prescribed_at ? fmtDt(r.prescribed_at) : '—' }}</span></div>
            <div class="md-row"><b>患者</b><span>{{ r.patient }}</span></div>
            <div class="md-row"><b>药品种类</b><span style="color:var(--acc)">{{ r.items.length }} 种</span></div>
            <div class="md-row"><b>备注</b><span>{{ r.note || '—' }}</span></div>
          </div>
          <div class="md-right">
            <div class="md-item" v-for="(it, i) in r.items" :key="i">
              <div class="md-name">{{ it.name || '未命名药品' }}<span class="md-spec">{{ it.spec || '' }}</span></div>
              <div class="md-meta">频次 <span>{{ it.frequency || '—' }}</span> · 用法 <span>{{ it.usage || '—' }}</span></div>
            </div>
            <div v-if="!r.items.length" class="md-empty">无药品明细</div>
          </div>
        </div>
        <div class="md-ops">
          <button class="mini pri" @click="openView(r)">查看</button>
          <button class="mini" @click="openEdit(r)" v-if="canWrite">编辑</button>
          <button class="mini dan" @click="del(r.id)" v-if="canWrite">删除</button>
        </div>
      </div>
      <div v-if="!rows.length" class="t-mut" style="text-align:center;padding:28px">暂无开方记录，点「＋ 新增开方」创建</div>
    </div>

    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:36px"><label class="chk"><input type="checkbox" :checked="allChecked" @change="toggleAll"><i></i></label></th>
          <th>开方时间</th><th>患者</th><th>开方机构 / 科室</th><th>开方医师</th><th>关联检查时间</th><th>药品种类</th><th>备注</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in pagedRows" :key="r.id">
            <td><label class="chk"><input type="checkbox" :checked="selected.includes(r.id)" @change="toggleSel(r.id)"><i></i></label></td>
            <td class="t-num">{{ r.prescribed_at ? r.prescribed_at.replace('T', ' ').slice(0, 16) : '—' }}</td>
            <td><b>{{ r.patient }}</b></td>
            <td>{{ r.org_dept || '—' }}</td>
            <td>{{ r.doctor || '—' }}</td>
            <td class="t-num">{{ r.check_time ? r.check_time.replace('T', ' ').slice(0, 16) : '—' }}</td>
            <td><span class="t-num" style="color:var(--acc)">{{ r.items.length }} 种</span></td>
            <td class="t-mut" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.note || '—' }}</td>
            <td><div class="ops">
              <button class="mini" @click="openView(r)">查看</button>
              <button class="mini" @click="openEdit(r)" v-if="canWrite">编辑</button>
              <button class="mini dan" @click="del(r.id)" v-if="canWrite">删除</button>
            </div></td>
          </tr>
          <tr v-if="!rows.length"><td colspan="9" class="t-mut" style="text-align:center;padding:28px">暂无开方记录，点「＋ 新增开方」创建</td></tr>
        </tbody>
      </table>
    </div>

    <MobilePager :total="total" v-model:visible="visibleCount" unit="条" />
    <div class="pager">
      <div class="pg-left"><span class="pg-info">共 <b>{{ total }}</b> 条</span>
        <SearchSelect style="width:106px" :searchable="false" placeholder="20 条/页" :options="[{ value: 20, label: '20 条/页' }, { value: 50, label: '50 条/页' }, { value: 100, label: '100 条/页' }]" />
        <span class="pg-info">第 <b>1</b>/<b>1</b> 页</span></div>
      <div class="pg-right">
        <button class="pg-btn" disabled>首页</button><button class="pg-btn" disabled>‹ 上一页</button>
        <button class="pg-btn cur">1</button>
        <button class="pg-btn" disabled>下一页 ›</button><button class="pg-btn" disabled>末页</button>
      </div>
    </div>

    <!-- 查看开方弹窗 -->
    <div class="modal-mask" :class="{ show: viewMdl }">
      <div class="modal wide panel">
        <div class="mbar">
          <h3>查看开方</h3>
          <div class="mtools">
            <button class="mt-btn" title="关闭" @click="viewMdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">开方详情 · 关联检查记录：{{ viewRow?.check_time ? fmtDt(viewRow.check_time) : '未关联' }}</div>
        <div class="mbody">
          <div class="fgrid">
            <div class="field full"><div class="flabel">患者</div><div class="kv">{{ viewRow?.patient || '—' }}</div></div>
            <div class="field"><div class="flabel">开方机构 / 科室</div><div class="kv">{{ viewRow?.org_dept || '—' }}</div></div>
            <div class="field"><div class="flabel">开方医师</div><div class="kv">{{ viewRow?.doctor || '—' }}</div></div>
            <div class="field"><div class="flabel">开方时间</div><div class="kv">{{ fmtDt(viewRow?.prescribed_at) }}</div></div>
            <div class="field"><div class="flabel">关联检查时间</div><div class="kv">{{ fmtDt(viewRow?.check_time) }}</div></div>
            <div class="field"><div class="flabel">用药开始时间</div><div class="kv">{{ viewRow?.start_date || '—' }}</div></div>
            <div class="field"><div class="flabel">用药结束时间</div><div class="kv">{{ viewRow?.end_date || '—' }}</div></div>
            <div class="field full"><div class="flabel">开方备注</div><div class="kv">{{ viewRow?.note || '—' }}</div></div>
          </div>
          <div style="margin:8px 0 8px"><b style="font-size:13px">药品明细（{{ (viewRow?.items || []).length }} 种）</b></div>
          <div class="tbl-wrap">
            <table class="med-tbl">
              <thead><tr>
                <th style="width:30px">#</th><th>药品名称</th><th>规格 / 剂量</th><th>用药频次</th>
                <th>用法</th>
              </tr></thead>
              <tbody>
                <tr v-for="(it, i) in (viewRow?.items || [])" :key="i">
                  <td class="t-mut">{{ i + 1 }}</td>
                  <td>{{ it.name || '—' }}</td>
                  <td>{{ it.spec || '—' }}</td>
                  <td>{{ it.frequency || '—' }}</td>
                  <td>{{ it.usage || '—' }}</td>
                </tr>
                <tr v-if="!(viewRow?.items || []).length"><td colspan="5" class="t-mut" style="text-align:center;padding:20px">无药品明细</td></tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="modal-ft">
          <button class="pri" @click="viewMdl = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 新增 / 编辑开方弹窗：一次开方多药 -->
    <div class="modal-mask" :class="{ show: showMdl }">
      <div class="modal wide panel" :class="{ full: maxMdlDoc }">
        <div class="mbar">
          <h3>{{ mdlTitle }}</h3>
          <div class="mtools">
            <button v-if="!maxMdlDoc" class="mt-btn" title="放大" @click="maxMdlDoc = true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5"/><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M16 21h5v-5"/></svg></button>
            <button v-else class="mt-btn" title="还原" @click="maxMdlDoc = false"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h5V3"/><path d="M21 8h-5V3"/><path d="M3 16h5v5"/><path d="M21 16h-5v5"/></svg></button>
            <button class="mt-btn" title="关闭" @click="showMdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">一次开方（处方）可包含多种药品，分别填写明细</div>
        <div class="mbody">
          <div class="fgrid">
            <div class="field full"><div class="flabel">患者 <span style="color:var(--err)">*</span></div><input type="text" v-model="form.patient" placeholder="患者姓名"></div>
            <div class="field"><div class="flabel">开方机构 / 科室</div><input type="text" v-model="form.org_dept" placeholder="例如 内分泌科 · 门诊"></div>
            <div class="field"><div class="flabel">开方医师</div><input type="text" v-model="form.doctor" placeholder="医师姓名"></div>
            <div class="field"><div class="flabel">开方时间</div><input type="datetime-local" v-model="form.prescribed_at"></div>
            <div class="field"><div class="flabel">用药开始时间</div><input type="date" v-model="form.start_date"></div>
            <div class="field"><div class="flabel">用药结束时间</div><input type="date" v-model="form.end_date"></div>
            <div class="field"><div class="flabel">关联检查记录 <span class="t-mut" style="font-weight:400">非必填</span></div>
              <SearchSelect v-model="form.report_id" :options="linkOptions" placeholder="— 不关联 —" />
            </div>
            <div class="field span2" v-if="linkedReport"><div class="flabel">带出的检查时间</div><div class="kv">{{ fmtDt(linkedReport.checked_at) }}</div></div>
            <div class="field full"><div class="flabel">开方备注</div><input type="text" v-model="form.note" placeholder="备注（可选），如 饭后服用 / 复诊带药"></div>
          </div>

          <div style="display:flex;align-items:center;justify-content:space-between;margin:8px 0 8px;flex-wrap:wrap;gap:8px">
            <b style="font-size:13px">药品明细 <span class="t-mut" style="font-weight:400;font-size:12px">可添加多种药品</span></b>
            <div style="display:flex;gap:8px">
              <button v-if="!editingId" class="sm" title="把最近一次开方的患者与药品明细拉过来修改" @click="reuseLast">↩ 复用上次用药</button>
              <button class="sm" @click="addRow">＋ 添加药品</button>
            </div>
          </div>
          <div class="tbl-wrap">
            <table class="med-tbl">
              <thead><tr>
                <th style="width:30px">#</th><th>药品名称</th><th>规格 / 剂量</th><th>用药频次</th>
                <th>用法</th><th style="width:40px"> </th>
              </tr></thead>
              <tbody>
                <tr v-for="(it, i) in form.items" :key="i">
                  <td class="t-mut">{{ i + 1 }}</td>
                  <td><input v-model="it.name" placeholder="药品名称"></td>
                  <td><input v-model="it.spec" placeholder="规格/剂量"></td>
                  <td><input v-model="it.frequency" placeholder="用药频次"></td>
                  <td><input v-model="it.usage" placeholder="用法"></td>
                  <td><button class="mini dan" @click="delRow(i)">删</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="t-mut" style="font-size:11.5px;margin-top:6px">共 {{ form.items.length }} 种药品</div>
        </div>
        <div class="modal-ft">
          <button @click="showMdl = false">取消</button>
          <button class="pri" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存开方' }}</button>
        </div>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>

<style scoped>
/* ── 移动端：用药记录卡片（左信息 + 右药品明细）── 默认隐藏，PC 表格不变 ── */
.md-cards { display: none; }
@media (max-width: 560px) {
  .md-cards { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding-bottom: 8px; }
  .md-cards + .tbl-wrap { display: none; }
  .md-card {
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 12px;
  }
  .md-main { display: flex; gap: 10px; align-items: stretch; }
  /* 左区域：开方时间 / 患者 / 药品种类 / 备注 */
  .md-left {
    flex: 0 0 96px; min-width: 0;
    display: flex; flex-direction: column; gap: 8px;
    border-right: 1px dashed var(--line); padding-right: 10px;
  }
  .md-left .md-row { display: flex; flex-direction: column; gap: 2px; }
  .md-left .md-row b { font-size: 11px; color: var(--mut); font-weight: 500; }
  .md-left .md-row span { font-size: 12px; color: var(--fg); line-height: 1.45; word-break: break-all; }
  /* 右区域：药品明细（名称/规格/频次/用法）——高度随内容/左区增高，不遮挡 */
  .md-right { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .md-item {
    padding: 7px 8px; border: 1px solid var(--line); border-radius: 8px;
    background: var(--card2);
  }
  .md-item + .md-item { margin-top: 6px; }
  .md-name {
    font-weight: 600; font-size: 13px; color: var(--fg); line-height: 1.4;
    overflow-wrap: anywhere; display: flex; flex-wrap: wrap; gap: 4px 8px;
  }
  .md-spec { font-weight: 400; font-size: 11.5px; color: var(--mut); }
  .md-meta { margin-top: 3px; font-size: 11.5px; color: var(--mut); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .md-meta span { color: var(--fg); }
  .md-empty {
    border: 1px dashed var(--line); border-radius: 8px; padding: 22px 0;
    text-align: center; font-size: 12.5px; color: var(--mut);
  }
  /* 底部操作行 */
  .md-ops {
    display: flex; justify-content: flex-end; align-items: center; gap: 8px;
    margin-top: 10px; padding-top: 10px;
    border-top: 1px dashed var(--line);
  }
}
</style>