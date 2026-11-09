<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { aiApi } from '../api'
import { hasPerm } from '../utils/perm'

const canWrite = hasPerm('op.ai.write')
const rows = ref([])
const total = ref(0)
const query = ref('')
const showMdl = ref(false)
const saving = ref(false)
const toastMsg = ref('')
const selected = ref([])
const filterVendor = ref('')
const showKey = ref(false)

// 常见服务商预设（选中自动带出接入地址）
const VENDORS = [
  { value: 'OpenAI', label: 'OpenAI', addr: 'https://api.openai.com/v1' },
  { value: 'DeepSeek', label: 'DeepSeek 深度求索', addr: 'https://api.deepseek.com/v1' },
  { value: '通义千问', label: '通义千问（阿里云百炼）', addr: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { value: 'Kimi', label: 'Kimi（月之暗面）', addr: 'https://api.moonshot.cn/v1' },
  { value: '智谱 GLM', label: '智谱 GLM', addr: 'https://open.bigmodel.cn/api/paas/v4' },
  { value: '硅基流动', label: '硅基流动 SiliconFlow', addr: 'https://api.siliconflow.cn/v1' },
  { value: 'Ollama', label: 'Ollama（本地）', addr: 'http://localhost:11434/v1' },
  { value: '其他', label: '其他（自定义）', addr: '' },
]
const vendorOpts = VENDORS.map((v) => ({ value: v.value, label: v.label }))
const filterVendorOpts = [
  { value: '', label: '全部服务商' },
  ...VENDORS.filter((v) => v.value !== '其他').map((v) => ({ value: v.value, label: v.label })),
]

function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

// 创建时间显示：2026年10月26日 01:04（与表格同源字符串，不做时区转换）
function fmtCt(s) {
  if (!s) return '—'
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T?(\d{2}):(\d{2})/)
  if (!m) return s.replace('T', ' ').slice(0, 16)
  return m[1] + '年' + +m[2] + '月' + +m[3] + '日 ' + m[4] + ':' + m[5]
}

function maskKey(k) {
  if (!k) return '—'
  const s = String(k)
  if (s.length <= 8) return '****' + s.slice(-4)
  return s.slice(0, 3) + '…' + s.slice(-4)
}

// 分组标识：优先别名；历史数据（无别名）回退 服务商+地址+KEY
function groupKey(r) { return r.alias || [r.vendor || '', r.addr || '', r.api_key || ''].join('|') }

const groups = computed(() => {
  const map = new Map()
  for (const r of rows.value) {
    const k = groupKey(r)
    if (!map.has(k)) map.set(k, [])
    map.get(k).push(r)
  }
  return [...map.entries()].map(([k, items]) => {
    items.sort((a, b) => (a.id - b.id))
    const first = items[0]
    return {
      key: k,
      firstId: first.id,
      alias: first.alias || '',
      vendor: first.vendor || '',
      addr: first.addr || '',
      api_key: first.api_key || '',
      items,
      enabledCount: items.filter((m) => m.enabled).length,
      created_at: items[items.length - 1].created_at,
    }
  })
})

const filteredGroups = computed(() => {
  if (!filterVendor.value) return groups.value
  return groups.value.filter((g) => g.vendor === filterVendor.value)
})

const allChecked = computed(() => filteredGroups.value.length > 0 && selected.value.length === filteredGroups.value.length)

function toggleSel(g) {
  const i = selected.value.indexOf(g.firstId)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(g.firstId)
}

function toggleAll() {
  if (allChecked.value) selected.value = []
  else selected.value = filteredGroups.value.map((g) => g.firstId)
}

const form = ref({ alias: '', vendor: '', addr: '', api_key: '', enabled: true })
const editId = ref(0)

watch(() => form.value.vendor, (v) => {
  const p = VENDORS.find((x) => x.value === v)
  if (p && p.addr && !form.value.addr.trim()) form.value.addr = p.addr
})

async function load() {
  try { rows.value = await aiApi.list({ q: query.value, limit: 100 }) } catch (e) { rows.value = [] }
}

function openMdl() {
  editId.value = 0
  form.value = { alias: '', vendor: '', addr: '', api_key: '', enabled: true }
  showMdl.value = true
}

function openEdit(g) {
  editId.value = g.firstId
  form.value = { alias: g.alias, vendor: g.vendor, addr: g.addr, api_key: g.api_key, enabled: true }
  showMdl.value = true
}

function existingNames(alias) {
  const g = groups.value.find((x) => x.alias === alias)
  return new Set((g ? g.items : []).map((m) => m.name))
}

