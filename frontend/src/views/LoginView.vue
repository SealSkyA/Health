<template>
  <div class="login-page">
    <canvas ref="bgCanvas" class="login-bg"></canvas>

    <p class="quote quote-pc">健康如对弈 · 步步为营</p>

    <div class="login-panel">
      <div class="panel-head">
        <div class="mk">壹</div>
        <div>
          <div class="pt">壹健康 · 检查报告管理系统</div>
          <div class="ps">报告 · 用药 · AI · 文件</div>
        </div>
      </div>

      <p class="quote quote-m">健康如对弈 · 步步为营</p>

      <div class="login-logo">
        <div class="login-title">账号登录</div>
        <span class="phase"><b class="turn-dot" :class="{ wk2: phaseText[0] === '白' }"></b>{{ phaseText }}</span>
      </div>

      <form class="login-form" @submit.prevent="doLogin">
        <label class="fld">
          <span class="fl">用户名</span>
          <input type="text" v-model="username" placeholder="请输入用户名" autocomplete="username" required />
        </label>
        <label class="fld">
          <span class="fl">密码</span>
          <input type="password" v-model="password" placeholder="请输入密码" autocomplete="current-password" required />
        </label>

        <p v-if="err" class="login-err">{{ err }}</p>

        <button class="pri login-btn" type="submit" :disabled="loading">
          {{ loading ? '登录中…' : '登 录' }}
        </button>
      </form>

      <p class="login-tip">默认管理员：admin</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../api/index.js'
import { resetPerms } from '../utils/perm'
import { applyUserFromApi } from '../utils/user'

const router = useRouter()
const username = ref('')
const password = ref('')
const err = ref('')
const loading = ref(false)

// ── 全屏背景：五子棋对弈（双 AI 博弈）──
const bgCanvas = ref(null)
const phaseText = ref('黑方行棋')
let engine = null

onMounted(() => { engine = createGame(bgCanvas.value, (t) => phaseText.value = t) })
onBeforeUnmount(() => { if (engine) engine.stop() })

