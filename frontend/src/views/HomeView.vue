<template>
  <section class="page">
    <div class="kpis">
      <div class="kpi blue"><div class="k">我的检查记录</div><div class="v">{{ kpi.report }}</div><div class="d">仅统计当前账号可见</div></div>
      <div class="kpi green"><div class="k">用药记录</div><div class="v">{{ kpi.med }}</div><div class="d">仅统计当前账号可见</div></div>
      <div class="kpi amber"><div class="k">文件存储</div><div class="v">{{ kpi.files }}</div><div class="d">仅统计当前账号可见</div></div>
      <div class="kpi red"><div class="k">报告模板</div><div class="v">{{ kpi.tpl }}</div><div class="d">系统公共模板库</div></div>
    </div>

    <template v-if="interests.length || groups.length">
      <div class="card ti-card-wrap">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <button class="ti-title" @click="favDetail = true" title="查看全部关注检查项">
            <h3 style="font-size:15px;font-weight:650;margin:0">关注检查项</h3>
            <span class="ti-all">全部 {{ favItems.length }} ›</span>
          </button>
          <span class="sub" style="font-size:12px;color:var(--mut)">在「检查报告 → 查看报告」里点 ☆关注 / ☆加入组合 添加；每张卡可切换时间区间</span>
          <span class="ti-hint" v-if="favItems.length > 1">左右滑动切换 ▸</span>
        </div>
        <div class="ti-grid">
          <div class="ti-card" v-for="f in favItems" :key="favKey(f)">
            <template v-if="f.kind === 'g'">
              <div class="ti-head">
                <div>
                  <b class="ti-name g">{{ f.g.doc_name }} <span class="badge info">{{ f.g.series.length }} 项组合</span></b>
                  <div class="ti-now">组内各检查项历史走势对照</div>
                </div>
                <div class="tabs ti-tabs">
                  <button :class="{ on: f.g.scope === 'all' }" @click="switchGrp(f.g, 'all')">全年</button>
                  <button :class="{ on: f.g.scope === 'year' }" @click="switchGrp(f.g, 'year')">今年</button>
                  <button :class="{ on: f.g.scope === 'quarter' }" @click="switchGrp(f.g, 'quarter')">季度</button>
                  <button :class="{ on: f.g.scope === 'recent3' }" @click="switchGrp(f.g, 'recent3')">最近三次</button>
                </div>
              </div>
              <div v-if="f.g.loading" class="ti-empty">加载中…</div>
              <div v-else-if="hasGroupData(f.g)">
                <TrendChart :series="chartSeries(f.g)" :height="230" />
              </div>
              <div v-else class="ti-empty">该区间内暂无历史数据</div>
              <div class="ti-foot">
                <span class="t-mut" style="font-size:11.5px">组内共 {{ groupCount(f.g) }} 个数据点</span>
                <button class="mini" @click="ungroupAll(f.g)" title="取消该报告全部组合关注">取消本组关注 ✕</button>
              </div>
            </template>
            <template v-else>
              <div class="ti-head">
                <div>
                  <b class="ti-name">{{ f.it.name }}</b>
                  <div class="ti-now">
                    最新
                    <span :class="'rs ' + (f.it.latest_result || '')">
                      {{ f.it.latest_value ?? '—' }}{{ f.it.latest_result === 'high' ? ' ↑' : (f.it.latest_result === 'low' ? ' ↓' : '') }}
                    </span>
                    <em v-if="f.it.unit" style="font-style:normal;font-size:11px;opacity:.7">{{ f.it.unit }}</em>
                    <span class="t-mut" style="font-size:11px"> · {{ f.it.latest_checked_at || '暂无' }}</span>
                  </div>
                </div>
                <div class="tabs ti-tabs">
                  <button :class="{ on: f.it.scope === 'all' }" @click="switchOne(f.it, 'all')">全年</button>
                  <button :class="{ on: f.it.scope === 'year' }" @click="switchOne(f.it, 'year')">今年</button>
                  <button :class="{ on: f.it.scope === 'quarter' }" @click="switchOne(f.it, 'quarter')">季度</button>
                  <button :class="{ on: f.it.scope === 'recent3' }" @click="switchOne(f.it, 'recent3')">最近三次</button>
                </div>
              </div>
              <div v-if="f.it.loading" class="ti-empty">加载中…</div>
              <div v-else-if="f.it.points && f.it.points.length">
                <TrendChart :points="f.it.points" :unit="f.it.unit || ''" :height="230" />
              </div>
              <div v-else class="ti-empty">该区间内暂无历史数据</div>
              <div class="ti-foot">
                <span class="t-mut" style="font-size:11.5px">共 {{ f.it.points?.length || 0 }} 个数据点</span>
                <button class="mini" @click="unfollow(f.it)" title="取消关注">取消关注 ✕</button>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 关注检查项详情页：全部卡片上下结构展示 -->
      <div class="fav-detail" v-if="favDetail">
        <div class="fav-bar">
          <button class="fav-back" @click="favDetail = false">‹ 返回</button>
          <b class="fav-title">关注检查项 <span class="t-mut">{{ favItems.length }}</span></b>
        </div>
        <div class="fav-list">
          <div class="ti-card" v-for="f in favItems" :key="favKey(f)">
            <template v-if="f.kind === 'g'">
              <div class="ti-head">
                <div>
                  <b class="ti-name g">{{ f.g.doc_name }} <span class="badge info">{{ f.g.series.length }} 项组合</span></b>
                  <div class="ti-now">组内各检查项历史走势对照</div>
                </div>
                <div class="tabs ti-tabs">
                  <button :class="{ on: f.g.scope === 'all' }" @click="switchGrp(f.g, 'all')">全年</button>
                  <button :class="{ on: f.g.scope === 'year' }" @click="switchGrp(f.g, 'year')">今年</button>
                  <button :class="{ on: f.g.scope === 'quarter' }" @click="switchGrp(f.g, 'quarter')">季度</button>
                  <button :class="{ on: f.g.scope === 'recent3' }" @click="switchGrp(f.g, 'recent3')">最近三次</button>
                </div>
              </div>
              <div v-if="f.g.loading" class="ti-empty">加载中…</div>
              <div v-else-if="hasGroupData(f.g)">
                <TrendChart :series="chartSeries(f.g)" :height="230" />
              </div>
              <div v-else class="ti-empty">该区间内暂无历史数据</div>
              <div class="ti-foot">
                <span class="t-mut" style="font-size:11.5px">组内共 {{ groupCount(f.g) }} 个数据点</span>
                <button class="mini" @click="ungroupAll(f.g)" title="取消该报告全部组合关注">取消本组关注 ✕</button>
              </div>
            </template>
            <template v-else>
              <div class="ti-head">
                <div>
                  <b class="ti-name">{{ f.it.name }}</b>
                  <div class="ti-now">
                    最新
                    <span :class="'rs ' + (f.it.latest_result || '')">
                      {{ f.it.latest_value ?? '—' }}{{ f.it.latest_result === 'high' ? ' ↑' : (f.it.latest_result === 'low' ? ' ↓' : '') }}
                    </span>
                    <em v-if="f.it.unit" style="font-style:normal;font-size:11px;opacity:.7">{{ f.it.unit }}</em>
                    <span class="t-mut" style="font-size:11px"> · {{ f.it.latest_checked_at || '暂无' }}</span>
                  </div>
                </div>
                <div class="tabs ti-tabs">
                  <button :class="{ on: f.it.scope === 'all' }" @click="switchOne(f.it, 'all')">全年</button>
                  <button :class="{ on: f.it.scope === 'year' }" @click="switchOne(f.it, 'year')">今年</button>
                  <button :class="{ on: f.it.scope === 'quarter' }" @click="switchOne(f.it, 'quarter')">季度</button>
                  <button :class="{ on: f.it.scope === 'recent3' }" @click="switchOne(f.it, 'recent3')">最近三次</button>
                </div>
              </div>
              <div v-if="f.it.loading" class="ti-empty">加载中…</div>
              <div v-else-if="f.it.points && f.it.points.length">
                <TrendChart :points="f.it.points" :unit="f.it.unit || ''" :height="230" />
              </div>
              <div v-else class="ti-empty">该区间内暂无历史数据</div>
              <div class="ti-foot">
                <span class="t-mut" style="font-size:11.5px">共 {{ f.it.points?.length || 0 }} 个数据点</span>
                <button class="mini" @click="unfollow(f.it)" title="取消关注">取消关注 ✕</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </template>

    <div class="card" style="padding:18px">
      <h3 style="font-size:15px;font-weight:650;margin-bottom:4px">最新报告</h3>
      <div class="sub" style="font-size:12px;color:var(--mut);margin-bottom:14px">按检查日期倒序（当前账号可见），点卡片或「查看」直接在首页看报告明细</div>
      <div class="lp-grid">
        <div class="lp-card" v-for="(d, i) in latestDocs" :key="d.id">
          <div class="lp-media" @click="viewImg(d)">
            <img v-if="d.cover" :src="'/static/' + d.cover" :alt="d.name" loading="lazy" title="点击放大查看报告图片">
            <div v-else class="lp-ph">
              <span class="lp-ph-cat">{{ d.category || '检查报告' }}</span>
              <span class="lp-ph-idx">{{ String(i + 1).padStart(2, '0') }}</span>
            </div>
          </div>
          <div class="lp-body">
            <div class="lp-name">
              <b class="lp-t"><span class="mq-track"><span class="mq-item">{{ d.name }}</span><span class="mq-item" aria-hidden="true">{{ d.name }}</span></span></b>
              <span v-if="d.abnormal" class="badge danger">异常 {{ d.abnormal }}</span>
            </div>
            <div class="lp-meta">
              <span class="t-num">{{ d.checked_at || '—' }}</span>
              <template v-if="d.addr"> · {{ d.addr }}</template>
              <template v-if="d.doctor"> · {{ d.doctor }}</template>
            </div>
            <div class="lp-stat">
              <span class="t-num">{{ d.item_count ?? 0 }} 项</span>
              <template v-if="d.abnormal"> · 异常 <span class="rs abnormal">{{ d.abnormal }}</span></template>
            </div>
            <div class="lp-ops">
              <button class="mini pri" @click="openDocView(d)">查看</button>
            </div>
          </div>
        </div>
        <div v-if="!latestDocs.length" class="lp-empty">暂无报告（可到「检查报告」页录入）</div>
      </div>
    </div>

    <!-- 最新报告：点击图片放大查看（同一检查记录全部图片串组，左右滑动 / 箭头 / 缩略图切换） -->
    <div class="modal-mask" :class="{ show: imgMdl }" @click.self="imgMdl = false">
      <div class="img-viewer" v-if="imgMdl && imgList.length">
        <PinchZoom :key="imgIdx" :src="imgList[imgIdx].src" :alt="imgList[imgIdx].name" @close="imgMdl = false" @swipe="switchImg" />
        <div class="img-cap" v-if="imgList[imgIdx].name">{{ imgList[imgIdx].name }}</div>
        <div class="img-counter" v-if="imgList.length > 1">{{ imgIdx + 1 }} / {{ imgList.length }}</div>
        <button v-if="imgList.length > 1" class="img-nav prev" @click="switchImg(-1)" title="上一张">‹</button>
        <button v-if="imgList.length > 1" class="img-nav next" @click="switchImg(1)" title="下一张">›</button>
        <div class="img-thumbs" v-if="imgList.length > 1">
          <img v-for="(im, i) in imgList" :key="i" :src="im.src" :class="{ on: i === imgIdx }"
            :alt="im.name || ('图片 ' + (i + 1))" :title="im.name || ('图片 ' + (i + 1))"
            @click="imgIdx = i" loading="lazy">
        </div>
        <button class="img-close" @click="imgMdl = false"><span style="font-size:15px">✕</span></button>
      </div>
    </div>

    <!-- 首页查看报告弹窗 -->
    <div class="modal-mask show" v-if="viewDoc" @click.self="closeDocView">
      <div class="modal wide">
        <h3>{{ viewDoc.name }}
          <span v-if="viewDoc.abnormal" class="badge danger" style="margin-left:8px;vertical-align:middle">异常 {{ viewDoc.abnormal }} 项</span>
        </h3>
        <div class="msub">{{ viewDoc.checked_at || '—' }} · {{ viewDoc.category || '未分类' }} · {{ viewDoc.addr || '—' }}{{ viewDoc.doctor ? ' · ' + viewDoc.doctor : '' }} · 共 {{ viewDocItems.length }} 项</div>
        <div style="margin:6px 0 10px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <div class="tabs">
            <button :class="{ on: viewTab === 'all' }" @click="viewTab = 'all'">所有项</button>
            <button :class="{ on: viewTab === 'abn' }" @click="viewTab = 'abn'">异常项（{{ viewAbnItems.length }}）</button>
          </div>
          <label class="grp-switch" :class="{ on: groupMode }" title="勾选后，本报告内关注的检查项会在首页合并到一张曲线图对照显示">
            <input type="checkbox" v-model="groupMode"><i></i><span>组合到本报告一张图</span>
          </label>
        </div>
        <div class="tbl-wrap">
          <table>
            <thead>
              <tr><th>检验项目</th><th>结果</th><th>单位</th><th>参考范围</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="(it, i) in shownItems" :key="i">
                <td>{{ it.name }}</td>
                <td class="t-num">{{ it.value ?? '—' }}</td>
                <td>{{ it.unit || '—' }}</td>
                <td>{{ it.ref_range || '—' }}</td>
                <td><span :class="'rs ' + (it.result || 'blank')">{{ statusText(it.result) }}</span></td>
                <td><div class="ops">
                  <button class="mini" @click="openTrendH(it.name)" title="查看历史趋势曲线">趋势</button>
                  <button class="mini star" :class="{ on: onInterest(it.name) }" @click="toggleInterestH(it.name)" :title="(groupMode ? (onInterest(it.name) ? '取消本报告组合关注' : '组合到本报告一张图（首页对照显示）') : (onInterest(it.name) ? '取消关注（首页展示）' : '关注该检查项（首页展示）'))">
                    {{ interestLabel(it.name) }}
                  </button>
                </div></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="modal-ft"><button @click="closeDocView">关闭</button></div>
      </div>
    </div>

    <!-- 趋势小弹窗 -->
    <div class="modal-mask show" v-if="trendMdl" @click.self="trendMdl = false">
      <div class="modal">
        <h3>「{{ trendName }}」历史趋势</h3>
        <div class="msub">切换时间区间查看；关注后持续在首页展示</div>
        <div class="tabs" style="margin:4px 0 12px">
          <button :class="{ on: trendScope === 'all' }" @click="setScopeH('all')">全年</button>
          <button :class="{ on: trendScope === 'year' }" @click="setScopeH('year')">今年</button>
          <button :class="{ on: trendScope === 'quarter' }" @click="setScopeH('quarter')">季度</button>
          <button :class="{ on: trendScope === 'recent3' }" @click="setScopeH('recent3')">最近三次</button>
        </div>
        <div v-if="trendLoading" class="empty">加载中…</div>
        <TrendChart v-else-if="trendData && (trendData.points || []).length" :points="trendData.points" :unit="trendData.unit || ''" :height="220" />
        <div v-else class="empty">该区间暂无数据</div>
        <div class="modal-ft">
          <button class="mini star" :class="{ on: onInterest(trendName) }" @click="toggleInterestH(trendName)" style="margin-right:auto">{{ interestLabel(trendName) }}</button>
          <button @click="trendMdl = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 二次确认弹窗 -->
    <div class="modal-mask" :class="{ show: askMdl }" @click.self="askMdl = false">
      <div class="modal" style="width:340px;text-align:center">
        <h3 style="margin-bottom:14px">确定{{ askDanger ? '取消关注' : '' }}？</h3>
        <div class="msub" style="margin-bottom:4px;white-space:normal">{{ askMsg }}</div>
        <div class="modal-ft" style="justify-content:center;gap:12px">
          <button style="min-width:96px" @click="askMdl = false">再想想</button>
          <button class="pri" style="min-width:96px" @click="askDo">确认取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick, onUnmounted } from 'vue'