async function createModels(names, alias, vendor, addr, apiKey, done) {
  if (!alias) { toast('请先填写别名'); saving.value = false; return }
  let created = 0
  const exist = existingNames(alias)
  const pending = new Set()
  for (const n of names) {
    if (!n || pending.has(n) || exist.has(n)) continue
    pending.add(n)
    await aiApi.create({ alias, name: n, vendor, addr, api_key: apiKey, enabled: true })
    created++
  }
  if (!created) { toast('没有新增（模型已存在或未勾选）'); saving.value = false; return }
  toast('已保存 ' + created + ' 个模型')
  if (done) done()
  await load()
}

// ---- 获取模型（新增 / 查看共用）----
const fetchMdl = ref(false)
const fetchBusy = ref(false)
const fetched = ref([])
const fetchSel = ref([])
const fetchSource = ref('add')
const fetchAllChecked = computed(() => fetched.value.length > 0 && fetchSel.value.length === fetched.value.length)

async function doFetch() {
  if (!form.value.alias.trim()) { toast('请先填写别名'); return }
  if (!form.value.addr.trim()) { toast('请先填写接入地址'); return }
  fetchSource.value = 'add'
  fetchBusy.value = true
  try {
    const r = await aiApi.fetchModels({ addr: form.value.addr.trim(), api_key: (form.value.api_key || '').trim() })
    fetched.value = (r.models || []).map((m) => ({ id: String(m) }))
    fetchSel.value = []
    fetchMdl.value = true
  } catch (e) { toast('获取失败：' + (e.response?.data?.detail || e.message)) } finally { fetchBusy.value = false }
}

function toggleFetchAll() {
  if (fetchAllChecked.value) fetchSel.value = []
  else fetchSel.value = fetched.value.map((m) => m.id)
}

async function createFromFetch() {
  const names = fetched.value.filter((m) => fetchSel.value.includes(m.id)).map((m) => m.id)
  if (!names.length) { toast('请先勾选要创建的模型'); return }
  saving.value = true
  try {
    if (fetchSource.value === 'detail') {
      const g = detailGroup.value
      await createModels(names, g.alias, g.vendor, g.addr, g.api_key, () => { fetchMdl.value = false; refreshDetail() })
    } else {
      await createModels(names, form.value.alias.trim(), form.value.vendor, form.value.addr.trim(), (form.value.api_key || '').trim(), () => { fetchMdl.value = false; showMdl.value = false })
    }
  } catch (e) { toast('创建失败：' + (e.response?.data?.detail || e.message)) } finally { saving.value = false }
}

async function save() {
  if (!form.value.alias.trim()) { toast('请填写别名'); return }
  if (!form.value.addr.trim()) { toast('请填写接入地址'); return }
  // 编辑：更新该别名下全部模型
  if (editId.value) {
    const g = groups.value.find((x) => x.firstId === editId.value)
    if (!g) { toast('供应商不存在'); return }
    const other = groups.value.find((x) => x.alias === form.value.alias.trim() && x.firstId !== editId.value)
    if (other) { toast('该别名已存在，请换一个'); return }
    saving.value = true
    try {
      for (const m of g.items) {
        await aiApi.update(m.id, {
          alias: form.value.alias.trim(), name: m.name,
          vendor: form.value.vendor, addr: form.value.addr.trim(),
          api_key: (form.value.api_key || '').trim(), enabled: m.enabled,
        })
      }
      toast('供应商已更新')
      showMdl.value = false
      await load()
    } catch (e) { toast('保存失败：' + (e.response?.data?.detail || e.message)) } finally { saving.value = false }
    return
  }
  // 新增：需先获取模型
  if (fetchMdl.value && fetchSel.value.length) { await createFromFetch(); return }
  toast('请先点「获取模型」拉取并勾选要添加的模型')
}

// ---- 查看：别名下所有模型 ----
const detailMdl = ref(false)
const detailGroup = ref(null)
const addName = ref('')
const detailBusy = ref(false)

function openDetail(g) {
  detailGroup.value = g
  addName.value = ''
  detailMdl.value = true
}

function refreshDetail() {
  const g = detailGroup.value
  if (!g) return
  const ng = groups.value.find((x) => x.key === g.key)
  if (ng) detailGroup.value = ng
}

async function addModelToGroup() {
  const name = addName.value.trim()
  if (!name) { toast('请输入模型名称'); return }
  const g = detailGroup.value
  if (g.items.some((m) => m.name === name)) { toast('该模型已存在'); return }
  detailBusy.value = true
  try {
    await aiApi.create({ alias: g.alias, name, vendor: g.vendor, addr: g.addr, api_key: g.api_key, enabled: true })
    addName.value = ''
    toast('模型已添加')
    await load(); refreshDetail()
  } catch (e) { toast('添加失败：' + (e.response?.data?.detail || e.message)) } finally { detailBusy.value = false }
}

