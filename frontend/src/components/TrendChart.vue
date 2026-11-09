<script setup>
// 轻量 SVG 折线图：参考区间带 + 趋势曲线 + 数值点 + 悬停/点击提示。
// 支持单系列（points）与多系列（series，同一图内对照显示，如组合关注）。
// viewBox 跟随容器实际尺寸（1:1 渲染），避免文字被非等比拉伸而模糊。
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  points: { type: Array, default: () => [] },               // 单系列 [{ checked_at, value, num, ref_range, unit, result }]
  series: { type: Array, default: () => [] },               // 多系列 [{ name, unit, points }]
  unit: { type: String, default: '' },
  mini: { type: Boolean, default: false },
  height: { type: Number, default: 0 },                     // 大图自定义高度（0=默认300px）
})

const W0 = 620, H0 = 300
const PAD = props.mini ? { l: 6, r: 10, t: 8, b: 2 } : { l: 46, r: 24, t: 26, b: 30 }
const hover = ref(-1)
const pinned = ref(false)
const PALETTE = ['#3274d9', '#e5484d', '#2fbf71', '#f5a524', '#a855f7', '#0ea5e9', '#f43f5e', '#84cc16']

// 容器实际尺寸（像素），viewBox 与之 1:1，保证文字、圆点不变形
const tcEl = ref(null)
const W = ref(W0)
const H = ref(H0)
let ro = null
function setBox() {
  if (!tcEl.value) return
  const r = tcEl.value.getBoundingClientRect()
  if (r.width > 0) W.value = Math.max(60, r.width)
  if (r.height > 0) H.value = Math.max(60, r.height)
}
onMounted(() => {
  setBox()
  if (tcEl.value && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(setBox)
    ro.observe(tcEl.value)
  }
})
onBeforeUnmount(() => { if (ro) ro.disconnect() })

function parseRange(r) {
  if (!r) return null
  const s = String(r).trim()
  const m = s.match(/(-?\d+(?:\.\d+)?)\s*[~\-—～]\s*(-?\d+(?:\.\d+)?)/)
  if (m) return [parseFloat(m[1]), parseFloat(m[2])]
  const lo = s.match(/[≥>]\s*(-?\d+(?:\.\d+)?)/)
  if (lo) return [parseFloat(lo[1]), null]
  const hi = s.match(/[≤<]\s*(-?\d+(?:\.\d+)?)/)
  if (hi) return [null, parseFloat(hi[1])]
  return null
}

// 归一化成系列列表：series 优先，否则用 points 包一层
const sers = computed(() => {
  if (props.series && props.series.length) return props.series
  if (props.points && props.points.length) return [{ name: '', unit: props.unit || '', points: props.points }]
  return []
})

// 每条曲线的可数点
const numPts = (s) => s.points.filter((p) => p.num != null && isFinite(p.num))
const hasData = computed(() => sers.value.some((s) => numPts(s).length > 0))

// 全局日期轴（共享 X 坐标，缺数据自动断线）
const dates = computed(() => {
  const set = new Set()
  for (const s of sers.value) for (const p of s.points) if (p.checked_at) set.add(p.checked_at)
  return [...set].sort()
})
const xIndex = (d) => dates.value.indexOf(d)
const X = (di) => {
  const n = dates.value.length
  if (n < 2) return props.mini ? 4 : PAD.l + (W.value - PAD.l - PAD.r) / 2
  return PAD.l + (di / (n - 1)) * (W.value - PAD.l - PAD.r)
}

// 参考区间带：收集全部点中最近的非空参考（组合图优先用第一系列的）
const refBand = computed(() => {
  if (!hasData.value) return null
  let lo = null, hi = null, last = {}
  for (const s of sers.value) {
    for (const p of s.points) {
      if (p.ref_range) last = p
      const r = parseRange(p.ref_range)
      if (!r) continue
      if (r[0] != null) lo = lo == null ? r[0] : Math.min(lo, r[0])
      if (r[1] != null) hi = hi == null ? r[1] : Math.max(hi, r[1])
    }
    if (last && lo != null && hi != null) break
  }
  return { lo, hi, refStr: last.ref_range }
})