import { reportApi, medApi, fileApi, tplApi } from '../api'
import TrendChart from '../components/TrendChart.vue'
import PinchZoom from '../components/PinchZoom.vue'
import { watchBack } from '../utils/backstack'

const kpi = reactive({ report: 0, med: 0, files: 0, tpl: 0 })
const latestDocs = ref([])  // 最新报告列表（按检查日期倒序）
const interests = ref([])   // 单独关注 [{ name, unit, points, latest_*, scope, loading }]
const groups = ref([])      // 组合关注 [{ doc_id, doc_name, series, scope, loading }]
const loading = ref(true)
// 关注检查项：合并排序（组合卡在前、单独关注在后），轮播与详情页共用同一份卡片模板
const favItems = computed(() => [
  ...groups.value.map((g) => ({ kind: 'g', g })),
  ...interests.value.map((it) => ({ kind: 'i', it })),
])
// 点击标题进入的全量详情页（上下结构展示所有关注卡）
const favDetail = ref(false)
const favKey = (f) => (f.kind === 'g' ? 'g' + f.g.doc_id : 'i' + f.it.name)

// ---- 首页查看报告 ----
const viewDoc = ref(null)
const viewTab = ref('all')
const groupMode = ref(false)      // 组合关注开关（仅查看弹窗内）
// ---- 最新报告：图片放大查看（同一检查记录全部图片串组，左右滑动 / 箭头 / 缩略图切换）----
const imgMdl = ref(false)
const imgList = ref([])
const imgIdx = ref(0)
function collectHomeImgs(docs) {
  const imgs = []
  const push = (p, n) => { const s = '/static/' + p; if (p && !imgs.some((i) => i.src === s)) imgs.push({ src: s, name: (n || '').trim() }) }
  for (const d of docs) {
    const first = d.cover || d.image
    if (first) push(first, d.name || '')
    for (const a of (d.attachments || [])) {
      if (/\.(png|jpe?g|gif|webp|bmp|svg|avif)$/i.test(a.path || '')) push(a.path, a.name || d.name || '')
    }
  }
  return imgs
}
async function viewImg(d) {
  if (!d || !(d.cover || d.image)) return
  // 先立即显示点击的这张，再异步补拉同检查记录下的全部图片串组
  const t = '/static/' + (d.cover || d.image)
  imgList.value = [{ src: t, name: d.name || '' }]
  imgIdx.value = 0
  imgMdl.value = true
  if (!d.report_id) return
  try {
    const docs = await reportApi.docs(d.report_id)
    if (!imgMdl.value) return
    const imgs = collectHomeImgs(docs)
    if (!imgs.length) return
    imgList.value = imgs
    const i = imgs.findIndex((x) => x.src === t)
    imgIdx.value = i >= 0 ? i : 0
  } catch (e) { /* 补拉失败保持单图 */ }
}
function switchImg(dir) {
  const n = imgList.value.length
  if (n < 2) return
  imgIdx.value = (imgIdx.value + dir + n) % n
}
const trendMdl = ref(false)
const trendName = ref('')
const trendScope = ref('all')
const trendData = ref(null)
const trendLoading = ref(false)