async function fetchInDetail() {
  const g = detailGroup.value
  if (!g.addr.trim()) { toast('该供应商未配置接入地址'); return }
  fetchSource.value = 'detail'
  fetchBusy.value = true
  try {
    const r = await aiApi.fetchModels({ addr: g.addr.trim(), api_key: (g.api_key || '').trim() })
    fetched.value = (r.models || []).map((m) => ({ id: String(m) }))
    fetchSel.value = []
    fetchMdl.value = true
  } catch (e) { toast('获取失败：' + (e.response?.data?.detail || e.message)) } finally { fetchBusy.value = false }
}

async function toggleModel(m) {
  const g = detailGroup.value
  try {
    await aiApi.update(m.id, { alias: g.alias, name: m.name, vendor: g.vendor, addr: g.addr, api_key: g.api_key, enabled: !m.enabled })
    m.enabled = !m.enabled
    toast(m.enabled ? '模型已启用' : '模型已停用')
    refreshDetail()
  } catch (e) { toast('操作失败') }
}

async function delModel(m) {
  try { await aiApi.remove(m.id); toast('模型已删除'); await load(); refreshDetail() } catch (e) { toast('删除失败') }
}

async function delGroup(g) {
  if (!confirm('删除「' + (g.alias || '未命名') + '」下的 ' + g.items.length + ' 个模型？')) return
  try {
    await aiApi.batchRemove(g.items.map((m) => m.id))
    toast('供应商已删除')
    if (detailGroup.value && detailGroup.value.key === g.key) detailMdl.value = false
    await load()
  } catch (e) { toast('删除失败') }
}

async function batchDel() {
  if (!selected.value.length) { toast('请先勾选要删除的数据'); return }
  const ids = []
  for (const g of groups.value) {
    if (selected.value.includes(g.firstId)) ids.push(...g.items.map((m) => m.id))
  }
  try {
    await aiApi.batchRemove(ids)
    toast('已删除 ' + selected.value.length + ' 个供应商')
    selected.value = []
    await load()
  } catch (e) { toast('批量删除失败：' + (e.response?.data?.detail || e.message)) }
}