const yDomain = computed(() => {
  let lo = Infinity, hi = -Infinity
  for (const s of sers.value) for (const p of numPts(s)) { lo = Math.min(lo, p.num); hi = Math.max(hi, p.num) }
  if (!isFinite(lo)) return [0, 1]
  const rb = refBand.value
  if (rb && rb.lo != null) lo = Math.min(lo, rb.lo)
  if (rb && rb.hi != null) hi = Math.max(hi, rb.hi)
  if (lo === hi) { lo -= 1; hi += 1 }
  const pad = (hi - lo) * 0.14 || 1
  return [lo - pad, hi + pad]
})

const Y = (v) => {
  const [lo, hi] = yDomain.value
  return PAD.t + (1 - (v - lo) / (hi - lo)) * (H.value - PAD.t - PAD.b)
}

// 每条曲线 path（按日期序，缺槽断开）
function linePathOf(s) {
  const pts = numPts(s).filter((p) => p.checked_at).sort((a, b) => (a.checked_at < b.checked_at ? -1 : 1)).filter((p) => p.num != null)
  if (pts.length < 2) return ''
  const xs = pts.map((p) => X(xIndex(p.checked_at)))
  const ys = pts.map((p) => Y(p.num))
  let d = `M ${xs[0]} ${ys[0]}`
  for (let i = 1; i < pts.length; i++) {
    if (xs[i] === xs[i - 1]) continue
    d += ` L ${xs[i]} ${ys[i]}`
  }
  return d
}

const yTicks = computed(() => {
  if (props.mini) return []
  const [lo, hi] = yDomain.value
  const n = 4
  return Array.from({ length: n + 1 }, (_, i) => {
    const v = lo + ((hi - lo) * i) / n
    return { v, y: Y(v), label: v.toFixed(1) }
  })
})

const xLabels = computed(() => {
  if (props.mini) return []
  const step = Math.max(1, Math.ceil(dates.value.length / 6))
  return dates.value.map((d, i) => ({ i, y: H.value - 8, show: i % step === 0 || i === dates.value.length - 1, label: d.slice(5), x: X(i) }))
})

function colorOf(s, i) { return PALETTE[i % PALETTE.length] }

function onMove(e) {
  if (!hasData.value || props.mini) return
  setHoverFromEvent(e)
}
function onTap(e) {
  if (!hasData.value || props.mini) return
  setHoverFromEvent(e)
  pinned.value = true          // 点击固定查看该点详情（移出图表后清除）
}
function setHoverFromEvent(e) {
  const rect = e.currentTarget.getBoundingClientRect()
  const x = ((e.clientX - rect.left) / rect.width) * W.value
  let best = -1, bd = 1e9
  dates.value.forEach((d, i) => {
    const dd = Math.abs(X(i) - x)
    if (dd < bd) { bd = dd; best = i }
  })
  hover.value = best
}
function onLeave() {
  if (pinned.value) pinned.value = false
  hover.value = -1
}

const hoverPts = computed(() => {
  if (hover.value < 0 || !dates.value[hover.value]) return null
  const date = dates.value[hover.value]
  return sers.value.map((s, si) => {
    const p = numPts(s).find((p) => p.checked_at === date)
    return p ? { name: s.name, value: p.value, unit: p.unit || s.unit || '', result: p.result, color: colorOf(s, si) } : null
  }).filter(Boolean)
})

function resultText(r) {
  if (r === 'high') return '偏高'
  if (r === 'low') return '偏低'
  return '正常'
}

// HTML 浮层提示：宽度由内容撑开，位置以 hover 点为中心并钳制在图表内，绝不被遮挡
const tipEl = ref(null)
function placeTip() {
  const el = tipEl.value
  if (!el) return
  const w = W.value
  const cw = el.offsetWidth || 160
  const left = Math.min(Math.max(X(hover.value) - cw / 2, 6), Math.max(6, w - cw - 6))
  el.style.left = left + 'px'
  el.style.top = '8px'
}
watch(hover, async (v) => {
  if (v < 0 || props.mini) return
  await nextTick()
  placeTip()
})
</script>