const viewDocItems = computed(() => viewDoc.value?.items_detail || [])
const viewAbnItems = computed(() => viewDocItems.value.filter((it) => ['high', 'low', 'abnormal'].includes(it.result)))
const shownItems = computed(() => (viewTab.value === 'abn' ? viewAbnItems.value : viewDocItems.value))
function statusText(s) {
  if (s === 'high') return '偏高'
  if (s === 'low') return '偏低'
  if (s === 'abnormal') return '异常'
  if (s === 'normal') return '正常'
  return '—'
}

const interestMap = computed(() => {
  const m = {}
  for (const it of interests.value) m[it.name + '#0'] = true
  for (const g of groups.value) for (const s of g.series) m[s.name + '#' + g.doc_id] = true
  return m
})
const interestDocOf = (name) => (trendMdl.value || !groupMode.value || !viewDoc.value ? 0 : viewDoc.value.id)
const onInterest = (name) => !!interestMap.value[name + '#' + interestDocOf(name)]
const interestLabel = (name) => {
  const on = onInterest(name)
  if (groupMode.value && viewDoc.value) return on ? '★已入组' : '☆加入组合'
  return on ? '★已关注' : '☆关注'
}

async function refreshInterests() {
  try {
    const d = await reportApi.interests()
    interests.value = (d.singles || []).map(withScope)
    groups.value = (d.groups || []).map((g) => ({ ...g, series: (g.series || []).map((s) => ({ ...s })), scope: 'all' }))
  } catch (e) { }
}