onMounted(async () => {
  await load()
  try { const c = await aiApi.count(); total.value = c.total || 0 } catch (e) {}
})
</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div class="left">
        <button class="pri" @click="openMdl" v-if="canWrite">＋ 新增供应商</button>
        <button class="sm dan" @click="batchDel" v-if="canWrite">批量删除</button>
      </div>
      <div class="right">
        <SearchSelect v-model="filterVendor" class="vendor-sel" style="width:110px" :options="filterVendorOpts" placeholder="全部服务商" />
        <div class="searchbox"><input type="search" v-model="query" placeholder="搜索别名 / 模型名称 / 服务商" @keyup.enter="load"><svg class="lm" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4-4" stroke="currentColor" stroke-width="2"/></svg></div>
      </div>
    </div>

    <!-- 移动端：供应商卡片列表（左图标 + 右别名/创建时间/模型数/按钮） -->
    <div class="aic-cards">
      <div class="aic-card" v-for="g in filteredGroups" :key="g.key">
        <label class="chk" @click.stop><input type="checkbox" :checked="selected.includes(g.firstId)" @change="toggleSel(g)"><i></i></label>
        <div class="aic-ico">
          <svg viewBox="0 0 24 24" fill="none"><rect x="6" y="6" width="12" height="12" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="10" cy="10" r="1.2" fill="currentColor"/><circle cx="14" cy="14" r="1.2" fill="currentColor"/></svg>
        </div>
        <div class="aic-body">
          <div class="aic-name">{{ g.alias || '未命名' }}</div>
          <div class="aic-meta">{{ fmtCt(g.created_at) }}<span class="aic-bar">|</span>{{ g.items.length }} 个模型</div>
          <div class="aic-ops">
            <button class="mini pri" @click="openDetail(g)">查看</button>
            <button class="mini" @click="openEdit(g)" v-if="canWrite">编辑</button>
            <button class="mini dan" @click="delGroup(g)" v-if="canWrite">删除</button>
          </div>
        </div>
      </div>
      <div v-if="!filteredGroups.length" class="t-mut" style="text-align:center;padding:28px">暂无供应商配置，点「＋ 新增供应商」创建</div>
    </div>

    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:36px"><label class="chk"><input type="checkbox" :checked="allChecked" @change="toggleAll"><i></i></label></th>
          <th>别名</th><th>服务商</th><th>接入地址</th><th>API KEY</th><th>模型数</th><th>状态</th><th>创建时间</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="g in filteredGroups" :key="g.key">
            <td><label class="chk"><input type="checkbox" :checked="selected.includes(g.firstId)" @change="toggleSel(g)"><i></i></label></td>
            <td><b>{{ g.alias || '未命名' }}</b></td>
            <td>{{ g.vendor || '—' }}</td>
            <td><code style="font-size:11.5px">{{ g.addr || '—' }}</code></td>
            <td><code>{{ maskKey(g.api_key) }}</code></td>
            <td><button class="mini badge normal" @click="openDetail(g)">{{ g.items.length }} 个模型 ›</button></td>
            <td>
              <span v-if="g.enabledCount === g.items.length" class="mini badge normal">全部启用</span>
              <span v-else-if="g.enabledCount === 0" class="mini badge warn">全部停用</span>
              <span v-else class="mini badge">{{ g.enabledCount }}/{{ g.items.length }} 启用</span>
            </td>
            <td class="t-num">{{ g.created_at ? g.created_at.replace('T', ' ').slice(0, 16) : '—' }}</td>
            <td><div class="ops">
              <button class="mini pri" @click="openDetail(g)">查看</button>
              <button class="mini" @click="openEdit(g)" v-if="canWrite">编辑</button>
              <button class="mini dan" @click="delGroup(g)" v-if="canWrite">删除</button>
            </div></td>
          </tr>
          <tr v-if="!filteredGroups.length"><td colspan="9" class="t-mut" style="text-align:center;padding:28px">暂无供应商配置，点「＋ 新增供应商」创建</td></tr>
        </tbody>
      </table>
    </div>
    <div class="pager">
      <div class="pg-left"><span class="pg-info">共 <b>{{ total }}</b> 个模型 / <b>{{ groups.length }}</b> 个供应商</span></div>
    </div>

    <!-- 新增供应商弹窗 -->
    <div class="modal-mask" :class="{ show: showMdl }">
      <div class="modal">
        <h3>{{ editId ? '编辑 AI 供应商' : '新增 AI 供应商' }}</h3>
        <div class="msub">{{ editId ? '修改后该别名下的所有模型配置将同步更新' : '填好别名和接入信息后点「获取模型」，模型自动拉取，无需手写模型名称' }}</div>
        <div class="fgrid ai-fg">
          <div class="field"><div class="flabel">别名 <span style="color:var(--err)">*</span></div><span class="flc">：</span><input type="text" v-model="form.alias" placeholder="例如 公司 DeepSeek 主账号"></div>
          <div class="field"><div class="flabel">服务商</div><span class="flc">：</span>
            <SearchSelect v-model="form.vendor" :options="vendorOpts" placeholder="选择服务商（可选其他自定义）" />
          </div>
          <div class="field full"><div class="flabel">接入地址</div><span class="flc">：</span><input type="text" v-model="form.addr" placeholder="https://api.example.com/v1"></div>
          <div class="field full"><div class="flabel">API KEY</div><span class="flc">：</span>
            <div style="display:flex;gap:8px">
              <input :type="showKey ? 'text' : 'password'" v-model="form.api_key" placeholder="sk-..." style="flex:1">
              <button class="sm" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button>
            </div>
          </div>
          <div class="field full ai-fetch-field" style="margin-top:2px">
            <button class="sm ai-fetch-btn" @click="doFetch" :disabled="fetchBusy || saving">{{ fetchBusy ? '获取中…' : '↻ 获取模型（自动拉取该接入地址下可用模型）' }}</button>
            <span class="t-mut ai-fetch-hint">勾选后保存，别名下即可拥有这些模型</span>
          </div>
        </div>
        <div class="modal-ft">
          <button @click="showMdl = false">取消</button>
          <button class="pri" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存供应商' }}</button>
        </div>
      </div>
    </div>

    <!-- 获取模型结果（新增/查看共用） -->
    <div class="modal-mask" :class="{ show: fetchMdl }">
      <div class="modal">
        <h3>选择要添加的模型</h3>
        <div class="msub">已拉取到 {{ fetched.length }} 个可用模型，勾选后添加（已存在的自动跳过）</div>
        <div style="display:flex;align-items:center;gap:10px;margin:6px 0">
          <label style="font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer">
            <input type="checkbox" :checked="fetchAllChecked" @change="toggleFetchAll"> 全选
          </label>
        </div>
        <div style="max-height:300px;overflow:auto;border:1px solid var(--line);border-radius:8px">
          <label v-for="m in fetched" :key="m.id" style="display:flex;align-items:center;gap:8px;padding:7px 10px;cursor:pointer;border-bottom:1px solid var(--line)">
            <input type="checkbox" :value="m.id" v-model="fetchSel">
            <code style="font-size:12px">{{ m.id }}</code>
          </label>
          <div v-if="!fetched.length" class="t-mut" style="text-align:center;padding:18px">未获取到模型</div>
        </div>
        <div class="modal-ft">
          <button @click="fetchMdl = false">取消</button>
          <button class="pri" @click="createFromFetch" :disabled="saving" v-if="canWrite">添加所选 ({{ fetchSel.length }})</button>
        </div>
      </div>
    </div>

    <!-- 查看别名下模型弹窗 -->
    <div class="modal-mask" :class="{ show: detailMdl }">
      <div class="modal">
        <template v-if="detailGroup">
          <h3>{{ detailGroup.alias || '未命名' }} · 模型列表</h3>
          <div class="msub" style="display:flex;flex-wrap:wrap;gap:6px 14px">
            <span>服务商：<b>{{ detailGroup.vendor || '—' }}</b></span>
            <span><code style="font-size:11.5px">{{ detailGroup.addr || '未配置地址' }}</code></span>
            <span>API KEY：<code>{{ maskKey(detailGroup.api_key) }}</code></span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin:10px 0;flex-wrap:wrap">
            <input v-model="addName" type="text" placeholder="输入模型名称添加" style="flex:1;min-width:180px" @keyup.enter="addModelToGroup">
            <button class="sm pri" @click="addModelToGroup" :disabled="detailBusy" v-if="canWrite">＋ 添加模型</button>
            <button class="sm" @click="fetchInDetail" :disabled="fetchBusy">↻ 从服务商获取</button>
          </div>
          <div style="max-height:320px;overflow:auto;border:1px solid var(--line);border-radius:8px">
            <table style="width:100%">
              <thead><tr>
                <th>模型名称</th><th style="width:90px">状态</th><th style="width:120px">创建时间</th><th style="width:80px">操作</th>
              </tr></thead>
              <tbody>
                <tr v-for="m in detailGroup.items" :key="m.id">
                  <td><code style="font-size:12px">{{ m.name }}</code></td>
                  <td><button class="mini badge" :class="m.enabled ? 'normal' : 'warn'" @click="toggleModel(m)" v-if="canWrite">{{ m.enabled ? '启用' : '停用' }}</button></td>
                  <td class="t-num" style="font-size:11.5px">{{ m.created_at ? m.created_at.replace('T', ' ').slice(0, 16) : '—' }}</td>
                  <td><button class="mini dan" @click="delModel(m)" v-if="canWrite">删除</button></td>
                </tr>
                <tr v-if="!detailGroup.items.length"><td colspan="4" class="t-mut" style="text-align:center;padding:18px">该别名下暂无模型，点「从服务商获取」拉取</td></tr>
              </tbody>
            </table>
          </div>
        </template>
        <div class="modal-ft">
          <button @click="detailMdl = false">关闭</button>
        </div>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>

