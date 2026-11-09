<script setup>
// AI 问数悬浮球 —— 参考 MonkeyCode 桌面端交互：
// 右下角 AI 球 → 弹窗（左=会话/项目区，右=会话区）
// 会话区：上=消息流（左缘圆点大纲，悬停显示每次问题，点击跳转）；下=输入框（底部附件/技能/模型选择）
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { aiApi, aiApi2, reportApi } from '../api'
import { fileToDataUrl } from '../utils/file'

const router = useRouter()
const open = ref(false)
const sideOpen = ref(false)   // 移动端：会话列表面板抽屉开关
const toastMsg = ref('')
function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 2200) }
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
const fmt = (ts) => { const d = new Date(ts); return d.toTimeString().slice(0, 5) }

// ---------- 会话（localStorage 持久化，支持分组/重命名/移动） ----------
const STORE = 'ai_ball_sessions'
const LAST_CHAT = 'ai_ball_last_chat'
const ACTIVE = 'ai_ball_active_tasks'   // 进行中后台任务登记簿：{tid, sid, seq, at}
// 兜底：历史数据里 assistant 正文为空但有完整回复 _full 时回填（修复打字机期间未持久化导致正文丢失）；
// 以及清洗 user 消息 seq 冲突（旧版本用 msgs.length 编号，压缩后可能撞车 → 圆点大纲双高亮）。
// 仅递增去重冲突项，已有 seq 保持原值（resumeLiveTasks 依赖登记簿里的 seq 定位消息重建）。
function normalizeMsgs(sessions) {
  for (const s of sessions || []) {
    const used = new Set()
    for (const m of (s.msgs || [])) {
      if (m.role === 'assistant' && !m.content && m._full) m.content = m._full
      if (m.role !== 'user') continue
      let sq = typeof m.seq === 'number' ? m.seq : -1
      while (sq < 0 || used.has(sq)) sq = (sq < 0 ? 0 : sq + 1)
      used.add(sq)
      if (m.seq !== sq) m.seq = sq
    }
  }
  return sessions
}
function loadStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) || 'null')
    if (raw && Array.isArray(raw.sessions)) return {   // 新版 {groups, sessions, _ver}
      _ver: raw._ver || 0,
      _owner: raw._owner ?? null,                      // 归属账号（users.id）：null=未绑定(旧数据/首次)
      groups: raw.groups || [],
      sessions: normalizeMsgs(raw.sessions),
    }
    if (Array.isArray(raw)) return {                   // 旧版迁移
      _ver: 0,
      _owner: null,
      groups: [],
      sessions: normalizeMsgs(raw.map((s) => ({ ...s, groupId: 'default' }))),
    }
  } catch (e) { /* 忽略损坏数据 */ }
  return { _ver: 0, _owner: null, groups: [], sessions: [{ id: uid(), title: '新会话', groupId: 'default', msgs: [], ts: Date.now() }] }
}
const store = ref(loadStore())
const groups = computed(() => [{ id: 'default', name: '默认' }, ...store.value.groups])
// 打开时恢复上次停留的会话（优先）
const savedLast = localStorage.getItem(LAST_CHAT)
const curId = ref(
  store.value.sessions.some((s) => s.id === savedLast)
    ? savedLast
    : (store.value.sessions[0] || {}).id || ''
)
const cur = computed(() => store.value.sessions.find((s) => s.id === curId.value) || store.value.sessions[0])
const msgs = computed(() => cur.value.msgs)
const sysMsgs = computed(() => msgs.value.filter((m) => m.sys))
// 本地 + 云端持久化（版本号判定新旧：本地新→刷新不丢且补推后端；后端新→用后端）
// remoteReady：与后端首次同步（含账号归属对齐）完成前，禁止把本地数据推给当前账号，
// 防止 localStorage 里的其他账号数据在切号瞬间覆盖当前账号后端。
let saveTimer = null
let remoteReady = false
function pushRemote() {
  if (!remoteReady) return Promise.resolve()
  return aiApi2.saveSessions({
    groups: store.value.groups,
    sessions: store.value.sessions,
    ver: store.value._ver || 0,
  }).catch(() => {})
}
function persist() {
  store.value._ver = Date.now()
  try { localStorage.setItem(STORE, JSON.stringify(store.value)) }
  catch (e) {
    // 存储配额超限（历史会话过大）：不可因持久化失败中断流式渲染。
    // 降级为"保留内存态 + 写入骨架"，仍失败则仅服务当前会话。
    try {
      const slim = JSON.parse(JSON.stringify(store.value))
      for (const s of slim.sessions || []) {
        for (const m of s.msgs || []) {
          if (m.role === 'assistant' && (m.content || '').length > 800) m.content = m.content.slice(0, 800)
          delete m._full
        }
      }
      localStorage.setItem(STORE, JSON.stringify(slim))
    } catch (e2) { console.warn('[AI]persist: localStorage quota exceeded, keep in-memory only', e2 && e2.message) }
  }
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(pushRemote, 300)
}
// 立即推一次后端（刷新/关闭页面前调用，避免 300ms 防抖把最新任务消息吞掉）
function flushRemote() {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
  return pushRemote()
}
// ----- 进行中后台任务登记簿（独立于会话数据：即使被后端旧数据覆盖也能恢复） -----
// 登记簿与 ai_ball_sessions 一样按账号隔离（curOwner 由 syncRemote 对齐后赋值），
// 避免 A 账号的进行中任务在 B 账号打开面板时被误当作 B 的任务去重连。
let curOwner = null
function activeKey() { return ACTIVE + '_' + (curOwner ?? 'anon') }
function markActive(tid, sid, seq) {
  const K = activeKey()
  let list = []
  try { list = JSON.parse(localStorage.getItem(K) || '[]') } catch (e) {}
  if (!list.some((x) => x.tid === tid)) {
    list.push({ tid, sid, seq, at: Date.now() })
    localStorage.setItem(K, JSON.stringify(list))
  }
}
function unmarkActive(tid) {
  if (!tid) return
  const K = activeKey()
  try {
    const list = JSON.parse(localStorage.getItem(K) || '[]')
    const next = list.filter((x) => x.tid !== tid)
    localStorage.setItem(K, JSON.stringify(next))
  } catch (e) {}
}
function activeList() {
  try { return JSON.parse(localStorage.getItem(activeKey()) || '[]') } catch (e) { return [] }
}
function persistLocalOnly() {
  localStorage.setItem(STORE, JSON.stringify(store.value))
}
// 打开时与后端比对版本：本地新→保持本地并把本地推回后端；后端新→采用后端。
// 账号归属对齐：本地缓存如果属于其他账号（localStorage 跨账号共享），一律丢弃、以当前账号后端为准，
// 避免把 A 账号的数据推到 B 账号名下，或让 A 的本地覆盖到 B（这是切号后"问题不见"的根因）。
async function syncRemote() {
  try {
    const r = await aiApi2.getSessions()
    if (!r || !Array.isArray(r.sessions)) return
    const me = r.user_id ?? null
    if (me) curOwner = me
    const rVer = r.ver || 0
    const lVer = store.value._ver || 0
    const remoteEmpty = !r.sessions.length && !(r.groups || []).length
    const lOwner = store.value._owner ?? null
    if (lOwner && lOwner !== me) {
      // localStorage 里是另一个账号的数据：丢弃，重置为当前账号视角
      store.value = {
        _ver: rVer, _owner: me,
        groups: r.groups || [], sessions: normalizeMsgs(r.sessions || []),
      }
      persistLocalOnly()
      const last = localStorage.getItem(LAST_CHAT)
      if (!last || !store.value.sessions.some((s) => s.id === last)) {
        curId.value = store.value.sessions[0]?.id || ''
      }
      remoteReady = true
      return
    }
    if (rVer > lVer && !remoteEmpty) {
      // 后端较新（他处产生的消息）：采用后端
      store.value = { _ver: rVer, _owner: me, groups: r.groups || [], sessions: normalizeMsgs(r.sessions || []) }
      persistLocalOnly()
      const last = localStorage.getItem(LAST_CHAT)
      if (!last || !store.value.sessions.some((s) => s.id === last)) {
        curId.value = store.value.sessions[0]?.id || ''
      }
    } else if (lVer > rVer && (store.value.sessions.length || store.value.groups.length)) {
      // 本地较新（刚发送就刷新等）：本地优先，并补推后端
      store.value._owner = me
      persistLocalOnly()
      remoteReady = true
      pushRemote()
    } else if (remoteEmpty && (store.value.sessions.length || store.value.groups.length)) {
      // 后端还是空的（首次进入）：推一份过去
      store.value._owner = me
      persistLocalOnly()
      remoteReady = true
      pushRemote()
    } else {
      // 无冲突：把归属标记落到本地
      if (me && store.value._owner !== me) { store.value._owner = me; persistLocalOnly() }
    }
    remoteReady = true
  } catch (e) { /* 未登录/网络失败：保持本地；不放开远端推送，避免跨账号误推 */ }
}
function resetChat() {
  if (!confirm('清空当前会话的全部消息？')) return
  cur.value.msgs = []
  persist(); scrollBottom()
}
function titleOf(s) {
  const first = s.msgs.find((m) => m.role === 'user')
  if (s.title !== '新会话') return s.title
  if (first) return first.content.replace(/\s+/g, ' ').slice(0, 14) || '（附件消息）'
  return '新会话'
}
function sessionsOf(gid) { return store.value.sessions.filter((s) => s.groupId === gid) }
function countOf(gid) { return store.value.sessions.filter((s) => s.groupId === gid).length }

// 分组折叠状态（默认展开）
const folded = ref({})
function toggleFold(gid) { folded.value = { ...folded.value, [gid]: !folded.value[gid] } }

// 会话/分组操作
function newChatIn(gid) {
  const s = { id: uid(), title: '新会话', groupId: gid || 'default', msgs: [], ts: Date.now() }
  store.value.sessions.unshift(s)
  curId.value = s.id
  sideOpen.value = false
  persist()
}
function newGroup() {
  askName('新分组名称', '', (name) => {
    store.value.groups.push({ id: uid(), name })
    persist()
  })
}
function renameGroup(g) {
  askName('分组名称', g.name, (name) => {
    g.name = name; persist()
  })
}
function renameSession(s) {
  askName('会话名称', s.title, (name) => {
    s.title = name; persist()
  })
  menuFor.value = null
}

// 自定义输入弹窗（取代浏览器 prompt，统一风格）
const dlg = ref(null)      // { title, value, ok }
const dlgInp = ref(null)
function askName(title, initial = '', onOk) {
  dlg.value = { title, value: initial, ok: onOk }
  nextTick(() => dlgInp.value && dlgInp.value.focus())
}
function dlgOk() {
  const v = (dlg.value?.value || '').trim()
  if (!v) return
  const fn = dlg.value.ok
  dlg.value = null
  fn(v)
}
// 自定义确认弹窗（取代浏览器 confirm：删除会话/分组）
const cdlg = ref(null)     // { title, message, okText, onOk }
function askConfirm(title, message, okText, onOk) {
  cdlg.value = { title, message, okText, onOk }
}
function cdlgOk() {
  const fn = cdlg.value.onOk
  cdlg.value = null
  fn()
}
function delGroup(g) {
  askConfirm('删除分组', '删除分组「' + g.name + '」？组内会话将移到「默认」', '删除', () => {
    store.value.sessions.forEach((s) => { if (s.groupId === g.id) s.groupId = 'default' })
    store.value.groups = store.value.groups.filter((x) => x.id !== g.id)
    persist()
  })
}
function moveSession(s, gid) {
  s.groupId = gid; menuFor.value = null; persist()
}
function switchChat(id) { curId.value = id; menuFor.value = null; sideOpen.value = false }
function delChat(id) {
  menuFor.value = null
  askConfirm('删除会话', '确定删除该会话？删除后不可恢复。', '删除', () => {
    store.value.sessions = store.value.sessions.filter((s) => s.id !== id)
    if (curId.value === id) curId.value = store.value.sessions[0]?.id || ''
    persist()
  })
}

// 会话三点菜单：Teleport 到 body 固定定位，杜绝被左栏 overflow 裁剪
const menuFor = ref(null)
const menuPos = ref({ x: 0, y: 0 })
const curSession = computed(() => store.value.sessions.find((s) => s.id === menuFor.value) || null)
const menuStyle = computed(() => ({ left: menuPos.value.x + 'px', top: menuPos.value.y + 'px' }))
function openMenu(s, ev) {
  if (menuFor.value === s.id) { menuFor.value = null; return }
  menuFor.value = s.id
  const r = ev.currentTarget.getBoundingClientRect()
  const mw = 172
  const x = Math.min(r.right + 6, window.innerWidth - mw - 8)
  const y = Math.min(r.top, window.innerHeight - 132)
  menuPos.value = { x, y }
}
function onDocClick() { menuFor.value = null }