async function toggleInterestH(name) {
  if (!name || !name.trim()) return
  const docId = interestDocOf(name)
  const on = !!interestMap.value[name + '#' + docId]
  try {
    if (on) await reportApi.interestRemove(name, docId || undefined)
    else await reportApi.interestAdd(name, docId || null)
    await refreshInterests()
  } catch (e) { alert('操作失败：' + (e.response?.data?.detail || e.message)) }
}

function openDocView(d) { viewDoc.value = d; viewTab.value = 'all'; groupMode.value = false }
function closeDocView() { viewDoc.value = null }
function openTrendH(name) {
  trendName.value = name || ''
  trendScope.value = 'all'
  trendData.value = null
  trendMdl.value = true
  loadTrendH()
}
async function loadTrendH() {
  trendLoading.value = true
  try { trendData.value = await reportApi.trend(trendName.value.trim(), trendScope.value) }
  catch (e) { trendData.value = null } finally { trendLoading.value = false }
}
function setScopeH(s) { trendScope.value = s; loadTrendH() }

function withScope(x) { return { ...x, scope: 'all' } }

// ---- 单独关注 ----
async function switchOne(it, s) {
  if (it.scope === s && it.points && it.points.length) return
  it.scope = s
  it.loading = true
  try {
    const d = await reportApi.trend(it.name, s)
    it.points = d.points || []
    if (d.unit) it.unit = d.unit
  } catch (e) { it.points = [] } finally { it.loading = false }
}