<style scoped>
/* ── 移动端 AI 供应商卡片列表（默认隐藏，PC 表格不变）── */
.aic-cards { display: none; }
@media (max-width: 560px) {
  .aic-cards { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; padding-bottom: 8px; }
  .aic-cards + .tbl-wrap { display: none; }
  .aic-card {
    position: relative;
    display: flex; gap: 12px; align-items: flex-start;
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 12px 14px;
  }
  .aic-card .chk { position: absolute; top: 12px; right: 12px; }
  .aic-ico {
    flex: 0 0 44px; width: 44px; height: 44px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    background: var(--card2); border: 1px solid var(--line); color: var(--acc);
  }
  .aic-ico svg { width: 24px; height: 24px; }
  .aic-body { flex: 1; min-width: 0; padding-right: 30px; }
  .aic-name {
    font-weight: 600; font-size: 15px; line-height: 1.45; color: var(--fg);
    overflow-wrap: anywhere; padding-right: 4px;
  }
  .aic-meta {
    font-size: 12px; color: var(--mut); margin-top: 6px; line-height: 1.5;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .aic-meta .aic-bar { margin: 0 6px; color: var(--line); }
  .aic-ops {
    display: flex; justify-content: flex-end; align-items: center; gap: 8px;
    margin-top: 10px; padding-top: 10px;
    border-top: 1px dashed var(--line);
  }
}
</style>