function createGame(cv, onPhase) {
  if (!cv) return null
  const N = 15, ctx = cv.getContext('2d')
  const dirs = [[1, 0], [0, 1], [1, 1], [1, -1]]
  let bd = Array.from({ length: N }, () => Array(N).fill(0))
  let W = 0, H = 0, g = 0, offX = 0, offY = 0
  let stones = [], cursor = null, winLine = null, over = false
  let acc = '90,146,229', raf = 0, stepT = 0, lastTs = 0
  let turn = 1 // 1 黑先

  const readAccent = () => {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--acc-rgb').trim()
    if (v) acc = v.replace(/\s+/g, '')
  }
  readAccent()
  // 主题色 / 明暗主题切换时刷新 accent，棋盘线条实时跟随
  const mo = new MutationObserver(readAccent)
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-accent', 'data-theme'] })

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    // canvas 仅铺满视口左侧 2/3（PC），棋盘与对弈区只在此区域内绘制
    W = cv.clientWidth; H = cv.clientHeight
    cv.width = W * dpr; cv.height = H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    // 整屏棋盘：格距适中铺满背景；对弈区为中间 15 路（PC 偏左让出右侧面板，移动端铺满居中）
    g = W <= 899 ? Math.max(22, Math.floor(W / 15)) : 46
    const gw = 14 * g
    // 偏移必须吸附到 g 的整数倍，棋子/星位才精确落在背景格线交叉点上
    // PC：对弈区在左 2/3 棋盘区内水平居中；移动端：全屏棋盘居中
    offX = Math.max(0, Math.floor((W - gw) / 2 / g) * g)
    offY = Math.max(0, Math.floor((H - gw) / 2 * 0.86 / g) * g)
  }
  resize()
  window.addEventListener('resize', resize)

  // —— AI 攻防评分 ——
  const weight = [0, 1, 10, 100, 1000]
  function lineLen(x, y, dx, dy, c, winArr) {
    let cnt = 1; const arr = [[x, y]]
    let i = x + dx, j = y + dy
    while (i >= 0 && i < N && j >= 0 && j < N && bd[i][j] === c) { cnt++; arr.push([i, j]); i += dx; j += dy }
    i = x - dx; j = y - dy
    while (i >= 0 && i < N && j >= 0 && j < N && bd[i][j] === c) { cnt++; arr.push([i, j]); i -= dx; j -= dy }
    if (winArr && cnt >= 5) { winArr.length = 0; winArr.push(...arr) }
    return cnt
  }
  function scorePos(x, y, c) {
    let s = 0
    for (const [dx, dy] of dirs) {
      const l = lineLen(x, y, dx, dy, c)
      if (l >= 5) return weight[4] * 100
      if (l >= 2) s += weight[l - 1]
    }
    return s
  }
  // 落子 (x,y) 颜色 c 后，四方向最大连子数
  function maxConnect(x, y, c) {
    let m = 0
    for (const [dx, dy] of dirs) m = Math.max(m, lineLen(x, y, dx, dy, c))
    return m
  }
  function choose() {
    const center = Math.floor(N / 2)
    let occupied = 0
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) if (bd[i][j]) occupied++
    if (occupied === 0) return [center, center]
    if (occupied === 1) return [center + Math.floor(Math.random() * 3) - 1, center + Math.floor(Math.random() * 3) - 1]
    const opp = -turn
    let bx = -1, by = -1, bs = -1
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
      if (bd[i][j]) continue
      let near = false
      for (let a = -1; a <= 1 && !near; a++) for (let b = -1; b <= 1 && !near; b++) {
        const ii = i + a, jj = j + b
        if (ii >= 0 && ii < N && jj >= 0 && jj < N && bd[ii][jj]) near = true
      }
      if (!near) continue
      // 平局规则：任何一方都禁止连成 4 子及以上（五连必先有四连）
      if (maxConnect(i, j, turn) >= 4) continue
      const atk = scorePos(i, j, turn)
      const def = scorePos(i, j, opp)
      if (atk >= weight[3] * 100) return [i, j]
      if (def >= weight[3] * 100) return [i, j]
      let s = atk * 1.15 + def
      s += (Math.random() - 0.5) * 0.06 * s
      if (s > bs) { bs = s; bx = i; by = j }
    }
    return (bx < 0) ? null : [bx, by]   // 无合法点 = 满盘和棋
  }

  function checkWin(x, y) {
    for (const [dx, dy] of dirs) {
      const arr = []
      lineLen(x, y, dx, dy, turn, arr)
      if (arr.length >= 5) return arr
    }
    return null
  }

  const px = (x) => offX + x * g
  const py = (y) => offY + y * g

  function place(x, y) {
    bd[x][y] = turn
    stones.push({ x: px(x), y: py(y), r: g * 0.43, kind: turn, phase: 0 })
    cursor = null
    const wl = checkWin(x, y)
    if (wl) {
      winLine = wl; over = true
      onPhase(turn === 1 ? '黑棋获胜' : '白棋获胜')
      if (stepT) clearTimeout(stepT)
      stepT = setTimeout(restart, 3400)
    } else {
      turn = -turn
      onPhase(turn === 1 ? '黑方行棋' : '白方行棋')
      if (stepT) clearTimeout(stepT)
      stepT = setTimeout(() => {
        const mv = choose()
        if (!mv) { onPhase('和棋 · 重新对弈'); stepT = setTimeout(restart, 3000); return }
        const [a, b] = mv
        cursor = { x: px(a), y: py(b) }
        place(a, b)
      }, 1080 + Math.random() * 700)
    }
  }
  function restart() {
    bd = Array.from({ length: N }, () => Array(N).fill(0))
    stones = []; winLine = null; over = false; turn = 1
    onPhase('黑方行棋')
    const mv = choose()
    if (!mv) { stepT = setTimeout(restart, 800); return }
    const [cx, cy] = mv
    cursor = { x: px(cx), y: py(cy) }
    stepT = setTimeout(() => place(cx, cy), 1000)
  }
  restart()

  function draw(ts) {
    raf = requestAnimationFrame(draw)
    const dt = Math.min(ts - (lastTs || ts), 50); lastTs = ts
    for (const s of stones) if (s.phase < 1) s.phase = Math.min(1, s.phase + dt / 320)

    ctx.clearRect(0, 0, W, H)
    // ── 整屏棋盘网格：铺满整个背景 ──
    const dark = document.documentElement.getAttribute('data-theme') === 'dark'
    ctx.strokeStyle = 'rgba(' + acc + ',' + (dark ? '.2' : '.13') + ')'
    ctx.lineWidth = 1
    ctx.beginPath()
    const cols = Math.ceil(W / g) + 1, rows = Math.ceil(H / g) + 1
    for (let i = 0; i <= cols; i++) { const x = i * g; ctx.moveTo(x, 0); ctx.lineTo(x, H) }
    for (let j = 0; j <= rows; j++) { const y = j * g; ctx.moveTo(0, y); ctx.lineTo(W, y) }
    ctx.stroke()
    // 对弈区（中央 15 路）内的星位
    ctx.fillStyle = 'rgba(' + acc + ',' + (dark ? '.38' : '.30') + ')'
    for (const [sx, sy] of [[3, 3], [11, 3], [7, 7], [3, 11], [11, 11]]) {
      ctx.beginPath(); ctx.arc(offX + sx * g, offY + sy * g, Math.max(2, g * 0.06), 0, Math.PI * 2); ctx.fill()
    }
    // 行棋光标
    if (cursor && !over) {
      const ph = Math.sin(ts / 260) * 0.5 + 0.5
      ctx.strokeStyle = 'rgba(255,255,255,' + (0.3 + ph * 0.32).toFixed(2) + ')'
      ctx.lineWidth = 1.8
      ctx.beginPath(); ctx.arc(cursor.x, cursor.y, g * 0.56, 0, Math.PI * 2); ctx.stroke()
    }
    // 胜线
    if (winLine) {
      const x0 = px(winLine[0][0]), y0 = py(winLine[0][1])
      const x1 = px(winLine[winLine.length - 1][0]), y1 = py(winLine[winLine.length - 1][1])
      const fl = 0.5 + 0.5 * Math.sin(ts / 140)
      ctx.strokeStyle = 'rgba(' + acc + ',.95)'; ctx.lineWidth = 2.8
      ctx.shadowColor = 'rgba(' + acc + ',' + (0.5 + fl * 0.4).toFixed(2) + ')'
      ctx.shadowBlur = 9 * (0.6 + fl)
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke()
      ctx.shadowBlur = 0
    }
    // 棋子
    for (const s of stones) {
      const r = s.r * (0.4 + 0.6 * s.phase)
      ctx.globalAlpha = 0.25 + 0.75 * s.phase
      if (s.kind === 1) {
        const cg = ctx.createRadialGradient(s.x - r * 0.3, s.y - r * 0.34, r * 0.1, s.x, s.y, r)
        cg.addColorStop(0, '#3E4856'); cg.addColorStop(0.55, '#1B212B'); cg.addColorStop(1, '#0E1218')
        ctx.fillStyle = cg
      } else {
        const cg = ctx.createRadialGradient(s.x - r * 0.3, s.y - r * 0.34, r * 0.1, s.x, s.y, r)
        cg.addColorStop(0, '#FFFFFF'); cg.addColorStop(0.6, '#EEF1F5'); cg.addColorStop(1, '#C9D2DC')
        ctx.fillStyle = cg
      }
      ctx.beginPath(); ctx.arc(s.x, s.y, r, 0, Math.PI * 2); ctx.fill()
      ctx.globalAlpha = 1
      if (s.kind === 1) {
        ctx.strokeStyle = 'rgba(255,255,255,.28)'; ctx.lineWidth = 1
        ctx.beginPath(); ctx.arc(s.x, s.y, r - 0.5, 0, Math.PI * 2); ctx.stroke()
      }
      if (s.phase < 1) {
        ctx.strokeStyle = 'rgba(255,255,255,' + ((1 - s.phase) * 0.5).toFixed(2) + ')'
        ctx.lineWidth = 1.4
        ctx.beginPath(); ctx.arc(s.x, s.y, r + (1 - s.phase) * 10, 0, Math.PI * 2); ctx.stroke()
      }
    }
    window.__boardOK = true
  }
  raf = requestAnimationFrame(draw)

  return { stop() { cancelAnimationFrame(raf); if (stepT) clearTimeout(stepT); mo.disconnect(); window.removeEventListener('resize', resize) } }
}