// 应用内二次确认弹窗（替代浏览器 confirm：移动端 WebView 常屏蔽原生 confirm）
const askMdl = ref(false)
const askMsg = ref('')
const askDanger = ref(false)
let askAction = null
function askConfirm(msg, fn, danger = false) {
  askMsg.value = msg
  askDanger.value = danger
  askAction = fn
  askMdl.value = true
}
function askDo() {
  const fn = askAction
  askMdl.value = false
  askAction = null
  if (fn) fn()
}

function unfollow(it) {
  askConfirm('取消对「' + it.name + '」的关注？', async () => {
    try {
      await reportApi.interestRemove(it.name)
      interests.value = interests.value.filter((x) => x.name !== it.name)
    } catch (e) { alert('操作失败：' + (e.response?.data?.detail || e.message)) }
  }, true)
}

// ---- 组合关注 ----
const chartSeries = (g) => g.series.map((s) => ({ name: s.name, unit: s.unit || '', points: s.points, latest_value: s.latest_value }))
const hasGroupData = (g) => g.series.some((s) => s.points && s.points.length)
const groupCount = (g) => g.series.reduce((n, s) => n + (s.points?.length || 0), 0)

async function switchGrp(g, s) {
  if (g.scope === s && hasGroupData(g)) return
  g.scope = s
  g.loading = true
  try {
    await Promise.all(g.series.map(async (ser) => {
      const d = await reportApi.trend(ser.name, s)
      ser.points = d.points || []
      if (d.unit) ser.unit = d.unit
    }))
  } catch (e) { /* 部分失败保持原状 */ } finally { g.loading = false }
}