// ---------- 模型 / 供应商 / 思考深度 / 技能：记住上次选择（刷新不丢） ----------
const PREFS = 'ai_ball_prefs'
function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS) || '{}') } catch (e) { return {} }
}
const prefs = ref(loadPrefs())
const modelGroups = ref([])
const alias = ref('')
const model = ref('')
async function loadModels() {
  if (modelGroups.value.length) return
  try {
    const list = await aiApi.list({ limit: 100 })
    const map = {}
    for (const m of list) {
      if (!m.enabled) continue
      if (!map[m.alias]) map[m.alias] = { alias: m.alias, items: [] }
      map[m.alias].items.push({ name: m.name })
    }
    modelGroups.value = Object.values(map)
    if (modelGroups.value.length) {
      // 优先恢复上次选择（供应商与模型都还存在才使用，否则回退第一个）
      const p = prefs.value
      const g = modelGroups.value.find((x) => x.alias === p.alias)
      if (g && g.items.some((m) => m.name === p.model)) {
        alias.value = p.alias
        model.value = p.model
      } else {
        alias.value = modelGroups.value[0].alias
        model.value = modelGroups.value[0].items[0].name
      }
    }
  } catch (e) { modelGroups.value = [] }
}
function pickAlias() {
  const g = modelGroups.value.find((x) => x.alias === alias.value)
  model.value = (g && g.items.length) ? g.items[0].name : ''
}
function savePrefs() {
  localStorage.setItem(PREFS, JSON.stringify({
    alias: alias.value, model: model.value,
    think: think.value, skills: enabledSkills.value,
  }))
}

// ---------- 输入 / 附件 / 技能 / 思考深度 ----------
const input = ref('')
const busy = ref(false)   // 请求中或打字中
const typing = ref(false)
const skillOpen = ref(false)
const attachments = ref([])      // { name, ocr, fail, thumb }
const imgInp = ref(null)
// ---- AI 球：任意拖拽定位（localStorage 记忆位置）----
const BALL_KEY = 'ai_ball_pos'
const ballRef = ref(null)
const ballPos = ref(null)    // { x, y } 已自定义位置；null = 维持默认右下角
let ballDrag = null          // 拖动中状态
let suppressClick = false    // 拖动结束时抑制随之而来的那次 click（临时标记）

function loadBallPos() {
  try {
    const s = localStorage.getItem(BALL_KEY)
    if (s) { const o = JSON.parse(s); if (typeof o.x === 'number' && typeof o.y === 'number') ballPos.value = o }
  } catch (e) {}
}
function ballStyle() {
  // 有自定义位置时用 left/top 覆盖默认 right/bottom
  return ballPos.value ? { left: ballPos.value.x + 'px', top: ballPos.value.y + 'px' } : {}
}
function clampBall(p) {
  const S = 8
  return {
    x: Math.min(Math.max(p.x, S), Math.max(S, window.innerWidth - 66)),
    y: Math.min(Math.max(p.y, S), Math.max(S, window.innerHeight - 66)),
  }
}
function ballDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return
  const el = ballRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  ballDrag = { x0: r.left, y0: r.top, px: e.clientX, py: e.clientY, moved: false }
  el.classList.add('drag')
  window.addEventListener('pointermove', ballMove, { passive: false })
  window.addEventListener('pointerup', ballUp)
}
function ballMove(e) {
  if (!ballDrag) return
  const dx = e.clientX - ballDrag.px
  const dy = e.clientY - ballDrag.py
  if (!ballDrag.moved && Math.abs(dx) + Math.abs(dy) < 6) return   // 容差内视为点击
  ballDrag.moved = true
  ballPos.value = clampBall({ x: ballDrag.x0 + dx, y: ballDrag.y0 + dy })
}
function ballUp() {
  if (!ballDrag) return
  const moved = ballDrag.moved
  const el = ballRef.value
  if (el) el.classList.remove('drag')
  if (moved) {
    try { localStorage.setItem(BALL_KEY, JSON.stringify(ballPos.value)) } catch (e) {}
    suppressClick = true   // 拖动后紧接着的 click（由 mouseup 触发）应忽略
    setTimeout(() => { suppressClick = false }, 350)
  }
  ballDrag = null
  window.removeEventListener('pointermove', ballMove, { passive: false })
  window.removeEventListener('pointerup', ballUp)
}
function ballClick() {
  if (suppressClick) { suppressClick = false; return }   // 拖动后的 click 忽略
  open.value = !open.value
}
function clampBallToViewport() {
  if (!ballPos.value) return
  ballPos.value = clampBall(ballPos.value)
}
function onBallResize() { clearTimeout(ballRzT); ballRzT = setTimeout(clampBallToViewport, 150) }
const ballRzT = 0

const composerRef = ref(null)      // 输入区容器（顶部把手拖拽调高）

// 输入框顶沿/顶部把手：上下拖拽调节高度（60–260px）
// 窗口语义：上边缘向上拖 = 拉高，向下拖 = 压矮
let vd = null
function vgripDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return
  const ta = composerRef.value ? composerRef.value.querySelector('textarea') : null
  if (!ta) return
  vd = { ta, y: e.clientY, h: ta.offsetHeight }
  document.body.classList.add('ab-vdrag')
  window.addEventListener('pointermove', vgripMove, { passive: false })
  window.addEventListener('pointerup', vgripUp)
}
function vgripMove(e) {
  if (!vd) return
  const h = Math.min(260, Math.max(60, vd.h - (e.clientY - vd.y)))
  vd.ta.style.height = h + 'px'
}
function vgripUp() {
  if (!vd) return
  vd = null
  document.body.classList.remove('ab-vdrag')
  window.removeEventListener('pointermove', vgripMove, { passive: false })
  window.removeEventListener('pointerup', vgripUp)
}

// 技能（后端 SKILL.md 目录，MonkeyCode 同款机制，可安装）
const skills = ref([])           // [{name, description}]
const enabledSkills = ref([])    // 已启用技能名
const instInp = ref(null)
async function loadSkills() {
  try {
    skills.value = await aiApi2.listSkills()
    // 恢复上次启用的技能（仅在技能仍存在时恢复）
    const p = prefs.value
    if (Array.isArray(p.skills) && p.skills.length) {
      enabledSkills.value = p.skills.filter((s) => skills.value.some((sk) => sk.name === s))
    }
  } catch (e) { skills.value = [] }
}
async function toggleSkill(name) {
  const i = enabledSkills.value.indexOf(name)
  if (i >= 0) enabledSkills.value.splice(i, 1)
  else enabledSkills.value.push(name)
}
async function onInstallFile(ev) {
  const f = ev.target.files && ev.target.files[0]
  ev.target.value = ''
  if (!f) return
  if (!/\.md$/i.test(f.name)) { toast('请选择 SKILL.md 技能文件'); return }
  try {
    const text = await f.text()
    const fd = new FormData()
    fd.append('file', new Blob([text], { type: 'text/markdown' }), f.name)
    const r = await aiApi2.installSkill(fd)
    toast('技能已安装：' + r.name)
    await loadSkills()
  } catch (e) { toast('安装失败：' + (e.response?.data?.detail || e.message)) }
}

// 思考深度（MonkeyCode：off / low / medium / high）
const think = ref(['off', 'low', 'medium', 'high'].includes(prefs.value.think) ? prefs.value.think : 'low')
const thinkOpen = ref(false)
const THINK_LABELS = { off: '关闭', low: '低', medium: '中', high: '高' }