async function doLogin() {
  if (loading.value) return
  err.value = ''
  loading.value = true
  try {
    const data = await authApi.login({ username: username.value.trim(), password: password.value })
    localStorage.setItem('token', data.access_token)
    applyUserFromApi(data.user || {})
    resetPerms()
    router.replace('/home')
  } catch (e) {
    err.value = (e.response && e.response.data && e.response.data.detail) || '登录失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  height: 100vh;
  height: 100dvh;
  display: flex;
  align-items: stretch;
  justify-content: flex-end;
  padding: 0;
  overflow: hidden;
  background: var(--bg);
}
.login-bg { position: absolute; left: 0; top: 0; width: 66.6667%; height: 100%;
  z-index: 0; pointer-events: none; }
.quote { position: absolute; left: 50%; transform: translateX(-50%); z-index: 1; margin: 0;
  font-size: 13px; letter-spacing: 4px; color: var(--sh); white-space: nowrap; user-select: none; }
.quote-pc { left: 33.3333%; transform: translateX(-50%); bottom: 4.5%; }
.quote-m { display: none; }

/* PC：右侧 1/3 宽登录侧栏，上/下/右贴边无间隙（保持原布局） */
.login-panel {
  position: relative; z-index: 2;
  width: 33.3333%;
  min-width: 340px;
  display: flex; flex-direction: column; justify-content: center;
  padding: 48px 52px;
  background: rgba(255, 255, 255, .82);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  border-left: 1px solid rgba(23, 37, 58, .10);
  box-shadow: -24px 0 70px rgba(20, 35, 60, .16);
}
html[data-theme="dark"] .login-panel { background: rgba(20, 26, 36, .84); border-left-color: rgba(255, 255, 255, .08); }
.panel-head { display: flex; align-items: center; gap: 13px; margin-bottom: 22px; }
.panel-head .mk {
  width: 46px; height: 46px; border-radius: 12px; flex: none;
  background: var(--acc-soft); border: 1px solid rgba(var(--acc-rgb), .3);
  display: flex; align-items: center; justify-content: center;
  color: var(--acc); font-weight: 800; font-size: 22px;
}
.panel-head .pt { font-size: 15px; font-weight: 700; line-height: 1.35; }
.panel-head .ps { font-size: 11.5px; color: var(--mut); margin-top: 3px; letter-spacing: .5px; }

.login-logo { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }
.login-title { font-size: 17px; font-weight: 700; }
.phase { font-size: 12px; color: var(--mut); display: flex; align-items: center; gap: 5px; }
.turn-dot { width: 9px; height: 9px; border-radius: 50%; background: #14181F; border: 1px solid rgba(255, 255, 255, .5); box-shadow: 0 0 0 1px rgba(0, 0, 0, .35); }
.turn-dot.wk2 { background: #fff; border-color: rgba(0, 0, 0, .3); box-shadow: 0 0 0 1px rgba(255, 255, 255, .7); }

.fld { display: block; margin-bottom: 14px; }
.fl { display: block; font-size: 12.5px; color: var(--mut); margin-bottom: 6px; font-weight: 600; }
.login-btn { width: 100%; padding: 12px; font-size: 15px; margin-top: 6px; }
.login-err { color: var(--err); font-size: 12.5px; margin: 0 0 10px; }
.login-tip { text-align: center; font-size: 12px; color: var(--mut); margin-top: 16px; }

@media (max-width: 899px) {
  .login-page { justify-content: center; align-items: center; padding: 22px 16px; }
  .login-bg { width: 100%; }
  .quote-pc { display: none; }
  .quote-m { display: block; position: static; transform: none;
    text-align: center; font-size: 12px; letter-spacing: 3px; margin-bottom: 14px; }
  .login-panel {
    position: relative; z-index: 2; width: 100%; max-width: 380px; margin: 0;
    min-width: 0; display: block; justify-content: initial;
    padding: 26px 26px 22px;
    background: rgba(255, 255, 255, .40);
    border: 1px solid rgba(255, 255, 255, .7);
    border-radius: 18px;
    box-shadow: 0 24px 70px rgba(20, 35, 60, .28);
    -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  }
  html[data-theme="dark"] .login-panel { background: rgba(20, 26, 36, .44); border-color: rgba(255, 255, 255, .10); }
}
</style>