function ungroupAll(g) {
  askConfirm('取消该报告内全部组合关注（' + g.doc_name + '）？', async () => {
    try {
      for (const s of g.series) await reportApi.interestRemove(s.name, g.doc_id)
      groups.value = groups.value.filter((x) => x.doc_id !== g.doc_id)
    } catch (e) { alert('操作失败：' + (e.response?.data?.detail || e.message)) }
  }, true)
}

onMounted(async () => {
  await Promise.allSettled([
    reportApi.count().then((c) => (kpi.report = c.total || 0)).catch(() => {}),
    medApi.count().then((c) => (kpi.med = c.total || 0)).catch(() => {}),
    fileApi.count().then((c) => (kpi.files = c.total || 0)).catch(() => {}),
    tplApi.count().then((c) => (kpi.tpl = c.total || 0)).catch(() => {}),
  ])
  try { latestDocs.value = await reportApi.latestDocs(10) } catch (e) { latestDocs.value = [] }
  await refreshInterests()
  loading.value = false
  window.addEventListener('resize', onLpResize)
})

// ---- 最新报告卡名：超出时无缝 360° 循环跑马灯（JS rAF 驱动）----
let lpStops = []   // 已启动跑马灯的清理函数集
let lpResizeT = 0

function onLpResize() { clearTimeout(lpResizeT); lpResizeT = setTimeout(detectLpName, 250) }