// 上下文压缩（MonkeyCode compact）——发送前满足阈值即自动执行，无需手动
const compactBusy = ref(false)
const AUTO_COMPACT_MSGS = 10       // 历史超过 10 条自动压缩
const AUTO_COMPACT_CHARS = 6000    // 或历史超过 6000 字自动压缩（降 tpm 消耗，避免限流）
function buildHistory() {
  return msgs.value
    .filter((m) => m.content && (
      m.role === 'user' || m.role === 'system' || (m.role === 'assistant' && !m.pending && !m.sys)
    ))
    .map((m) => ({ role: m.role === 'user' ? 'user' : m.role, content: m.content }))
}
function histSize(hist) {
  return { len: hist.length, chars: hist.reduce((a, m) => a + (m.content?.length || 0), 0) }
}
function needAutoCompact() {
  const { len, chars } = histSize(buildHistory().slice(0, -1))
  return len >= AUTO_COMPACT_MSGS || chars >= AUTO_COMPACT_CHARS
}
// 自动压缩（静默执行；失败仅提示不中断发送）
async function doCompact(quiet = false) {
  const curS = cur.value
  const texts = buildHistory()
  try {
    compactBusy.value = true
    const r = await aiApi2.agentCompact({ alias: alias.value, model: model.value, history: texts })
    if (!r.summary) { if (!quiet) toast('压缩无结果，请稍后再试'); return false }
    const keep = curS.msgs.slice(-8)
    const n = curS.msgs.length
    curS.msgs = [
      { role: 'assistant', content: '已自动压缩上下文：较早的 ' + (n - keep.length) + ' 条消息已合并为摘要（' + fmt(Date.now()) + '）', sys: true, ts: Date.now() },
      { role: 'system', content: '以下是较早对话的摘要：' + r.summary, ts: Date.now() },
      ...keep,
    ]
    persist(); scrollBottom()
    return true
  } catch (e) {
    if (!quiet) toast('压缩失败：' + (e.response?.data?.detail || e.message))
    return false
  } finally {
    compactBusy.value = false
  }
}
function manualCompact() {
  if (busy.value) return
  busy.value = true
  doCompact(false).finally(() => { busy.value = false })
}
function onAttachFile(ev) {
  const f = ev.target.files && ev.target.files[0]
  ev.target.value = ''
  if (!f) return
  if (busy.value || sendQueue.value.length) { toast('当前正在回答，请等待完成后再添加附件'); return }
  if (!/^image\//.test(f.type)) { toast('仅支持图片附件（报告照片）'); return }
  const a = { name: f.name, ocr: '', fail: false, thumb: URL.createObjectURL(f) }
  attachments.value.push(a)
  // 异步 OCR：识别文本将作为提问上下文一并交给 AI
  fileToDataUrl(f).then((du) => reportApi.ocrJson({ image: du, filename: f.name })).then((r) => {
    const lines = (r.lines || []).map((s) => String(s).trim()).filter(Boolean)
    if (!lines.length) { a.fail = true; toast('附件图片未识别到文字') }
    else { a.ocr = lines.join('\n'); toast('附件识别完成，AI 可读取图片内容') }
  }).catch(() => { a.fail = true; toast('附件识别失败，将仅告知 AI 文件名') })
}
function removeAtt(i) {
  const a = attachments.value[i]
  if (a && a.thumb) URL.revokeObjectURL(a.thumb)
  attachments.value.splice(i, 1)
}

// ---------- 圆点大纲（MonkeyCode OutlineNav 复刻） ----------
const outlineOpen = ref(false)
const activeSeq = ref(-1)
const msgBox = ref(null)
const entries = computed(() => msgs.value
  .filter((m) => m.role === 'user')
  .map((m) => ({ seq: m.seq, label: m.content || '（附件消息）', time: fmt(m.ts) })))
const MAX_DOTS = 10
const railEntries = computed(() => {
  if (entries.value.length <= MAX_DOTS) return entries.value
  const c = Math.max(0, activeSeq === -1 ? entries.value.length - 1 : activeSeq)
  const start = Math.max(0, Math.min(c - Math.floor(MAX_DOTS / 2), entries.value.length - MAX_DOTS))
  return entries.value.slice(start, start + MAX_DOTS)
})
function jumpTo(seq) {
  outlineOpen.value = false
  activeSeq.value = seq
  nextTick(() => {
    const n = msgBox.value && msgBox.value.querySelector('[data-seq="' + seq + '"]')
    if (n) n.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}
function onMsgScroll() {
  updateGScroll()
  const box = msgBox.value
  if (!box) return
  let last = -1
  box.querySelectorAll('[data-seq]').forEach((n) => {
    if (n.offsetTop <= box.scrollTop + 120) last = Number(n.dataset.seq)
  })
  activeSeq.value = last
}

// ---------- 发送 / 打字机 / 思考中 / 发送队列（MonkeyCode 交互） ----------
const sendQueue = ref([])        // [{ id, text }] 待发送队列
const processingItem = ref(null) // 当前正在处理的队列项（思考中）
const qOpen = ref(false)         // 队列面板展开
function scrollBottom() {
  nextTick(() => { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight })
}
// ---------- 正文 Markdown 轻量渲染（无依赖、全转义，防 XSS） ----------
const escText = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
function mdRender(src) {
  if (!src) return ''
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const safeUrl = (u) => (/^https?:\/\//i.test(u) || u.startsWith('/')) ? u : ''
  const inline = (s) => {
    let o = s
    o = o.replace(/`([^`\n]+)`/g, (_, c) => `<code>${esc(c)}</code>`)
    o = o.replace(/\*\*([^*\n]+)\*\*/g, (_, c) => `<strong>${esc(c)}</strong>`)
    o = o.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_, t, u) => {
      const href = safeUrl(esc(u)); return href ? `<a href="${href}" target="_blank" rel="noopener">${esc(t)}</a>` : esc(t)
    })
    o = o.replace(/(^|[^\w*])\*([^*\n]+)\*(?=[^\w*]|$)/g, (_, p, c) => `${p}<em>${esc(c)}</em>`)
    return o
  }
  const lines = String(src).replace(/\r/g, '').split('\n')
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (/^```/.test(line)) {                       // 代码块
      const buf = []; i++
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++ }
      i++
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`)
      continue
    }
    if (/^\s*\|.*\|/.test(line)) {                 // 表格
      const rows = []
      while (i < lines.length && /^\s*\|.*\|/.test(lines[i])) { rows.push(lines[i].trim()); i++ }
      let body = 1
      if (rows[1] && /^[|\s:-]+$/.test(rows[1])) body = 2   // 分隔行 |---|---|
      const cell = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      if (body >= rows.length) { out.push(`<p>${inline(rows[0])}</p>`); continue }
      let t = '<table><thead><tr>' + cell(rows[0]).map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>'
      for (let r = body; r < rows.length; r++) t += '<tr>' + cell(rows[r]).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>'
      out.push(t + '</tbody></table>')
      continue
    }
    if (/^\s*[-*+]\s+/.test(line)) {               // 无序列表
      const items = []
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*+]\s+/, '')); i++ }
      out.push('<ul>' + items.map((it) => `<li>${inline(it)}</li>`).join('') + '</ul>')
      continue
    }
    if (/^\s*\d+[.、)]\s+/.test(line)) {           // 有序列表
      const items = []
      while (i < lines.length && /^\s*\d+[.、)]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+[.、)]\s+/, '')); i++ }
      out.push('<ol>' + items.map((it) => `<li>${inline(it)}</li>`).join('') + '</ol>')
      continue
    }
    if (/^\s*>+\s?/.test(line)) {                  // 引用
      const buf = []
      while (i < lines.length && /^\s*>+\s?/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>+\s?/, '')); i++ }
      out.push(`<blockquote>${inline(buf.join('<br>'))}</blockquote>`)
      continue
    }
    const h = line.match(/^(#{1,3})\s+(.*)$/)      // 标题
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue }   // 分隔线
    if (!line.trim()) { i++; continue }            // 空行
    const buf = [line]; i++                        // 普通段落（合并连续行）
    while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i]) && !/^\s*\|.*\|/.test(lines[i]) &&
           !/^\s*[-*+]\s+/.test(lines[i]) && !/^\s*\d+[.、)]\s+/.test(lines[i]) && !/^\s*>+\s?/.test(lines[i]) &&
           !/^(#{1,3})\s+/.test(lines[i]) && !/^\s*([-*_])\1{2,}\s*$/.test(lines[i])) { buf.push(lines[i]); i++ }
    out.push(`<p>${inline(buf.join('<br>'))}</p>`)
  }
  return out.join('')
}
function typeMsg(m) {
  typing.value = true
  const full = m._full
  let i = 0
  m._timer = setInterval(() => {
    i += 3
    m.content = full.slice(0, i)
    scrollBottom()
    if (i >= full.length) {
      clearInterval(m._timer); m._timer = null
      typing.value = false
      finishTurn()
      persist()   // 打字机完成：把完整正文落库（此前 push 时正文还是空的）
    }
  }, 16)
}
// 结束当前回合：空闲 → 自动处理下一条队列消息
function finishTurn() {
  typing.value = false
  busy.value = false
  processingItem.value = null
  scrollBottom()
  next()
}
function next() {
  const it = sendQueue.value.shift()
  if (it) processItem(it)
}
// 发送：空闲直接处理；忙则加入输入框上方的发送队列（MonkeyCode 同款）
async function send() {
  const text = input.value.trim()
  if (!text && !attachments.value.length) return
  if (!alias.value || !model.value) { toast('请先选择 AI 供应商和模型'); return }
  if (busy.value) {
    if (attachments.value.length) { toast('当前正在回答，请等待完成后发送图片附件'); return }
    sendQueue.value.push({ id: uid(), text, ts: Date.now() })
    input.value = ''
    qOpen.value = true
    toast('已加入发送队列（共 ' + sendQueue.value.length + ' 条）')
    return
  }
  input.value = ''
  processItem({
    id: uid(), text, ts: Date.now(),
    atts: attachments.value.map((a) => ({ name: a.name, fail: a.fail })),
  })
}
function nextSeq() {
  // seq 必须单调递增、永不复用：曾用 msgs.length 导致压缩删除早期消息后 seq 撞车，
  // 两个用户消息同 seq → 圆点大纲两个圆点同时高亮。改为取会话内当前最大 seq + 1。
  let max = -1
  for (const m of msgs.value) {
    if (typeof m.seq === 'number' && m.seq > max) max = m.seq
  }
  return max + 1
}
async function processItem(it) {
  // 附件 OCR 文本拼入上下文
  let ctx = ''
  if (it.atts && it.atts.length) {
    for (const a of it.atts) {
      if (a.ocr) ctx += `\n【附件：${a.name}（报告图片 OCR 识别文本）】\n${a.ocr}\n`
      else if (a.fail) ctx += `\n【附件：${a.name}（图片识别失败，仅告知文件名）】\n`
    }
  }
  attachments.value.forEach((a) => a.thumb && URL.revokeObjectURL(a.thumb))
  attachments.value = []
  const seq = nextSeq()
  msgs.value.push({
    role: 'user', content: it.text, ts: Date.now(), seq,
    atts: it.atts || [],
  })
  persist(); scrollBottom()
  busy.value = true
  processingItem.value = it
  // 上下文过长 → 自动压缩（无需手动，MonkeyCode compact 机制）
  if (needAutoCompact()) {
    await doCompact(true)
    scrollBottom()
  }
  const history = buildHistory().slice(0, -1)
  // 预创建助手消息：任务在服务器端后台执行，进度（搜索小窗/重试）通过订阅实时更新
  const m = {
    role: 'assistant', content: '', _full: '', ts: Date.now(),
    thinking: '', _tk: false, pending: [], searches: [], _busy: null,
    _taskId: null, _running: false, _done: false,
  }
  msgs.value.push(m)
  persist(); scrollBottom()
  try {
    const r = await aiApi2.createAgentTask({
      alias: alias.value, model: model.value, message: it.text + ctx, history,
      think: think.value, skills: enabledSkills.value,
    })
    m._taskId = r.task_id
    m._running = true
    persist()
    markActive(m._taskId, curId.value, seq)
    liveSubscribe(m)
  } catch (e) {
    const d = String(e.response?.data?.detail || e.message || '')
    m._busy = null
    m.content = '出错了：' + d
    persist(); scrollBottom()
    finishTurn()
  }
}
// 后台任务订阅：任务在服务器端跑，前端只是"观众"；断线/刷新后重连即续看
const taskSubs = new Map()   // taskId -> { stop, timer }
// 订阅计数（ref 保证响应式）：taskSubs 是普通 Map，Vue 跟踪不了它的增删，
// 必须用计数器驱动 AI 球状态——否则刷新后"任务在跑但球显示空闲"
const liveCount = ref(0)
const anyRunning = computed(() => liveCount.value > 0)
// 流式强制重渲染信号：每个内容事件自增并绑定在消息列表根上，保证逐帧重渲染（兜底深响应式异常）
const streamTick = ref(0)
function liveSubscribe(m) {
  const tid = m._taskId
  if (!tid || taskSubs.has(tid)) return
  const sub = { timer: null, stop: null, tries: 0 }
  taskSubs.set(tid, sub)
  liveCount.value += 1
  const attempt = async () => {
    if (!m._running || m._done || !taskSubs.has(tid)) return
    try {
      const s = aiApi2.agentTaskStream(tid, (evt) => liveApply(m, evt))
      sub.stop = s.stop
      await s.stream
      sub.tries = 0
    } catch (e) {
      console.error('[LIVE]CATCH', tid, 'tries=' + sub.tries, String((e && e.message) || e))
      if (!m._running || m._done) return
      // 网络/连接中断：服务端任务不受影响，退避后自动重连（1s→10s 封顶）
      sub.tries += 1
      if (sub.tries > 8) {
        // 多次重连仍失败（如任务记录已被服务器过期清理）：停止无谓重试，给出可见结束态
        m._running = false
        m._busy = null
        if (!m.content) m.content = '（任务连接中断，未能恢复进度）'
        persist()
        closeSub(tid)
        finishTurn()
        return
      }
      sub.timer = setTimeout(attempt, Math.min(1000 * sub.tries, 10000))
      return
    }
    // 流正常结束但任务仍未完成（服务端未发终态）：1 秒后继续看；累计次数防御死循环
    if (m._running && !m._done) {
      sub.tries += 1
      if (sub.tries > 8) {
        // 服务端异常提前断开且不发终态：停止重连，保留已流式显示的内容，给出可见结束态
        m._running = false
        m._busy = null
        if (!m.content) m.content = '（连接已中断，后台任务可能仍在执行）'
        persist()
        closeSub(tid)
        finishTurn()
        return
      }
      sub.timer = setTimeout(attempt, Math.min(1000 * sub.tries, 10000))
    }
  }
  attempt()
}
// 流式内容（delta/think）期间：防抖持久化与贴底滚动，避免高频事件拖慢渲染
let streamPt = 0, streamSt = 0
function scheduleStreamPersist() {
  if (streamPt) clearTimeout(streamPt)
  streamPt = setTimeout(() => { streamPt = 0; persist() }, 900)
}
function scheduleStreamScroll() {
  if (streamSt) return
  streamSt = setTimeout(() => { streamSt = 0; scrollBottom() }, 120)
}
// 事件级容错：单个事件处理失败（如持久化异常）不中断整条 SSE 流，
// 后续 delta/think 仍逐字渲染。失败事件记录便于定位。
function liveApply(m, evt) {
  try { liveApplyInner(m, evt) }
  catch (e) { console.error('[LIVE]APPLY_ERR', evt && evt.type, String((e && e.stack) || e)) }
}
function liveApplyInner(m, evt) {
  // 防御：工具型任务会先出现 web_search/step 而非正文，确保字段已初始化
  if (!m.searches) m.searches = []
  if (!m.steps) m.steps = []
  // 流式强制重渲染：内容/状态事件均推进 tick，消息列表逐帧刷新显示增量
  if (evt.type !== 'done') streamTick.value += 1
  if (evt.type === 'delta') {
    // 正文实时打字：服务端逐块推送，直接拼接即时渲染
    if (m._timer) { clearInterval(m._timer); m._timer = null }   // 停用旧打字机（流式已实时）
    m.content = (m.content || '') + evt.text
    scheduleStreamPersist(); scheduleStreamScroll()
  } else if (evt.type === 'think') {
    // 推理过程实时累积（折叠块内逐字呈现）；首个推理事件自动展开，让用户实时看到推理过程
    if (m._timer) { clearInterval(m._timer); m._timer = null }
    if (!m._tk) m._tk = true
    m.thinking = (m.thinking || '') + evt.text
    scheduleStreamPersist()
  } else if (evt.type === 'delta_reset') {
    // 网络中断后服务端从头重试：截断到其实际输出进度，避免文字重复
    m.content = String(m.content || '').slice(0, evt.content || 0)
    m.thinking = String(m.thinking || '').slice(0, evt.think || 0)
    scheduleStreamPersist()
  } else if (evt.type === 'cur') {
    // 刷新/重连进度快照：把正文与推理补到服务端当前进度
    if (evt.reply && evt.reply.length > (m.content || '').length) m.content = evt.reply
    if (evt.thinking && evt.thinking.length > (m.thinking || '').length) m.thinking = evt.thinking
    persist(); scrollBottom()
  } else if (evt.type === 'web_search') {
    const st = evt.status === 'running' ? 'run' : 'done'
    let s = m.searches.find((x) => x.q === evt.query)
    if (!s) { s = { q: evt.query, status: st, results: [], error: '', _exp: false }; m.searches.push(s) }
    s.status = st
    if (evt.status === 'done') { s.results = evt.results || []; s.error = evt.error || '' }
    persist(); scrollBottom()
  } else if (evt.type === 'step') {
    // 执行步骤（MonkeyCode 式任务列表）：running → done 逐项推进
    m.steps = m.steps || []
    let it = m.steps.find((x) => x.id === evt.id)
    if (!it) { it = { id: evt.id, fn: evt.fn, desc: evt.desc, status: evt.status }; m.steps.push(it) }
    else { it.status = evt.status; if (evt.desc) it.desc = evt.desc }
    scrollBottom()
  } else if (evt.type === 'busy') {
    // 供应商限流：模型服务在自动排队退避重试，显示进度而非报错
    m._busy = { attempt: evt.attempt, wait: evt.wait }
    persist()
  } else if (evt.type === 'done') {
    m._done = true
    m._running = false
    m._busy = null
    m._full = evt.reply || '（模型未返回内容）'
    // 刷新后重连的场景：补齐搜索小窗数据
    if (evt.searches && evt.searches.length && !m.searches.length) {
      m.searches = evt.searches.map((x) => ({
        q: x.q, status: x.done ? 'done' : 'run', results: x.results || [], error: x.error || '', _exp: false,
      }))
    }
    // 推理已流式累积；全量比累积更长时（刷新后重连）取全量对齐
    if (evt.thinking && evt.thinking.length > (m.thinking || '').length) m.thinking = evt.thinking
    m.pending = (evt.pending_actions || []).map((a) => ({ ...a, status: 'wait' }))
    // 正文已实时流式显示：直接对齐最终全文收尾，无需再逐字打字
    if (m._full && (!m.content || m.content.length < m._full.length)) m.content = m._full
    m._typed = true
    persist()
    closeSub(m._taskId)
    unmarkActive(m._taskId)
    finishTurn()
  } else if (evt.type === 'cancelled') {
    m._done = true
    m._running = false
    m._busy = null
    if (m._full && (!m.content || m.content.length < m._full.length)) m.content = m._full
    else if (!m.content) m.content = '已停止'
    persist(); scrollBottom()
    closeSub(m._taskId)
    unmarkActive(m._taskId)
    finishTurn()
  } else if (evt.type === 'error') {
    m._done = true
    m._running = false
    m._busy = null
    const d = String(evt.message || '')
    const busy = /429|limit|rate|繁忙|限流|quota|tpm/.test(d)
    m.content = busy
      ? 'AI 服务繁忙（限流）。' + (m.searches.length
        ? '联网搜索结果已保留，稍后可直接重发提问。'
        : '请稍等再试（系统在自动排队重试，可先做其他操作）。')
      : '出错了：' + d
    persist(); scrollBottom()
    closeSub(m._taskId)
    unmarkActive(m._taskId)
    finishTurn()
  }
}
function closeSub(tid) {
  if (!tid) return
  const sub = taskSubs.get(tid)
  if (sub) {
    if (sub.timer) clearTimeout(sub.timer)
    try { sub.stop && sub.stop() } catch (e) {}
    if (taskSubs.delete(tid)) liveCount.value -= 1
  }
}
// 页面刷新后恢复仍在前台运行的后台任务（离开再回来继续看）
// 以独立登记簿驱动：即使任务消息被同步覆盖，也能按 会话+seq 重建占位消息再订阅事件流
function resumeLiveTasks() {
  for (const act of activeList()) {
    const sess = store.value.sessions.find((s) => s.id === act.sid)
    let m = sess ? sess.msgs.find((x) => x.role === 'assistant' && x._taskId === act.tid) : null
    if (!m && sess && act.seq != null) {
      const ui = sess.msgs.findIndex((x) => x.seq === act.seq)
      if (ui >= 0) {
        m = { role: 'assistant', content: '', _full: '', ts: Date.now(), thinking: '', _tk: false,
          pending: [], searches: [], _busy: null, _taskId: act.tid, _running: true, _done: false }
        sess.msgs.splice(ui + 1, 0, m)
      }
    }
    if (!m || m._done || !m._running || m._full) { unmarkActive(act.tid); continue }
    liveSubscribe(m)
    persist()
    scrollBottom()
  }
}
// 联网搜索小窗：展开/收起
function toggleSearchExp(s) { s._exp = !s._exp }
// 阅读全文：后端抓取网页正文，就地展示
async function readFull(s, r) {
  if (r._loading) return
  r._loading = true
  try {
    const res = await aiApi2.webFetch(r.url)
    r._body = (res && res.text) ? res.text.trim() : '（无正文）'
  } catch (e) {
    r._body = '读取失败：' + (e.response?.data?.detail || e.message)
  }
  r._loading = false
}
// 停止生成：取消服务器端后台任务（保留已输出内容），队列保留可继续可删
function stopGen() {
  // 遍历所有会话：刷新后恢复的后台任务可能不在当前会话，但都要一并停止
  for (const s of store.value.sessions) {
    for (const m of (s.msgs || [])) {
      if (m._timer) { clearInterval(m._timer); m._timer = null }
      // 中断时把已收到的完整回复补进正文，避免只留半截
      if (m._full && (!m.content || m.content.length < m._full.length)) m.content = m._full
      if (m._running && m._taskId) {
        m._running = false
        aiApi2.cancelAgentTask(m._taskId).catch(() => {})
        unmarkActive(m._taskId)
      }
      closeSub(m._taskId)
    }
  }
  typing.value = false
  busy.value = false
  processingItem.value = null
  persist()
  scrollBottom()
}
// 队列编辑（textarea 即改即生效）/ 删除 / 清空
function delQueue(i) { sendQueue.value.splice(i, 1) }
function clearQueue() { sendQueue.value = [] }
function confirmAction(a) {
  a.status = 'run'
  aiApi2.agentExecute({ action: { id: a.id, name: a.name, args: a.args, desc: a.desc } }).then((r) => {
    a.status = 'done'
    msgs.value.push({ role: 'assistant', content: (r.result_text || '操作已完成') + '（已同步到系统数据）', executed: true, ts: Date.now() })
    persist(); scrollBottom()
  }).catch((e) => {
    a.status = 'wait'
    toast('执行失败：' + (e.response?.data?.detail || e.message))
  })
}
function cancelAction(a) { a.status = 'cancel'; persist() }

// 思考过程折叠（MonkeyCode 同款：默认收起，点击展开）
function toggleThink(m) { m._tk = !m._tk }

// ---------- 快捷入口 ----------
const gates = [
  { to: '/report', lbl: '检查报告' }, { to: '/med', lbl: '用药记录' },
  { to: '/tpl', lbl: '报告模板' }, { to: '/ai', lbl: 'AI 配置' },
]
function goto(p) { open.value = false; router.push(p) }

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('resize', onBallResize)
  if (ballDrag) ballUp()
  if (msgsRo) msgsRo.disconnect()
  if (gsRaf) cancelAnimationFrame(gsRaf)
  if (vd) vgripUp()
  attachments.value.forEach((a) => a.thumb && URL.revokeObjectURL(a.thumb))
})

// ---------- 弹窗：居中 / 任意拖动 / 缩放 / 最大化 ----------
const panelEl = ref(null)
const maximized = ref(false)
const savedPos = ref({ x: 0, y: 0, w: 920, h: 620 })
const pos = ref({ x: 0, y: 0, w: 920, h: 620 })
let dragState = null

function centerPanel() {
  const w = Math.min(920, window.innerWidth - 48)
  const h = Math.min(Math.round(window.innerHeight * 0.78), 760)
  const x = Math.max(10, Math.round((window.innerWidth - w) / 2))
  const y = Math.max(10, Math.round((window.innerHeight - h) / 2))
  pos.value = { x, y, w, h }
  savedPos.value = { ...pos.value }
}
const panelStyle = computed(() => ({
  left: pos.value.x + 'px',
  top: pos.value.y + 'px',
  width: pos.value.w + 'px',
  height: pos.value.h + 'px',
}))

function onHeadDown(e) {
  if (maximized.value) return
  if (window.innerWidth <= 720) return   // 移动端全屏面板不拖动
  if (e.target.closest('button')) return // 顶栏按钮不触发拖动
  e.preventDefault()
  const r = panelEl.value.getBoundingClientRect()
  dragState = { dx: e.clientX - r.left, dy: e.clientY - r.top, w: r.width, h: r.height }
  window.addEventListener('pointermove', onHeadMove)
  window.addEventListener('pointerup', onHeadUp)
}
function onHeadMove(e) {
  if (!dragState) return
  pos.value.x = Math.max(-300, Math.min(window.innerWidth - 60, e.clientX - dragState.dx))
  pos.value.y = Math.max(0, Math.min(window.innerHeight - 40, e.clientY - dragState.dy))
}
function onHeadUp() {
  dragState = null
  window.removeEventListener('pointermove', onHeadMove)
  window.removeEventListener('pointerup', onHeadUp)
}

function onResizeDown(e) {
  if (maximized.value) return
  if (window.innerWidth <= 720) return   // 移动端全屏面板不可缩放
  e.preventDefault(); e.stopPropagation()
  const r = panelEl.value.getBoundingClientRect()
  dragState = { w: r.width, h: r.height, x: e.clientX, y: e.clientY }
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', onResizeUp)
}
function onResizeMove(e) {
  if (!dragState) return
  pos.value.w = Math.max(680, Math.min(window.innerWidth - 16, dragState.w + (e.clientX - dragState.x)))
  pos.value.h = Math.max(420, Math.min(window.innerHeight - 16, dragState.h + (e.clientY - dragState.y)))
}
function onResizeUp() {
  dragState = null
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', onResizeUp)
}

function toggleMax() {
  if (window.innerWidth <= 720) return   // 移动端面板恒为全屏
  if (!maximized.value) {
    savedPos.value = { ...pos.value }
    pos.value = { x: 10, y: 10, w: window.innerWidth - 20, h: window.innerHeight - 20 }
    maximized.value = true
  } else {
    pos.value = { ...savedPos.value }
    maximized.value = false
  }
}

// 右侧消息区自绘滚动条（规避浏览器 overlay 滚动条差异，任何环境可见）
const gScroll = ref({ thumbH: 26, top: 0 })
const scbarEl = ref(null)
let msgsRo = null
let gsRaf = 0
function updateGScroll() {
  menuFor.value = null   // 滚动时收起左栏三点菜单
  const el = msgBox.value
  const bar = scbarEl.value
  if (!el || !bar) return
  const sh = el.scrollHeight, ch = el.clientHeight
  const bh = bar.clientHeight   // 轨道可视高度（含上下缩进）
  const can = sh > ch + 2
  const thumbH = Math.max(26, can ? (bh * bh) / sh : Math.min(26, bh * 0.15))
  const top = can ? (el.scrollTop / (sh - ch)) * (bh - thumbH) : 0
  gScroll.value = { thumbH, top }
}
function scheduleGScroll() {
  if (gsRaf) return
  gsRaf = requestAnimationFrame(() => { gsRaf = 0; updateGScroll() })
}
watch(msgs, scheduleGScroll, { deep: true })

// OnMounted 与新增功能合并（保持单一挂载入口）
onMounted(() => {
  loadModels(); centerPanel(); loadSkills()
  loadBallPos()
  window.addEventListener('resize', onBallResize)
  syncRemote().finally(() => { resumeLiveTasks() })   // 恢复刷新前仍在前台运行的后台任务
  document.addEventListener('click', onDocClick)
  // 刷新/关闭页面前强制同步：300ms 防抖的"最后一次"可能来不及发出去，这里用同步请求补上
  window.addEventListener('beforeunload', () => {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
    try {
      const x = new XMLHttpRequest()
      x.open('POST', '/api/ai/sessions', false)
      x.setRequestHeader('Content-Type', 'application/json')
      const tk = localStorage.getItem('token')
      if (tk) x.setRequestHeader('Authorization', 'Bearer ' + tk)
      x.send(JSON.stringify({
        groups: store.value.groups, sessions: store.value.sessions, ver: store.value._ver || 0,
      }))
    } catch (e) { /* 刷新前同步失败不阻塞页面 */ }
  })
  updateGScroll()
  if (typeof ResizeObserver !== 'undefined' && msgBox.value) {
    msgsRo = new ResizeObserver(() => updateGScroll())
    msgsRo.observe(msgBox.value)
  }
})

// 记住上次停留的会话；打开面板时自动滚动到最新消息（最底部）
watch(curId, (id) => { if (id) localStorage.setItem(LAST_CHAT, id) }, { immediate: true })
// 记住模型 / 供应商 / 思考深度 / 技能选择（刷新不丢）
watch([alias, model, think, enabledSkills], savePrefs)
watch(open, (v) => {
  if (v) setTimeout(() => scrollBottom(), 240)   // 等面板过渡动画完成后再贴底
})
// 移动端：打开会话列表抽屉时收起输入区弹出菜单（技能/思考），避免压在抽屉上
watch(sideOpen, (v) => {
  if (v) { skillOpen.value = false; thinkOpen.value = false }
})
</script>

<template>
  <!-- 输入弹窗（分组/会话命名，自定义取代浏览器 prompt） -->
  <Transition name="fade">
    <div v-if="dlg" class="ab-dlgmask" @click.self="dlg = null">
      <div class="ab-dlg">
        <div class="ab-dlg-title">{{ dlg.title }}</div>
        <input ref="dlgInp" v-model="dlg.value" class="ab-dlg-input" :placeholder="dlg.title"
          @keydown.enter="dlgOk" @keydown.esc="dlg = null" />
        <div class="ab-dlg-ops">
          <button class="c" @click="dlg = null">取消</button>
          <button class="ok" @click="dlgOk">确定</button>
        </div>
      </div>
    </div>
  </Transition>

  <!-- 确认弹窗（取代浏览器 confirm：删除会话/分组） -->
  <Transition name="fade">
    <div v-if="cdlg" class="ab-dlgmask" @click.self="cdlg = null">
      <div class="ab-dlg">
        <div class="ab-dlg-title">{{ cdlg.title }}</div>
        <div class="ab-dlg-msg">{{ cdlg.message }}</div>
        <div class="ab-dlg-ops">
          <button class="c" @click="cdlg = null">取消</button>
          <button class="ok dan" @click="cdlgOk">{{ cdlg.okText }}</button>
        </div>
      </div>
    </div>
  </Transition>

  <!-- 会话三点菜单：Teleport 到 body，固定定位不再被左栏裁剪 -->
  <Teleport to="body">
    <div v-if="menuFor" class="ab-smenu" :style="menuStyle" @click.stop>
      <button @click="renameSession(curSession)">重命名会话</button>
      <div class="ab-smove">移动到 <span>▸</span>
        <div class="ab-ssub">
          <button v-for="g2 in groups" :key="g2.id" :class="{ on: curSession?.groupId === g2.id }"
            @click.stop="moveSession(curSession, g2.id)">{{ g2.name }}</button>
        </div>
      </div>
      <button class="dan" @click="delChat(curSession.id)">删除会话</button>
    </div>
  </Teleport>

  <!-- 遮罩：点击外部关闭 -->
  <Transition name="fade">
    <div v-show="open" class="ab-mask" @click="open = false" />
  </Transition>

  <!-- 弹窗（v-show 保留 DOM：关闭时任务/打字机/滚动条不受影响） -->
  <Transition name="pop">
    <div v-show="open" ref="panelEl" class="ab-panel" :class="{ max: maximized }" :style="panelStyle">
      <!-- 左：会话 / 项目区域 -->
      <aside class="ab-side" :class="{ open: sideOpen }" @click="menuFor = null">
        <div class="ab-brand">
          <div class="ab-logo">问</div>
          <div><b>AI 问数</b><span>数据问答 · 历史会话</span></div>
        </div>
        <button class="ab-new" @click="newChatIn('default')">＋ 新建会话</button>
        <div class="ab-sec-t">会话历史</div>
        <div class="ab-grps" @scroll="updateGScroll">
          <div v-for="g in groups" :key="g.id" class="ab-grp">
            <div class="ab-grp-h" :class="{ fold: folded[g.id] }" @click="toggleFold(g.id)">
              <span class="ab-chev">{{ folded[g.id] ? '▸' : '▾' }}</span>
              <b>{{ g.name }}</b><span class="ab-cnt">{{ countOf(g.id) }}</span>
              <span class="ab-grp-ops" @click.stop>
                <button title="在此分组新建会话" @click="newChatIn(g.id)">＋</button>
                <button v-if="g.id !== 'default'" title="重命名分组" @click="renameGroup(g)">✎</button>
                <button v-if="g.id !== 'default'" title="删除分组" @click="delGroup(g)"><svg class="ico" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M10 11v6M14 11v6" /></svg></button>
              </span>
            </div>
            <ul v-if="!folded[g.id]" class="ab-sess">
              <li v-for="s in sessionsOf(g.id)" :key="s.id" :class="{ on: s.id === curId }" @click="switchChat(s.id)">
                  <span class="s-dot"></span>
                  <span class="s-title">{{ titleOf(s) }}</span>
                  <span class="s-menu" @click.stop="openMenu(s, $event)">⋯</span>
                </li>
            </ul>
          </div>
        </div>
        <div class="ab-sec-t">系统模块</div>
        <div class="ab-gates">
          <button v-for="g in gates" :key="g.to" @click="goto(g.to)">{{ g.lbl }}<span>›</span></button>
        </div>
        <button class="ab-new grp" @click="newGroup">＋ 新建分组</button>
      </aside>

      <!-- 移动端抽屉遮罩：点击空白处关闭会话列表（☰ 会被抽屉盖住，需独立关闭入口） -->
      <Transition name="fade">
        <div v-show="sideOpen" class="ab-side-mask" @click="sideOpen = false" />
      </Transition>

      <!-- 右：会话区域 -->
      <section class="ab-main">
        <header class="ab-head" @pointerdown="onHeadDown">
          <div class="ab-hl">
            <span class="ab-status" :class="busy ? 'busy' : 'idle'"></span>
            <b>{{ titleOf(cur) }}</b>
            <span class="ab-hsub">{{ modelGroups.length ? model || '未选模型' : '未配置 AI 模型' }}</span>
          </div>
          <div class="ab-acts">
            <button class="ab-ico ab-sidebtn" :class="{ on: sideOpen }" title="会话列表" @click="sideOpen = !sideOpen">☰</button>
            <button class="ab-ico" title="清空当前会话" :disabled="!msgs.length" @click="resetChat">
              <svg class="ico" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M10 11v6M14 11v6" /></svg>
            </button>
            <button class="ab-ico ab-mx" :title="maximized ? '还原窗口' : '放大窗口'" @click="toggleMax">
              <svg v-if="!maximized" class="ico" viewBox="0 0 24 24"><path d="M4 4h16v16H4z" /></svg>
              <svg v-else class="ico" viewBox="0 0 24 24"><path d="M4 8V4h4M20 4h-4v4M20 16v4h-4M4 20h4v-4" /></svg>
            </button>
            <button class="ab-ico" title="关闭" @click="open = false">✕</button>
          </div>
        </header>

        <!-- 上：实时显示区。圆点列作为固定占位列（不随滚动），消息区在其右侧 -->
        <div class="ab-msgs-wrap">
          <!-- 圆点大纲：固定 30px 占位列，不随消息滚动 -->
          <nav class="ab-outline" @mouseenter="outlineOpen = true" @mouseleave="outlineOpen = false">
            <div class="ab-rail">
              <span v-for="e in railEntries" :key="e.seq" class="ab-dot" :class="{ on: e.seq === activeSeq }" />
            </div>
            <Transition name="fade">
              <div v-if="outlineOpen && entries.length" class="ab-opanel">
                <div class="ab-otitle">每次提问</div>
                <div v-for="e in entries" :key="e.seq" class="ab-oitem" :class="{ cur: e.seq === activeSeq }"
                  @click="jumpTo(e.seq)">
                  <span class="ab-olbl">{{ e.label }}</span>
                  <span class="ab-otime">{{ e.time }}</span>
                </div>
              </div>
            </Transition>
          </nav>
          <div ref="msgBox" class="ab-msgs" @scroll.passive="onMsgScroll">
            <div class="ab-flow" :data-tick="streamTick">
              <!-- 系统提示条（压缩通知等）：全宽居中 -->
            <div v-for="(m, i) in sysMsgs" :key="'s' + i" class="ab-sys">{{ m.content }}</div>
            <div v-for="m in msgs" :key="m._id || m.ts + '_' + msgs.indexOf(m)" class="ab-msg" :class="m.role"
              :data-seq="m.role === 'user' ? m.seq : undefined">
              <div class="ab-bubble">
                <div class="ab-who">{{ m.role === 'user' ? '你' : 'AI 助手' }}</div>
                <div v-if="m.atts && m.atts.length" class="ab-atts">
                  <span v-for="(a, i) in m.atts" :key="i" class="ab-att"><svg class="ico" viewBox="0 0 24 24"><path d="M21 11.5a5 5 0 0 0-7-7l-7 7a3.5 3.5 0 0 0 5 5l7-7" /></svg> {{ a.name }}<em>{{ a.fail ? '（识别失败）' : '（已识别）' }}</em></span>
                </div>
                <!-- 思考过程：MonkeyCode 折叠块，点击展开/收起 -->
                <div v-if="m.role === 'assistant' && m.thinking" class="ab-think" :class="{ on: m._tk }"
                  @click="toggleThink(m)">
                  <div class="ab-think-head">
                    <span>💭 思考过程</span>
                    <span class="ab-think-arrow">{{ m._tk ? '▲' : '▼' }}</span>
                  </div>
                  <pre v-if="m._tk" class="ab-think-body">{{ m.thinking }}</pre>
                </div>
                <!-- 限流排队重试提示条：供应商限流时自动退避重试，不报错打断 -->
                <div v-if="m.role === 'assistant' && m._busy" class="ab-busy">
                  AI 服务繁忙，自动排队重试中（第 {{ m._busy.attempt }} 次，等待 {{ m._busy.wait }} 秒）…
                </div>
                <!-- 联网搜索小窗：默认一行，点击放大查看结果/阅读全文 -->
                <div v-if="m.role === 'assistant' && m.searches && m.searches.length" class="ab-srch">
                  <div v-for="s in m.searches" :key="s.q" class="ab-srch-step" :class="{ open: s._exp }">
                    <div class="ab-srch-head" @click="toggleSearchExp(s)">
                      <span class="ab-srch-ic"><svg class="ico" viewBox="0 0 24 24"><path d="M21 21l-4.3-4.3M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z" /></svg></span>
                      <span class="ab-srch-q" :title="s.q">{{ s.q }}</span>
                      <span v-if="s.status === 'run'" class="ab-srch-st run"><span class="ab-spin"></span>搜索中…</span>
                      <span v-else-if="s.error" class="ab-srch-st err">{{ s.error }}</span>
                      <span v-else class="ab-srch-st">{{ s.results.length }} 条 · {{ s._exp ? '收起 ▲' : '展开 ▼' }}</span>
                    </div>
                    <div v-if="s.status === 'done' && s._exp" class="ab-srch-body">
                      <div v-for="(r, ri) in s.results" :key="ri" class="ab-srch-res">
                        <div class="ab-srch-res-t">
                          <a :href="r.url" target="_blank" rel="noopener">{{ r.title }}</a>
                          <button class="ab-mini" @click.stop="readFull(s, r)">{{ r._loading ? '读取中…' : (r._body ? '已读取' : '阅读全文') }}</button>
                        </div>
                        <div class="ab-srch-res-s">{{ r.snippet }}</div>
                        <div v-if="r._body" class="ab-srch-res-body"><pre>{{ r._body }}</pre></div>
                      </div>
                    </div>
                  </div>
                </div>
                <!-- 执行步骤（MonkeyCode 式任务分解：搜索/查询/阅读逐一执行并打勾） -->
                <div v-if="m.role === 'assistant' && m.steps && m.steps.length" class="ab-steps">
                  <div v-for="s in m.steps" :key="s.id" class="ab-step" :class="s.status">
                    <span class="ab-step-ic">{{ s.status === 'done' ? '✓' : (s.status === 'running' ? '⟳' : (s.status === 'error' ? '✕' : '•')) }}</span>
                    <span class="ab-step-desc">{{ s.desc }}</span>
                  </div>
                </div>
                <div class="ab-txt" :class="{ 'ab-md': !m._timer }"
                  v-html="m._timer ? escText(m.content) : mdRender(m.content)"></div>
                <!-- 待确认写操作卡片 -->
                <div v-if="m.pending && m.pending.length" class="ab-pends">
                  <div v-for="a in m.pending" :key="a.id" class="ab-pend" :class="'st-' + a.status">
                    <div class="ab-pend-head"><span class="ab-badge">写操作</span><b>{{ a.desc }}</b></div>
                    <div class="ab-pend-args">{{ a.name }}({{ JSON.stringify(a.args) }})</div>
                    <div class="ab-pend-ops">
                      <template v-if="a.status === 'wait'">
                        <button class="ab-mini pri" @click="confirmAction(a)">确认执行</button>
                        <button class="ab-mini" @click="cancelAction(a)">取消</button>
                      </template>
                      <span v-else-if="a.status === 'run'" class="ab-mut"><span class="ab-spin"></span> 执行中…</span>
                      <span v-else-if="a.status === 'done'" class="ab-rs ok">✓ 已执行</span>
                      <span v-else class="ab-mut">已取消</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- busy 状态条 -->
            <div v-if="busy" class="ab-msg assistant">
              <div class="ab-bubble ab-busy">
                <span class="ab-spin"></span>
                <template v-if="compactBusy">正在压缩上下文…（会话较长，自动合并早期消息）</template>
                <template v-else-if="typing">正在输出…</template>
                <template v-else>正在处理…（AI 服务繁忙会自动重试，请稍候）</template>
              </div>
            </div>
          </div>
          </div>
            <div ref="scbarEl" class="ab-scbar"><div class="ab-thumb" :style="{ height: gScroll.thumbH + 'px', transform: 'translateY(' + gScroll.top + 'px)' }" /></div>
        </div>

        <!-- 下：输入区 -->
        <div class="ab-composer" ref="composerRef">
          <!-- 待发送附件 chips -->
          <div v-if="attachments.length" class="ab-chiprow">
            <div v-for="(a, i) in attachments" :key="i" class="ab-chip">
              <img v-if="a.thumb" :src="a.thumb" alt="">
              <span>{{ a.name }}</span>
              <em>{{ a.ocr ? '✓ 已识别' : (a.fail ? '识别失败' : '识别中…') }}</em>
              <button @click="removeAtt(i)">✕</button>
            </div>
          </div>
          <!-- 思考中 + 发送队列（MonkeyCode：输入框上方状态条，直到该回合完成才消失） -->
          <!-- anyRunning：刷新后恢复的后台任务也在此显示"任务执行中"，保证可手动停止 -->
          <div v-if="processingItem || sendQueue.length || anyRunning" class="ab-aiq">
            <div v-if="processingItem" class="ab-aiq-working">
              <span class="ab-aiq-spin"></span>
              <span class="ab-aiq-txt">思考中「{{ processingItem.text.slice(0, 22) }}{{ processingItem.text.length > 22 ? '…' : '' }}」</span>
              <button class="ab-aiq-stop" title="中断本次回答（已输出的内容会保留）" @click="stopGen">■ 停止</button>
            </div>
            <div v-else-if="anyRunning" class="ab-aiq-working">
              <span class="ab-aiq-spin"></span>
              <span class="ab-aiq-txt">后台任务执行中…（页面刷新后已自动恢复）</span>
              <button class="ab-aiq-stop" title="中断该任务（已输出的内容会保留）" @click="stopGen">■ 停止</button>
            </div>
            <div v-if="sendQueue.length" class="ab-aiq-q">
              <div class="ab-aiq-qhead" @click="qOpen = !qOpen">
                <span>待发送队列（{{ sendQueue.length }} 条）<em>{{ qOpen ? '▲ 收起' : '▼ 展开' }}</em></span>
                <span class="ab-aiq-qops"><button title="清空队列" @click.stop="clearQueue">清空</button></span>
              </div>
              <div v-if="qOpen" class="ab-aiq-qlist">
                <div v-for="(it, i) in sendQueue" :key="it.id" class="ab-aiq-item">
                  <textarea v-model="it.text" rows="2" spellcheck="false" placeholder="编辑后按修改的内容发送" />
                  <div class="ab-aiq-itemops">
                    <span class="ab-aiq-no">#{{ i + 1 }}</span>
                    <button title="删除该条" @click="delQueue(i)">✕</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="ab-vgrip" title="上下拖动调节输入框高度" @pointerdown.prevent.stop="vgripDown"></div>
          <textarea v-model="input" rows="2" placeholder="问系统里的任何数据，例如：统计一下检查记录；也可以让我新增/修改记录（会先让你确认）"
            @keydown.enter.exact.prevent="send"
            @pointerdown="(e) => { if (e.offsetY <= 8) { vgripDown(e); e.preventDefault() } }"></textarea>
          <!-- 底部工具条：附件 / 技能 / 思考 / 模型 / 发送 -->
          <div class="ab-toolbar">
            <button class="ab-tbtn" title="添加报告图片附件（AI 自动识别内容）" @click="imgInp && imgInp.click()"><svg class="ico" viewBox="0 0 24 24"><path d="M21 11.5a5 5 0 0 0-7-7l-7 7a3.5 3.5 0 0 0 5 5l7-7" /></svg></button>
            <input ref="imgInp" type="file" accept="image/*" style="display:none" @change="onAttachFile">
            <div class="ab-skillwrap" @click.stop="skillOpen = !skillOpen">
              <button class="ab-tbtn" :class="{ on: skillOpen }">技能{{ enabledSkills.length ? '·' + enabledSkills.length : '' }} ▾</button>
              <Transition name="fade">
                <div v-if="skillOpen" class="ab-skillmenu" @click.stop>
                  <div class="ab-sm-title">已安装技能（可多选）</div>
                  <div v-for="sk in skills" :key="sk.name" class="ab-skill" :class="{ on: enabledSkills.includes(sk.name) }"
                    @click="toggleSkill(sk.name)">
                    <b>☑{{ enabledSkills.includes(sk.name) ? '✓' : '' }} {{ sk.name }}</b>
                    <span>{{ sk.description }}</span>
                  </div>
                  <div v-if="!skills.length" class="ab-sm-none">暂无技能，可上传 SKILL.md 安装</div>
                  <div class="ab-sm-foot">
                    <button class="ab-tbtn" @click="instInp && instInp.click()">＋ 安装技能（SKILL.md）</button>
                  </div>
                </div>
              </Transition>
            </div>
            <input ref="instInp" type="file" accept=".md" style="display:none" @change="onInstallFile">
            <div class="ab-thinkwrap" @click.stop="thinkOpen = !thinkOpen">
              <button class="ab-tbtn" :class="{ on: thinkOpen }" title="思考深度">思考 {{ THINK_LABELS[think] || '低' }} ▾</button>
              <Transition name="fade">
                <div v-if="thinkOpen" class="ab-thinkmenu" @click.stop>
                  <div class="ab-sm-title">思考深度</div>
                  <button v-for="(lbl, k) in THINK_LABELS" :key="k" class="ab-skill" :class="{ on: think === k }"
                    @click="think = k; thinkOpen = false">
                    <b>{{ lbl }}</b>
                    <span>{{ k === 'off' ? '简洁直接，不做多余推理' : k === 'low' ? '清晰有条理地回答' : k === 'medium' ? '分步推理，适当展开' : '深入分析，逐步推演' }}</span>
                  </button>
                </div>
              </Transition>
            </div>
            <div class="ab-sp"></div>
            <SearchSelect v-model="alias" class="ab-sel" style="width:110px" @change="pickAlias"
              :options="modelGroups.map((g) => ({ value: g.alias, label: g.alias }))" placeholder="供应商" />
            <SearchSelect v-model="model" class="ab-sel" style="width:150px"
              :options="(modelGroups.find((g) => g.alias === alias)?.items || []).map((m) => ({ value: m.name, label: m.name }))"
              placeholder="模型" />
            <button class="ab-send" @click="send" :disabled="(!input.trim() && !attachments.length) || !alias || !model">
              {{ busy ? '排队' : '发送' }}
            </button>
          </div>
          <!-- 已启用技能 chips -->
          <div v-if="enabledSkills.length" class="ab-skillchips">
            <span v-for="n in enabledSkills" :key="n" class="ab-chip ab-skchip">
              <em>技能</em><span>{{ n }}</span><button @click="toggleSkill(n)">✕</button>
            </span>
          </div>
        </div>
      </section>

      <!-- 右下角缩放手柄 -->
      <div class="ab-resize" :class="{ hide: maximized }" title="拖动调整窗口大小" @pointerdown="onResizeDown"></div>
    </div>
  </Transition>

  <!-- AI 球 -->
  <button ref="ballRef" class="ab-ball" :class="{ on: open, busy: busy || typing || sendQueue.length > 0 || processingItem || anyRunning, drag: !!ballDrag }"
    :style="ballStyle()" @pointerdown.prevent="ballDown" @click="ballClick"
    title="AI 问数（点击展开，按住可拖到任意位置）">
    <span class="ab-ball-ico">{{ open ? '✕' : 'AI' }}</span>
    <span class="ab-ring"></span>
  </button>

  <div class="ab-toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
</template>

<style scoped>
/* ---- 遮罩 ---- */
.ab-mask { position: fixed; inset: 0; background: rgba(10, 14, 22, .32); z-index: 90; backdrop-filter: blur(2px); }

/* ---- 面板 ---- */
.ab-panel {
  position: fixed; z-index: 95;
  display: flex; border-radius: 10px; overflow: visible;
  background: var(--card, #e9edf2); color: var(--fg, #3c4453);
  box-shadow: 0 24px 64px rgba(8, 12, 20, .38), 0 4px 16px rgba(8, 12, 20, .2);
  border: 1px solid var(--lt, #fff);
  min-width: 680px; min-height: 420px;
  border: 1px solid var(--line, #e3e7ed);
}
.ab-panel.max { border-radius: 0 }

/* ---- 左栏 ---- */
.ab-side { width: 232px; flex: none; display: flex; flex-direction: column; padding: 14px 12px;
  background: var(--card2, #eff2f6); border-right: 1px solid var(--sh, #c0c7d2);
  border-radius: 10px 0 0 10px; overflow: hidden; }
.ab-brand { display: flex; align-items: center; gap: 10px; padding: 2px 6px 12px; }
.ab-logo { width: 34px; height: 34px; border-radius: 10px; background: var(--acc, #4d6fa4);
  color: #fff; font-weight: 800; font-size: 16px; display: flex; align-items: center; justify-content: center; }
.ab-brand b { font-size: 14px; display: block; line-height: 1.2 }
.ab-brand span { font-size: 10.5px; color: var(--mut, #7f8a9b) }
.ab-new { border: 0; background: var(--acc, #4d6fa4); color: #f2f5f9; border-radius: 10px;
  padding: 9px 0; font-weight: 650; cursor: pointer; font-size: 13px; box-shadow: var(--up-sm, none); }
.ab-new.grp { margin-top: auto; background: transparent; color: var(--acc, #4d6fa4);
  border: 1px dashed var(--acc, #4d6fa4); font-size: 12px; padding: 7px 0; }
.ab-sec-t { font-size: 11px; color: var(--mut, #7f8a9b); font-weight: 700; letter-spacing: .5px;
  margin: 14px 4px 6px; }

/* ---- 分组 / 会话列表（保持原生滚动，隐藏系统滚动条） ---- */
.ab-grps { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 6px;
  scrollbar-width: none; }
.ab-grps::-webkit-scrollbar { width: 0; display: none }
.ab-grp-h { display: flex; align-items: center; gap: 6px; padding: 7px 6px; border-radius: 9px;
  cursor: pointer; font-size: 12.5px; user-select: none; }
.ab-grp-h:hover { background: var(--lt, #fff) }
.ab-grp-h.fold { opacity: .75 }
.ab-chev { font-size: 9px; color: var(--mut, #7f8a9b); flex: none }
.ab-grp-h b { flex: none }
.ab-cnt { font-size: 10.5px; color: var(--mut, #7f8a9b); background: var(--card, #e9edf2);
  border-radius: 7px; padding: 0 6px; }
.ab-grp-ops { margin-left: auto; display: flex; gap: 2px; opacity: 0; transition: .15s; }
.ab-grp-h:hover .ab-grp-ops { opacity: 1 }
.ab-grp-ops button { border: 0; background: transparent; color: var(--mut, #7f8a9b); cursor: pointer;
  font-size: 10.5px; padding: 2px 4px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; }
.ab-grp-ops button:hover { background: var(--card, #e9edf2); color: var(--fg, #3c4453) }
.ab-grp-ops button .ico { width: 12px; height: 12px; stroke: currentColor; fill: none; stroke-width: 1.9;
  stroke-linecap: round; stroke-linejoin: round; display: block }
.ab-sess { list-style: none; display: flex; flex-direction: column; gap: 3px; margin: 2px 0 4px 8px; }
.ab-sess li { position: relative; display: flex; align-items: center; gap: 7px; padding: 7px 8px;
  border-radius: 8px; cursor: pointer; font-size: 12px; color: var(--fg, #3c4453); transition: .15s; }
.ab-sess li:hover { background: var(--lt, #fff) }
.ab-sess li.on { background: var(--acc, #4d6fa4); color: #f2f5f9 }
.ab-sess .s-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--mut, #7f8a9b); flex: none }
.ab-sess li.on .s-dot { background: #fff }
.ab-sess .s-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.ab-sess .s-menu { opacity: 0; font-size: 13px; padding: 0 4px; border-radius: 5px; flex: none; }
.ab-sess li:hover .s-menu, .ab-sess li.on .s-menu { opacity: .8 }
.ab-sess .s-menu:hover { opacity: 1; background: rgba(127, 138, 155, .2) }
.ab-smenu { position: fixed; z-index: 400; min-width: 160px;
  background: var(--card, #e9edf2); border: 1px solid var(--lt, #fff); border-radius: 10px;
  box-shadow: 0 10px 30px rgba(8, 12, 20, .28); padding: 5px; display: flex; flex-direction: column; gap: 2px;
  max-height: calc(100vh - 16px); overflow-y: auto; scrollbar-width: none; }
.ab-smenu::-webkit-scrollbar { display: none }
.ab-smenu button { border: 0; background: transparent; color: var(--fg, #3c4453); font-size: 12px;
  padding: 6px 9px; border-radius: 7px; cursor: pointer; text-align: left; font-family: inherit; display: block; width: 100%; }
.ab-smenu button:hover { background: var(--lt, #fff) }
.ab-smenu button.dan { color: var(--err, #b3524d) }
.ab-smove { position: relative; padding: 6px 9px; font-size: 12px; display: flex; align-items: center;
  justify-content: space-between; cursor: default; border-radius: 7px; }
.ab-smove:hover { background: var(--lt, #fff) }
.ab-smove span { font-size: 9px; color: var(--mut, #7f8a9b) }
.ab-ssub { display: none; position: absolute; left: 100%; top: -4px; min-width: 120px;
  background: var(--card, #e9edf2); border: 1px solid var(--lt, #fff); border-radius: 9px;
  box-shadow: 0 10px 30px rgba(8, 12, 20, .28); padding: 4px; }
.ab-smove:hover .ab-ssub { display: block }
.ab-ssub button.on { color: var(--acc, #4d6fa4); font-weight: 650 }
.ab-gates { display: flex; flex-direction: column; gap: 4px; }
.ab-gates button { display: flex; align-items: center; justify-content: space-between; border: 0;
  background: transparent; color: var(--fg, #3c4453); font-size: 12.5px; padding: 7px 9px; border-radius: 9px;
  cursor: pointer; text-align: left; font-family: inherit; }
.ab-gates button:hover { background: var(--lt, #fff); color: var(--acc, #4d6fa4) }
.ab-gates span { color: var(--mut, #7f8a9b); font-size: 12px }

/* ---- 右栏 ---- */
.ab-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.ab-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;
  border-bottom: 1px solid var(--sh, #c0c7d2); cursor: move; user-select: none;
  touch-action: none; border-top-right-radius: 9px; }
.ab-head:active { cursor: grabbing }
.ab-hl { display: flex; align-items: center; gap: 9px; min-width: 0 }
.ab-status { width: 8px; height: 8px; border-radius: 50%; flex: none }
.ab-status.idle { background: var(--ok, #2f8f6d); box-shadow: 0 0 6px var(--ok, #2f8f6d) }
.ab-status.busy { background: var(--warn, #a5762c); animation: ab-blink 1s infinite }
@keyframes ab-blink { 50% { opacity: .35 } }
.ab-hl b { font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.ab-hsub { font-size: 11px; color: var(--mut, #7f8a9b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.ab-acts { display: flex; gap: 6px; flex: none }
.ab-ico { border: 0; background: transparent; color: var(--mut, #7f8a9b); cursor: pointer; font-size: 12px;
  padding: 4px 7px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; }
.ab-ico:hover { background: var(--lt, #fff); color: var(--fg, #3c4453) }
.ab-ico .ico { width: 15px; height: 15px; stroke: currentColor; fill: none; stroke-width: 1.9;
  stroke-linecap: round; stroke-linejoin: round; display: block }
.ab-sidebtn { display: none }   /* 会话抽屉按钮仅移动端显示 */
.ab-mx { display: none }        /* 最大化按钮仅桌面显示 */

/* ---- 右下角缩放手柄 ---- */
.ab-resize { position: absolute; right: 2px; bottom: 2px; width: 18px; height: 18px;
  cursor: nwse-resize; z-index: 20; touch-action: none; }
.ab-resize::after { content: ''; position: absolute; right: 3px; bottom: 3px; width: 8px; height: 8px;
  border-right: 2px solid var(--mut, #7f8a9b); border-bottom: 2px solid var(--mut, #7f8a9b);
  border-bottom-right-radius: 3px; opacity: .55; }
.ab-resize:hover::after { opacity: 1 }
.ab-resize.hide { display: none }

/* ---- 圆点大纲：固定 30px 占位列，在滚动容器左侧，不随消息滚动 ---- */
.ab-msgs-wrap { position: relative; flex: 1; min-height: 0; display: flex; }
.ab-msgs { flex: 1; min-height: 0; overflow-y: auto; position: relative;
  scrollbar-gutter: stable;   /* 右侧固定预留滚动条槽位（Chrome 8px / Firefox thin） */
  scrollbar-width: thin; }    /* 恢复可见滚动条 */
.ab-msgs::-webkit-scrollbar { width: 8px }
.ab-msgs::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, .18); border-radius: 4px }
.ab-msgs::-webkit-scrollbar-thumb:hover { background: rgba(0, 0, 0, .3) }
.ab-outline {
  position: relative; width: 30px; flex: none; align-self: stretch; z-index: 5;
  pointer-events: none; display: flex; align-items: center; padding: 0; }
.ab-rail { pointer-events: auto; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 8px; padding: 6px 0;
  /* 左侧留 15px、右侧留 8px：圆点右缘到消息内容 = 8px，与右侧滚动条槽宽严格相等 */
  margin-left: 15px; margin-right: 8px; width: 7px; }
.ab-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--acc, #4d6fa4); opacity: .35;
  flex: none; transition: .15s }
.ab-dot.on { opacity: 1; box-shadow: 0 0 5px var(--acc, #4d6fa4) }
.ab-opanel { pointer-events: auto; position: absolute; left: 100%; top: 50%; transform: translateY(-50%);
  width: 300px; max-height: 74%; overflow-y: auto; background: var(--card, #e9edf2);
  border: 1px solid var(--lt, #fff); border-radius: 12px; box-shadow: 0 10px 30px rgba(8, 12, 20, .25);
  padding: 10px; }
.ab-otitle { font-size: 11px; color: var(--mut, #7f8a9b); font-weight: 700; margin-bottom: 6px }
.ab-oitem { display: flex; align-items: center; gap: 8px; padding: 7px 9px; border-radius: 8px;
  cursor: pointer; font-size: 12px; }
.ab-oitem:hover { background: var(--lt, #fff) }
.ab-oitem.cur { background: var(--acc, #4d6fa4); color: #f2f5f9 }
.ab-olbl { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.ab-otime { font-size: 10px; opacity: .6; flex: none }

/* ---- 消息气泡：铺满可用宽度，左右各留 6px；你靠右 / AI 靠左 ---- */
.ab-flow { padding: 16px 18px 14px 18px; display: flex; flex-direction: column; gap: 12px; }
.ab-sys { align-self: center; font-size: 11.5px; color: var(--mut, #7f8a9b); background: var(--card2, #eff2f6);
  border: 1px solid var(--lt, #fff); border-radius: 999px; padding: 4px 12px; max-width: 90%;
  text-align: center; line-height: 1.6; }
.ab-msg { display: flex; }
.ab-msg.user { justify-content: flex-end }
.ab-bubble { max-width: 100%; padding: 10px 18px; border-radius: 8px; background: var(--card2, #eff2f6);
  box-shadow: var(--in-sm, none); }
.ab-msg.user .ab-bubble { background: var(--acc, #4d6fa4); color: #f2f5f9 }
.ab-who { font-size: 10.5px; opacity: .75; margin-bottom: 3px; font-weight: 650 }
.ab-atts { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 5px }
.ab-att { font-size: 11px; background: rgba(0, 0, 0, .06); padding: 2px 8px; border-radius: 7px;
  display: inline-flex; align-items: center; gap: 4px }
.ab-msg.user .ab-att { background: rgba(255, 255, 255, .2) }
.ab-att .ico { width: 12px; height: 12px; stroke: currentColor; fill: none; stroke-width: 1.9;
  stroke-linecap: round; stroke-linejoin: round; flex: none }
.ab-att em { font-style: normal; opacity: .7 }
.ab-txt { font-size: 13px; line-height: 1.75; white-space: pre-wrap; word-break: break-word }
/* ---- Markdown 渲染样式（.ab-md 为渲染后内容） ---- */
.ab-md { white-space: normal }
.ab-md p { margin: 4px 0 }
.ab-md h1, .ab-md h2, .ab-md h3 { margin: 9px 0 4px; line-height: 1.4; font-weight: 600 }
.ab-md h1 { font-size: 15px } .ab-md h2 { font-size: 14px } .ab-md h3 { font-size: 13px }
.ab-md ul, .ab-md ol { margin: 4px 0; padding-left: 20px }
.ab-md li { margin: 2px 0 }
.ab-md code { font-family: ui-monospace, Consolas, "Courier New", monospace; font-size: 12px;
  background: rgba(0, 0, 0, .06); padding: 1px 5px; border-radius: 4px }
html[data-theme="dark"] .ab-md code { background: rgba(255, 255, 255, .12) }
.ab-md pre { background: rgba(0, 0, 0, .06); border-radius: 8px; padding: 8px 10px;
  overflow-x: auto; margin: 6px 0 }
.ab-md pre code { background: none; padding: 0 }
html[data-theme="dark"] .ab-md pre { background: rgba(255, 255, 255, .1) }
.ab-md table { border-collapse: collapse; margin: 6px 0; font-size: 12px }
.ab-md th, .ab-md td { border: 1px solid var(--sh, #c0c7d2); padding: 4px 8px }
.ab-md th { background: rgba(0, 0, 0, .05); font-weight: 600 }
.ab-md blockquote { margin: 6px 0; padding: 2px 10px; border-left: 3px solid #4d6fa4;
  color: var(--mut, #7f8a9b); background: rgba(77, 111, 164, .06); border-radius: 0 6px 6px 0 }
.ab-md a { color: #4d6fa4; text-decoration: underline }
.ab-md hr { border: none; border-top: 1px dashed var(--sh, #c0c7d2); margin: 8px 0 }
/* ---- 限流排队重试提示条 ---- */
.ab-busy { display: flex; align-items: center; gap: 5px; margin-bottom: 7px; padding: 6px 9px;
  border: 1px dashed var(--sh, #c0c7d2); border-radius: 8px; font-size: 11.5px;
  color: var(--mut, #7f8a9b); background: rgba(255, 193, 7, .08) }
/* ---- 执行步骤（MonkeyCode 式任务分解：逐一执行并打勾） ---- */
.ab-steps { display: flex; flex-direction: column; gap: 4px; margin: 0 0 8px; padding-left: 2px }
.ab-step { display: flex; align-items: flex-start; gap: 7px; font-size: 12px; line-height: 1.6;
  color: var(--mut, #7f8a9b) }
.ab-step.running { color: #3b82f6 }
.ab-step.done { color: var(--mut, #7f8a9b); opacity: .85 }
.ab-step.error { color: #d6455a }
.ab-step-ic { width: 15px; flex: none; text-align: center; font-weight: 700 }
.ab-step.running .ab-step-ic { display: inline-block; animation: ab-spin-ic 1s linear infinite }
@keyframes ab-spin-ic { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }
/* ---- 联网搜索小窗（默认折叠一行，点击放大查看结果 / 阅读全文） ---- */
.ab-srch { margin-bottom: 7px; display: flex; flex-direction: column; gap: 5px }
.ab-srch-step { border: 1px solid var(--sh, #c0c7d2); border-radius: 8px; overflow: hidden;
  background: rgba(77, 111, 164, .06) }
.ab-srch-head { display: flex; align-items: center; gap: 6px; padding: 6px 9px;
  cursor: pointer; user-select: none }
.ab-srch-ic { font-size: 12px; flex: none; display: inline-flex }
.ab-srch-ic .ico { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 1.9;
  stroke-linecap: round; stroke-linejoin: round; display: block }
.ab-srch-q { font-size: 12px; font-weight: 600; color: var(--acc, #3c5a8c);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1 }
.ab-srch-st { font-size: 11px; color: var(--mut, #7f8a9b); flex: none; display: flex; align-items: center; gap: 4px }
.ab-srch-st.run { color: var(--acc, #4d6fa4) }
.ab-srch-st.err { color: #d9534f }
.ab-srch-body { border-top: 1px dashed var(--sh, #c0c7d2); padding: 7px 9px; display: flex;
  flex-direction: column; gap: 7px; max-height: 300px; overflow-y: auto }
.ab-srch-res { border: 1px solid var(--sh, #c0c7d2); border-radius: 7px; padding: 6px 8px;
  background: var(--card2, #f7f8fa) }
html[data-theme="dark"] .ab-srch-res { background: rgba(255, 255, 255, .04) }
.ab-srch-res-t { display: flex; align-items: center; gap: 8px; justify-content: space-between }
.ab-srch-res-t a { font-size: 12.5px; font-weight: 600; color: var(--acc, #3c5a8c);
  text-decoration: none; word-break: break-all }
.ab-srch-res-t a:hover { text-decoration: underline }
.ab-srch-res-s { font-size: 11.5px; color: var(--mut, #7f8a9b); line-height: 1.55; margin-top: 3px }
.ab-srch-res-body { margin-top: 6px; border-top: 1px dashed var(--sh, #c0c7d2); padding-top: 6px }
.ab-srch-res-body pre { margin: 0; font-size: 11.5px; line-height: 1.6; white-space: pre-wrap;
  word-break: break-word; color: inherit; background: none }
.ab-mini { font-size: 11px; padding: 2px 8px; border-radius: 6px; border: 1px solid var(--sh, #c0c7d2);
  background: transparent; color: var(--acc, #3c5a8c); cursor: pointer; flex: none }
.ab-mini:hover { background: rgba(77, 111, 164, .12) }
/* ---- 思考过程折叠块（MonkeyCode 同款：默认收起，点击展开） ---- */
.ab-think { border: 1px solid var(--sh, #c0c7d2); border-radius: 8px;
  background: rgba(127, 138, 155, .1); margin-bottom: 7px; overflow: hidden; cursor: pointer }
.ab-think-head { display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 5px 9px; font-size: 11.5px; color: var(--mut, #7f8a9b); user-select: none }
.ab-think.on .ab-think-head { border-bottom: 1px solid var(--sh, #c0c7d2) }
.ab-think-arrow { font-size: 9px; opacity: .7 }
.ab-think-body { margin: 0; padding: 8px 10px; font-size: 12px; line-height: 1.7; color: var(--mut, #7f8a9b);
  white-space: pre-wrap; word-break: break-word; font-family: inherit; max-height: 220px; overflow-y: auto;
  scrollbar-width: none; }
.ab-think-body::-webkit-scrollbar { display: none }
.ab-msg.user .ab-think { display: none }   /* 思考块仅在 AI 消息中出现 */
.ab-busy { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--mut, #7f8a9b) }
.ab-spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--mut, #7f8a9b);
  border-top-color: transparent; animation: ab-rot .7s linear infinite; display: inline-block }
@keyframes ab-rot { to { transform: rotate(360deg) } }

/* ---- 写操作卡片 ---- */
.ab-pends { margin-top: 9px; display: flex; flex-direction: column; gap: 7px; }
.ab-pend { border: 1px solid var(--sh, #c0c7d2); border-radius: 9px; padding: 8px 10px; background: #fff; }
.ab-msg.user .ab-pend { background: #fff; color: var(--fg, #3c4453); border-color: rgba(255,255,255,.3) }
.ab-pend-head { display: flex; align-items: center; gap: 8px; font-size: 12px; flex-wrap: wrap }
.ab-badge { background: var(--warn, #a5762c); color: #fff; font-size: 10px; font-weight: 700;
  padding: 1px 7px; border-radius: 5px; }
.ab-pend-args { font-size: 11px; margin: 4px 0 6px; color: var(--mut, #7f8a9b); word-break: break-all }
.ab-pend-ops { display: flex; align-items: center; gap: 8px }
.ab-mini { border: 1px solid var(--sh, #c0c7d2); background: var(--card2, #eff2f6); border-radius: 7px;
  padding: 3px 10px; font-size: 11.5px; cursor: pointer; font-family: inherit; color: var(--fg, #3c4453) }
.ab-mini.pri { background: var(--ok, #2f8f6d); color: #fff; border: 0 }
.ab-rs { font-size: 11.5px; font-weight: 650 }
.ab-rs.ok { color: var(--ok, #2f8f6d) }
.ab-mut { font-size: 11.5px; color: var(--mut, #7f8a9b) }

/* ---- 输入区 ---- */
.ab-composer { border-top: 1px solid var(--sh, #c0c7d2); padding: 10px 12px 12px;
  border-bottom-right-radius: 17px; }
/* 思考中 + 发送队列（输入框上方，MonkeyCode 同款） */
.ab-aiq { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.ab-aiq-working { display: flex; align-items: center; gap: 8px; background: rgba(77, 111, 164, .09);
  border: 1px solid rgba(77, 111, 164, .28); border-radius: 9px; padding: 6px 10px; font-size: 12px; }
.ab-aiq-spin { width: 11px; height: 11px; border-radius: 50%; border: 2px solid var(--acc, #4d6fa4);
  border-top-color: transparent; animation: ab-rot .7s linear infinite; flex: none }
.ab-aiq-txt { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--mut, #7f8a9b); font-size: 12px }
.ab-aiq-stop { border: 0; background: rgba(255, 82, 82, .12); color: #d64f4f; border-radius: 7px;
  padding: 4px 11px; font-size: 12px; cursor: pointer; flex: none; font-weight: 650; font-family: inherit }
.ab-aiq-stop:hover { background: rgba(255, 82, 82, .22) }
.ab-aiq-q { border: 1px solid var(--sh, #c0c7d2); border-radius: 9px; background: var(--card2, #eff2f6);
  overflow: hidden }
.ab-aiq-qhead { display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 6px 10px; cursor: pointer; font-size: 12px; color: var(--mut, #7f8a9b); font-weight: 650 }
.ab-aiq-qhead:hover { background: rgba(127, 138, 155, .08) }
.ab-aiq-qhead em { font-style: normal; font-weight: 400; opacity: .75; margin-left: 4px; font-size: 11px }
.ab-aiq-qops button { border: 0; background: transparent; color: var(--mut, #7f8a9b); cursor: pointer;
  padding: 2px 9px; border-radius: 6px; font-size: 11.5px; font-family: inherit }
.ab-aiq-qops button:hover { background: rgba(255, 82, 82, .12); color: #d64f4f }
.ab-aiq-qlist { padding: 4px 10px 10px; display: flex; flex-direction: column; gap: 8px }
.ab-aiq-item { display: flex; gap: 8px; align-items: flex-start }
.ab-aiq-item textarea { flex: 1; resize: vertical; min-height: 44px; max-height: 120px;
  border: 1px solid var(--sh, #c0c7d2); border-radius: 8px; padding: 7px 9px; font-size: 12.5px;
  font-family: inherit; line-height: 1.6; background: var(--lt, #fff); color: var(--fg, #3c4453); outline: none }
.ab-aiq-item textarea:focus { border-color: var(--acc, #4d6fa4) }
.ab-aiq-itemops { display: flex; flex-direction: column; align-items: center; gap: 5px }
.ab-aiq-no { font-size: 10px; color: var(--mut, #7f8a9b); font-weight: 700 }
.ab-aiq-itemops button { border: 0; background: rgba(255, 82, 82, .1); color: #d64f4f; width: 22px; height: 22px;
  border-radius: 6px; cursor: pointer; font-size: 11px; line-height: 1 }
.ab-aiq-itemops button:hover { background: rgba(255, 82, 82, .22) }
.ab-chiprow { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px }
.ab-chip { display: flex; align-items: center; gap: 6px; background: var(--card2, #eff2f6);
  border: 1px solid var(--lt, #fff); border-radius: 9px; padding: 4px 7px; font-size: 11.5px; }
.ab-chip img { width: 22px; height: 22px; object-fit: cover; border-radius: 5px }
.ab-chip em { font-style: normal; color: var(--mut, #7f8a9b); font-size: 10.5px }
.ab-chip button { border: 0; background: transparent; color: var(--mut, #7f8a9b); cursor: pointer; font-size: 10px }
.ab-composer textarea { width: 100%; resize: vertical; min-height: 60px; max-height: 260px;
  font-family: inherit; font-size: 13px; line-height: 1.6;
  border: 1px solid var(--sh, #c0c7d2); border-radius: 11px; padding: 9px 12px; outline: none;
  background: var(--lt, #fff); color: var(--fg, #3c4453); box-shadow: var(--in-sm, none); }
.ab-composer textarea:focus { border-color: var(--acc, #4d6fa4) }
/* 顶部拖拽把手：输入框上沿都可用于调高（含文字框内上边缘 8px） */
.ab-vgrip { height: 9px; margin: 1px 0 0; cursor: ns-resize; display: flex; align-items: center;
  justify-content: center; user-select: none; touch-action: none; border-radius: 4px }
.ab-vgrip::before { content: ''; width: 36px; height: 3px; border-radius: 2px;
  background: var(--sh, #c0c7d2); opacity: .5; transition: .16s }
.ab-vgrip:hover::before, .ab-vgrip:active::before { background: var(--acc, #4d6fa4); opacity: .85 }
body.ab-vdrag { user-select: none; cursor: ns-resize }
.ab-toolbar { display: flex; align-items: center; gap: 7px; margin-top: 8px; position: relative }
.ab-tbtn { border: 1px solid var(--sh, #c0c7d2); background: var(--card2, #eff2f6); border-radius: 8px;
  padding: 5px 10px; font-size: 12px; cursor: pointer; font-family: inherit; color: var(--fg, #3c4453);
  display: inline-flex; align-items: center; gap: 4px }
.ab-tbtn .ico { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 1.9;
  stroke-linecap: round; stroke-linejoin: round; flex: none }
.ab-tbtn:hover, .ab-tbtn.on { border-color: var(--acc, #4d6fa4); color: var(--acc, #4d6fa4) }
.ab-skillwrap { position: relative; z-index: 30 }
.ab-thinkwrap { position: relative; z-index: 30 }
.ab-skillmenu, .ab-thinkmenu { position: absolute; bottom: 34px; left: 0; width: 270px;
  background: var(--card, #e9edf2); border: 1px solid var(--lt, #fff); border-radius: 11px;
  box-shadow: 0 10px 30px rgba(8, 12, 20, .25); padding: 7px; display: flex; flex-direction: column;
  gap: 3px; z-index: 90; }
.ab-thinkmenu { left: auto; right: 0; width: 210px }
.ab-sm-title { font-size: 11px; color: var(--mut, #7f8a9b); font-weight: 700; padding: 2px 4px 5px }
.ab-skill { padding: 7px 9px; border-radius: 8px; cursor: pointer; border: 0; background: transparent;
  font-family: inherit; text-align: left; display: block; width: 100%; }
.ab-skill:hover { background: var(--lt, #fff) }
.ab-skill.on { background: var(--acc, #4d6fa4); color: #f2f5f9 }
.ab-skill b { font-size: 12.5px; display: block; margin-bottom: 1px }
.ab-skill span { font-size: 11px; color: var(--mut, #7f8a9b); line-height: 1.5; display: block }
.ab-skill.on span { color: rgba(255, 255, 255, .8) }
.ab-sm-none { font-size: 11.5px; color: var(--mut, #7f8a9b); padding: 8px 4px; }
.ab-sm-foot { border-top: 1px solid var(--sh, #c0c7d2); padding-top: 6px; margin-top: 2px }
.ab-sm-foot .ab-tbtn { width: 100%; font-size: 11.5px }
.ab-skillchips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.ab-skchip em { font-style: normal; color: var(--acc, #4d6fa4); font-size: 10px; font-weight: 700 }
.ab-skchip button { border: 0; background: transparent; color: var(--mut, #7f8a9b); cursor: pointer; font-size: 10px }
.ab-sp { flex: 1 }
/* 模型下拉在输入框底部：改为向上弹出，宽度按最长内容自动撑开（名称不被截断） */
.ab-sel :deep(.ssl) { position: relative; z-index: 30 }
.ab-sel :deep(.ssl-panel) { top: auto; bottom: calc(100% + 6px); z-index: 90; position: absolute;
  left: auto; right: 0; width: max-content; min-width: 100%;
  max-width: min(460px, 72vw); /* 极端长名时限制，避免超出窗口 */ }
.ab-sel :deep(*) { font-size: 12px !important }
.ab-send { border: 0; background: var(--acc, #4d6fa4); color: #f2f5f9; border-radius: 9px;
  padding: 6px 18px; font-size: 12.5px; font-weight: 650; cursor: pointer; font-family: inherit; }
.ab-send:disabled { opacity: .55; cursor: default }

/* ---- AI 球 ---- */
.ab-ball { position: fixed; right: 22px; bottom: 22px; z-index: 100; width: 58px; height: 58px;
  border-radius: 50%; border: 0; cursor: grab; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--acc, #4d6fa4), #3c5a8c); color: #fff;
  box-shadow: 0 8px 24px rgba(40, 70, 120, .45); transition: transform .2s; touch-action: none; }
.ab-ball:hover { transform: scale(1.08) }
.ab-ball:active { cursor: grabbing }
.ab-ball.drag { transition: none; transform: scale(1.05); cursor: grabbing }
.ab-ball.on { transform: scale(1) }
.ab-ball-ico { font-size: 15px; font-weight: 800; letter-spacing: .5px;
  color: #6fe39a; transition: color .2s; }
/* 执行中：AI 标记变黄（无红点）；空闲时保持绿色 */
.ab-ball.busy .ab-ball-ico { color: #ffd34d }
@keyframes ab-blink { 50% { opacity: .35 } }
.ab-ring { position: absolute; inset: -4px; border-radius: 50%; border: 2px solid var(--acc, #4d6fa4);
  opacity: .5; animation: ab-ring 2.4s ease-out infinite; pointer-events: none }
@keyframes ab-ring {
  0% { transform: scale(.92); opacity: .55 }
  70% { transform: scale(1.18); opacity: 0 }
  100% { transform: scale(1.18); opacity: 0 }
}

/* ---- 消息区自绘滚动条：贴面板右缘，气泡右移让位，不遮挡 ---- */
.ab-scbar { position: absolute; right: 2px; top: 12px; bottom: 12px; width: 8px; pointer-events: none;
  background: #cdd5e0; border-radius: 4px; z-index: 45; opacity: .95;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .5) }
html[data-theme="dark"] .ab-scbar { background: #39414e }
.ab-thumb { position: absolute; left: 1.5px; right: 1.5px; border-radius: 4px;
  background: var(--acc, #002fa7); box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .45); will-change: transform }
html[data-theme="dark"] .ab-thumb { background: var(--acc, #6c8fdb) }

/* ---- 过渡 / toast ---- */
.fade-enter-active, .fade-leave-active { transition: opacity .15s }
.fade-enter-from, .fade-leave-to { opacity: 0 }
.pop-enter-active, .pop-leave-active { transition: opacity .18s, transform .18s }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(14px) scale(.97) }
.ab-toast { position: fixed; left: 50%; bottom: 36px; transform: translateX(-50%) translateY(14px);
  z-index: 110; background: rgba(20, 26, 38, .9); color: #fff; font-size: 12.5px; padding: 9px 16px;
  border-radius: 10px; opacity: 0; pointer-events: none; transition: .2s; white-space: nowrap; }
.ab-toast.show { opacity: 1; transform: translateX(-50%) translateY(0) }

/* ---- 自定义输入弹窗（分组/会话命名） ---- */
.ab-dlgmask { position: fixed; inset: 0; background: rgba(8, 12, 20, .35);
  display: flex; align-items: center; justify-content: center; z-index: 300 }
.ab-dlg { width: 300px; max-width: calc(100vw - 48px); background: var(--card, #e9edf2);
  border: 1px solid var(--lt, #fff); border-radius: 10px; box-shadow: 0 18px 50px rgba(8, 12, 20, .35);
  padding: 16px 16px 14px; }
.ab-dlg-title { font-size: 14px; font-weight: 700; margin-bottom: 12px }
.ab-dlg-input { width: 100%; box-sizing: border-box; border: 1px solid var(--sh, #c0c7d2); border-radius: 9px;
  padding: 8px 11px; font-size: 13px; background: var(--lt, #fff); color: var(--fg, #3c4453);
  outline: none; font-family: inherit }
.ab-dlg-input:focus { border-color: var(--acc, #4d6fa4) }
.ab-dlg-ops { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px }
.ab-dlg-ops button { border: 0; border-radius: 8px; padding: 6px 16px; font-size: 12.5px; cursor: pointer; font-family: inherit }
.ab-dlg-ops .c { background: transparent; color: var(--mut, #7f8a9b) }
.ab-dlg-ops .c:hover { background: rgba(127, 138, 155, .12) }
.ab-dlg-ops .ok { background: var(--acc, #4d6fa4); color: #f2f5f9; font-weight: 650 }
.ab-dlg-ops .ok.dan { background: var(--err, #b3524d) }
.ab-dlg-msg { font-size: 13px; line-height: 1.7; color: var(--fg, #3c4453); word-break: break-word }

/* ══════════ 移动端适配：面板全屏 + 会话列表面板 + 简洁工具条 ══════════ */
@media (max-width: 720px) {
  /* AI 面板：全屏展示（覆盖 JS 内联位置/尺寸） */
  .ab-panel {
    left: 0 !important; top: 0 !important;
    width: 100vw !important; height: 100dvh !important;
    min-width: 0; min-height: 0; max-width: none; max-height: none;
    border-radius: 0;
  }
  /* 会话列表：左侧抽屉（☰ 打开） */
  .ab-sidebtn, .ab-mx { display: none }
  .ab-sidebtn { display: inline-flex }
  .ab-side {
    position: absolute; left: 0; top: 0; bottom: 0; z-index: 30;
    width: min(78vw, 280px);
    transform: translateX(-100%);
    transition: transform .22s ease;
    box-shadow: 14px 0 34px rgba(10, 14, 22, .18);
  }
  .ab-side.open { transform: translateX(0) }
  /* 技术/思考弹出菜单退出高层级：抽屉打开时被其盖住，不再浮在侧边栏上 */
  .ab-skillwrap, .ab-thinkwrap { z-index: auto }
  /* 抽屉遮罩：盖住正文（含头部按钮），点空白关闭；层级低于抽屉本体 */
  .ab-side-mask { display: block; position: absolute; inset: 0; z-index: 25; background: rgba(8, 12, 20, .28) }
  /* 不需拖动 / 缩放 / 最大化 */
  .ab-resize { display: none }
  .ab-head, .ab-head:active { cursor: default }
  /* 圆点大纲占位列在手机上不适用，隐藏以让消息全宽 */
  .ab-outline { display: none }
  .ab-flow { padding: 12px 12px 10px }
  /* 底部工具条：换行排列，供应商/模型各占半行 */
  .ab-toolbar { flex-wrap: wrap; gap: 6px }
  .ab-toolbar .ab-sel { width: auto !important; flex: 1 1 42% }
  .ab-send { flex: none }
  .ab-smenu { max-width: calc(100vw - 12px) }
  .ab-opanel { left: 4px; right: 4px; top: 100%; width: auto; transform: none; max-height: 46vh }
  /* AI 球避开底部导航；面板打开时隐藏（顶部有 ✕ 关闭） */
  .ab-ball { right: 16px; bottom: calc(86px + env(safe-area-inset-bottom)) }
  .ab-ball.on { display: none }
  .ab-toast { bottom: calc(90px + env(safe-area-inset-bottom)) }
}
</style>