<template>
  <div ref="tcEl" class="tc" :class="{ mini }" :style="height && !mini ? { height: height + 'px' } : null">
    <svg v-if="hasData" :viewBox="`0 0 ${W} ${H}`" class="tc-svg"
      @mousemove="onMove" @mouseleave="onLeave" @click="onTap" preserveAspectRatio="none">
      <defs>
        <linearGradient id="tc-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--acc)" stop-opacity="0.16" />
          <stop offset="100%" stop-color="var(--acc)" stop-opacity="0.02" />
        </linearGradient>
      </defs>

      <!-- 网格线 + y 轴刻度 -->
      <g v-if="!mini">
        <line v-for="t in yTicks" :key="t.v" :x1="PAD.l" :y1="t.y" :x2="W - PAD.r" :y2="t.y" stroke="var(--line)" stroke-width="1" stroke-dasharray="3 4" />
        <text v-for="t in yTicks" :key="'t' + t.v" :x="PAD.l - 6" :y="t.y + 3.5" text-anchor="end" class="tc-axis">{{ t.label }}</text>
      </g>

      <!-- 参考区间带（多系列仅当只有一个系列时展示，避免多条参考混淆） -->
      <g v-if="refBand && sers.length === 1 && (refBand.lo != null || refBand.hi != null)">
        <rect v-if="refBand.lo != null && refBand.hi != null"
          :x="PAD.l" :y="Y(refBand.hi)" :width="W - PAD.l - PAD.r" :height="Math.max(0, Y(refBand.lo) - Y(refBand.hi))"
          fill="rgba(47,191,113,.10)" stroke="rgba(47,191,113,.35)" stroke-width="1" stroke-dasharray="4 3" />
        <line v-if="refBand.lo != null" :x1="PAD.l" :y1="Y(refBand.lo)" :x2="W - PAD.r" :y2="Y(refBand.lo)" stroke="rgba(47,191,113,.45)" stroke-width="1" stroke-dasharray="4 3" />
        <line v-if="refBand.hi != null" :x1="PAD.l" :y1="Y(refBand.hi)" :x2="W - PAD.r" :y2="Y(refBand.hi)" stroke="rgba(47,191,113,.45)" stroke-width="1" stroke-dasharray="4 3" />
      </g>

      <!-- 面积（仅单系列时） -->
      <g v-if="sers.length === 1">
        <path v-if="!mini && linePathOf(sers[0])" :d="linePathOf(sers[0]) + ` L ${X(dates.length - 1)} ${H - PAD.b} L ${X(0)} ${H - PAD.b} Z`" fill="url(#tc-fill)" />
      </g>

      <!-- 曲线 -->
      <path v-for="(s, si) in sers" :key="si" :d="linePathOf(s)" fill="none" :stroke="colorOf(s, si)"
        :stroke-width="mini ? 1.8 : (sers.length > 1 ? 2.2 : 2.6)" stroke-linejoin="round" stroke-linecap="round" opacity="0.96" />

      <!-- x 轴日期标签 -->
      <g v-if="!mini">
        <text v-for="l in xLabels" :key="l.i" v-show="l.show" :x="l.x" :y="l.y" text-anchor="middle" class="tc-axis tiny">{{ l.label }}</text>
      </g>

      <!-- 数据点 -->
      <template v-for="(s, si) in sers" :key="si">
        <g v-for="(p, i) in numPts(s)" :key="i">
          <circle :cx="X(xIndex(p.checked_at))" :cy="Y(p.num)" :r="(mini ? 2 : (hover === dates.indexOf(p.checked_at) && sers.length === 1 ? 6 : 4))"
            :fill="colorOf(s, si)" :stroke="mini ? 'transparent' : '#fff'" :stroke-width="1.5" opacity="0.95">
            <title>{{ s.name }} {{ (p.checked_at || '') }}：{{ p.value }}</title>
          </circle>
        </g>
      </template>
    </svg>

    <!-- 悬停/点击详情：HTML 浮层（z-index 高，避免被图表内其他元素遮挡），宽度由内容撑开、居左对齐 -->
    <div ref="tipEl" v-if="!mini && hoverPts && hoverPts.length" class="tc-tip">
      <div class="tt-date">{{ dates[hover] || '—' }}</div>
      <template v-if="sers.length === 1">
        <div class="tt-val">
          <em :class="'tt-value'">{{ hoverPts[0].value }} {{ hoverPts[0].unit || '' }}</em>
          <em :class="'tt-rs ' + (hoverPts[0].result || '')">{{ resultText(hoverPts[0].result) }}</em>
        </div>
      </template>
      <template v-else>
        <div v-for="(hp, hi) in hoverPts" :key="hi" class="tt-row">
          <i :style="{ background: hp.color }"></i>{{ hp.name }}：{{ hp.value }} {{ hp.unit || '' }}
          <em :class="'tt-rs ' + (hp.result || '')">{{ resultText(hp.result) }}</em>
        </div>
      </template>
    </div>

    <div v-if="!hasData" class="tc-empty">{{ mini ? '—' : '暂无可用数值，无法绘制曲线' }}</div>
    <div v-if="!mini && hasData && dates.length < 2" class="tc-hint">数值点不足，暂无法连线</div>

    <!-- 图例（多系列时显示） -->
    <div v-if="!mini && sers.length > 1" class="tc-legend">
      <span v-for="(s, si) in sers" :key="si" class="lg">
        <i :style="{ background: colorOf(s, si) }"></i>{{ s.name }}
        <em v-if="s.latest_value != null">{{ s.latest_value }}{{ s.unit ? ' ' + s.unit : '' }}</em>
      </span>
    </div>
  </div>