function detectLpName() {
  // 清理旧动画再重建（窗口尺寸变化 / 数据变化后调用）
  lpStops.forEach((f) => { try { f() } catch (e) {} })
  lpStops = []
  document.querySelectorAll('.lp-t').forEach((el) => {
    el.classList.remove('mq')
    const track = el.querySelector('.mq-track')
    if (track) track.style.transform = ''
    if (el.scrollWidth <= el.clientWidth + 1) return
    el.classList.add('mq')
    startLp(el, track)
  })
}

function startLp(el, track) {
  const half = el.scrollWidth          // 轨道一半 = 单份名称宽（含间隔）
  let x = 0, raf = 0, running = true, last = performance.now()
  const tick = (t) => {
    if (!running) return
    const dt = Math.min(60, t - last); last = t
    x -= (42 * dt) / 1000              // 匀速 42px/s
    if (-x >= half) x += half          // 无缝接缝回卷
    track.style.transform = 'translateX(' + x + 'px)'
    raf = requestAnimationFrame(tick)
  }
  const stop = () => { running = false; cancelAnimationFrame(raf) }
  raf = requestAnimationFrame(tick)
  // 悬停 / 触摸按住暂停，移开继续
  track.addEventListener('mouseenter', stop)
  track.addEventListener('mouseleave', () => {
    if (!running) { running = true; last = performance.now(); raf = requestAnimationFrame(tick) }
  })
  lpStops.push(() => {
    stop()
    track.removeEventListener('mouseenter', stop)
  })
}
watch(latestDocs, async () => { await nextTick(); detectLpName() })
onUnmounted(() => {
  window.removeEventListener('resize', onLpResize)
  lpStops.forEach((f) => { try { f() } catch (e) {} })
  lpStops = []
})
// 系统返回键逐级返回：弹层进入返回栈，按返回先关弹层，再回退页面
watchBack(() => imgMdl.value, () => { imgMdl.value = false })
watchBack(() => !!viewDoc.value, () => closeDocView())
watchBack(() => trendMdl.value, () => { trendMdl.value = false })
watchBack(() => askMdl.value, () => { askMdl.value = false })
</script>

<style scoped>
.ti-title {
  display: inline-flex; align-items: center; gap: 8px;
  background: transparent; border: 0; padding: 0; cursor: pointer; color: inherit;
}
.ti-title .ti-all {
  font-size: 11.5px; color: var(--acc); border: 1px solid var(--line);
  background: var(--card2); border-radius: 999px; padding: 2px 8px;
}
.ti-hint {
  display: none; font-size: 11px; color: var(--mut);
  background: var(--card2); border: 1px dashed var(--line); border-radius: 6px;
  padding: 2px 8px;
}
.fav-detail {
  position: fixed; inset: 0; z-index: 820;
  background: var(--bg); display: flex; flex-direction: column;
}
.fav-bar {
  position: sticky; top: 0; z-index: 1;
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px calc(12px + env(safe-area-inset-top));
  background: var(--card); border-bottom: 1px solid var(--line);
}
.fav-back {
  border: 1px solid var(--line); background: var(--card2); color: var(--fg);
  border-radius: 8px; padding: 6px 12px; font-size: 13px; cursor: pointer;
}
.fav-title { font-size: 15px; font-weight: 650; }
.fav-list {
  flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px;
  padding: 14px 14px calc(30px + env(safe-area-inset-bottom));
}
.fav-list .ti-card { flex: 0 0 auto; }
.ti-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 16px;
  margin-top: 14px;
}
.ti-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px 18px 14px;
  background: var(--card);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ti-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.ti-name { font-size: 15px; }
.ti-name.g { font-size: 13.5px; }
.ti-now { margin-top: 3px; font-size: 12.5px; color: var(--mut); }
.ti-now .rs { font-size: 19px; font-weight: 700; margin: 0 2px; }
.ti-tabs { flex: none; }
.ti-tabs button { font-size: 12px; padding: 4px 10px; }
.ti-empty { flex: 1; min-height: 120px; display: flex; align-items: center; justify-content: center; font-size: 12.5px; color: var(--mut); }
.ti-foot { display: flex; align-items: center; justify-content: space-between; }
.ti-foot .mini { font-size: 11.5px; padding: 3px 8px; }

/* ── 最新报告：卡片网格（16:9 图 + 名称/日期/统计/操作）──
   PC 一行 4 张；平板 3 张；手机（≤560px）一行 2 张 */
.lp-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 14px; }
@media (max-width: 1100px) { .lp-grid { grid-template-columns: repeat(3, 1fr) } }
@media (max-width: 860px) { .lp-grid { grid-template-columns: repeat(2, 1fr) } }
.lp-card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
  display: flex; flex-direction: column; transition: border-color .16s, box-shadow .16s }
.lp-card:hover { border-color: var(--acc); box-shadow: 0 0 0 2px var(--acc-soft) }
.lp-media { position: relative; aspect-ratio: 16 / 9; background: var(--card2); border-bottom: 1px solid var(--line); overflow: hidden }
.lp-media img { width: 100%; height: 100%; object-fit: cover; display: block; cursor: zoom-in }
.lp-ph { position: absolute; inset: 0; display: flex; align-items: flex-start; justify-content: space-between;
  padding: 14px 16px }
.lp-ph-cat { font-size: 13px; font-weight: 700; letter-spacing: .4px; color: var(--acc) }
.lp-ph-idx { font-size: 26px; font-weight: 750; color: var(--mut); font-variant-numeric: tabular-nums; opacity: .65 }
.lp-body { display: flex; flex-direction: column; gap: 6px; padding: 14px 16px 16px; flex: 1 }
.lp-name { display: flex; align-items: center; gap: 8px; justify-content: space-between }
.lp-name b { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 15px; font-weight: 650 }
.lp-name b .mq-track { display: inline-flex; white-space: nowrap; min-width: 100% }
.lp-name b .mq-item { flex: none; white-space: nowrap; max-width: none }
.lp-name b:not(.mq) .mq-item:nth-child(2) { display: none }
/* 名称溢出：无缝 360° 循环跑马灯（JS rAF 驱动，悬停暂停） */
.lp-name b.mq .mq-item { padding-right: 26px }
.lp-name .badge { flex: none }
.lp-meta { font-size: 12px; color: var(--mut); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.lp-stat { font-size: 12.5px; color: var(--fg) }
.lp-ops { margin-top: auto; padding-top: 10px; display: flex; justify-content: flex-end }
.lp-empty { grid-column: 1 / -1; text-align: center; color: var(--mut); font-size: 13px; padding: 30px 10px }

/* ── 移动端：关注卡改轮播（横向滑动切换）；最新报告保持一行两张 ── */
@media (max-width: 560px) {
  .ti-hint { display: inline-block }
  .ti-grid {
    display: flex; overflow-x: auto; scroll-snap-type: x mandatory;
    gap: 10px; margin-top: 12px; padding: 2px 4px 8px;
    scrollbar-width: none; -webkit-overflow-scrolling: touch;
  }
  .ti-grid::-webkit-scrollbar { display: none }
  .ti-grid .ti-card {
    flex: 0 0 86%; max-width: 86%; scroll-snap-align: center;
    padding: 12px 12px 10px;
  }
  .ti-head { flex-direction: column; align-items: stretch; gap: 8px }
  .ti-tabs { display: flex; width: 100% }
  .ti-tabs button { flex: 1; padding: 6px 2px; font-size: 12px }
  .ti-name { font-size: 14px }
  .ti-now .rs { font-size: 17px }
  /* 关注卡详情页与轮播卡片外观一致（详情页上下结构） */
  .fav-list .ti-card { flex: 0 0 auto; width: auto; max-width: none; scroll-snap-align: unset }
  /* 最新报告：两列紧凑版（375px 下每卡约 170px） */
  .lp-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 12px }
  .lp-body { padding: 10px 12px 12px; gap: 4px }
  .lp-name b { font-size: 13px }
  .lp-name .badge { font-size: 10px; padding: 1px 6px }
  .lp-meta { font-size: 11px }
  .lp-stat { font-size: 11.5px }
  .lp-ops { padding-top: 8px }
  .lp-ops .mini { padding: 3px 9px; font-size: 11px }
  .lp-ph-cat { font-size: 11.5px }
  .lp-ph-idx { font-size: 17px }
}
</style>