</template>

<style scoped>
.tc { position: relative; }
.tc-svg { width: 100%; height: 100%; display: block; }
.tc:not(.mini) { height: 300px; }
.tc.mini { height: 52px; }
.tc-axis { font-size: 11.5px; fill: var(--mut); }
.tc-axis.tiny { font-size: 10.5px; }
.tc-tip {
  position: absolute; top: 8px; left: -999px;
  width: max-content; min-width: 150px; max-width: calc(100% - 12px);
  box-sizing: border-box;
  background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  box-shadow: 0 10px 28px rgba(8, 12, 20, .28);
  padding: 8px 10px; z-index: 50; text-align: left;
  pointer-events: none;
}
.tc-tip .tt-date { font-size: 12px; font-weight: 600; opacity: .78; color: var(--fg); margin-bottom: 3px; }
.tc-tip .tt-val, .tc-tip .tt-row { font-size: 13px; font-weight: 700; color: var(--fg); }
.tc-tip .tt-value { font-style: normal; }
.tc-tip .tt-rs { font-style: normal; font-size: 11px; margin-left: 6px; padding: 1px 6px; border-radius: 999px; background: color-mix(in srgb, var(--card2) 88%, var(--line)); color: var(--fg); font-weight: 600; white-space: nowrap }
.tc-tip .tt-rs.high { color: #e5484d }
.tc-tip .tt-rs.low { color: #f5a524 }
.tc-tip .tt-row i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px }
.tc-tip .tt-row { display: block; overflow-wrap: anywhere; }
.tc-empty, .tc-hint { position: absolute; left: 0; right: 0; top: 50%; transform: translateY(-50%); text-align: center; font-size: 12px; color: var(--mut); }
.tc-hint { top: auto; bottom: -18px; transform: none; font-size: 11px; }
.tc-legend {
  position: absolute; top: 4px; right: 6px; display: flex; flex-wrap: wrap; gap: 10px;
  font-size: 11px; color: var(--mut); background: color-mix(in srgb, var(--card) 82%, transparent);
  padding: 3px 8px; border-radius: 8px;
}
.tc-legend .lg { display: inline-flex; align-items: center; gap: 4px; }
.tc-legend i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.tc-legend em { font-style: normal; font-weight: 700; color: var(--fg); }
</style>