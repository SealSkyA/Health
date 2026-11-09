<template>
  <div class="login-page">
    <div class="login-frame">
      <!-- PC 左栏：品牌 + 对弈棋盘 -->
      <aside class="login-side">
        <div class="side-top">
          <div class="mk">壹</div>
          <h1 class="st-title">壹健康 · 检查报告管理系统</h1>
          <ul class="st-feats">
            <li>检查报告模板一键套用</li>
            <li>用药记录趋势可视化</li>
            <li>AI 智能问答与配置</li>
            <li>文件归档与安全存储</li>
          </ul>
        </div>
        <div class="board-box">
          <div class="b-cap"><span class="cap-dot wk"></span><b>{{ phaseText }}</b><span class="cap-dot bk"></span></div>
          <canvas ref="pcCanvas" class="board"></canvas>
          <div class="b-quote">健康如对弈，步步为营</div>
        </div>
      </aside>

      <!-- 右栏：账号密码区 -->
      <div class="login-col">
        <div class="login-card">
          <div class="m-board-box">
            <div class="b-cap m"><span class="cap-dot wk"></span><b>{{ phaseText }}</b><span class="cap-dot bk"></span></div>
            <canvas ref="mCanvas" class="board"></canvas>
            <div class="b-quote m">健康如对弈，步步为营</div>
          </div>

          <div class="login-logo">
            <div class="login-title">账号登录</div>
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

// ── 五子棋对弈：双 AI 博弈，健康如对弈 ──
const pcCanvas = ref(null)
const mCanvas = ref(null)
const phaseText = ref('黑方行棋')
let engine = null
let mq = null

onMounted(() => {
  mq = window.matchMedia('(min-width: 900px)')
  boot()
  if (mq.addEventListener) mq.addEventListener('change', boot)
  else mq.addListener(boot)
})
onBeforeUnmount(() => {
  stopEngine()
  if (mq && mq.removeEventListener) mq.removeEventListener('change', boot)
})

function stopEngine() { if (engine) { engine.stop(); engine = null } }
function boot() { stopEngine(); engine = createGame(mq.matches ? pcCanvas.value : mCanvas.value, setPhase) }
function setPhase(t) { phaseText.value = t }

function createGame(cv, onPhase) {
  if (!cv) return null
  const N = 15, ctx = cv.getContext('2d')
  const dirs = [[1, 0], [0, 1], [1, 1], [1, -1]]
  let bd = Array.from({ length: N }, () => Array(N).fill(0))
  let size = 0, g = 0, pad = 0
  let stones = [], cursor = null, winLine = null, over = false
  let acc = '90,146,229', raf = 0, stepT = 0, lastTs = 0
  let turn = 1 // 1 黑先

  const readAccent = () => {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--acc-rgb').trim()
    if (v) acc = v.replace(/\s+/g, '')
  }
  readAccent()

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    size = cv.clientWidth
    cv.width = size * dpr; cv.height = size * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    pad = Math.max(8, size * 0.035)
    g = (size - pad * 2) / (N - 1)
  }
  resize()
  window.addEventListener('resize', resize)

  // —— AI：攻防评分 ——
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
  function choose() {
    let bx = -1, by = -1, bs = -1
    const center = Math.floor(N / 2)
    // 空盘/稀疏：附近随机先手，避免固定开局
    let occupied = 0
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) if (bd[i][j]) occupied++
    if (occupied === 0) return [center, center]
    if (occupied === 1) {
      const cx = center + Math.floor(Math.random() * 3) - 1, cy = center + Math.floor(Math.random() * 3) - 1
      return [cx, cy]
    }
    const opp = -turn
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
      if (bd[i][j]) continue
      // 只看落子邻域，减少计算
      let near = false
      for (let a = -1; a <= 1 && !near; a++) for (let b = -1; b <= 1 && !near; b++) {
        const ii = i + a, jj = j + b
        if (ii >= 0 && ii < N && jj >= 0 && jj < N && bd[ii][jj]) near = true
      }
      if (!near) continue
      const atk = scorePos(i, j, turn)
      const def = scorePos(i, j, opp)
      if (atk >= weight[3] * 100) return [i, j]     // 成五
      if (def >= weight[3] * 100) return [i, j]     // 堵五
      let s = atk * 1.15 + def * 1.0
      s += (Math.random() - 0.5) * 0.06 * s         // 微幅随机，棋形不死板
      if (s > bs) { bs = s; bx = i; by = j }
    }
    return (bx < 0) ? [center, center] : [bx, by]
  }

  function checkWin(x, y) {
    for (const [dx, dy] of dirs) {
      const arr = []
      lineLen(x, y, dx, dy, turn, arr)
      if (arr.length >= 5) return arr
    }
    return null
  }

  function place(x, y) {
    bd[x][y] = turn
    const px = pad + x * g, py = pad + y * g
    stones.push({ x: px, y: py, r: g * 0.43, kind: turn, phase: 0, ripple: 0 })
    cursor = null
    const wl = checkWin(x, y)
    if (wl) {
      winLine = wl; over = true
      onPhase(turn === 1 ? '黑棋获胜' : '白棋获胜')
      if (stepT) clearTimeout(stepT)
      stepT = setTimeout(restart, 3200)
    } else {
      turn = -turn
      onPhase(turn === 1 ? '黑方行棋' : '白方行棋')
      if (stepT) clearTimeout(stepT)
      stepT = setTimeout(() => { const [cx, cy] = choose(); cursor = { x: pad + cx * g, y: pad + cy * g }; place(cx, cy) }, 1050 + Math.random() * 600)
    }
  }
  function restart() {
    bd = Array.from({ length: N }, () => Array(N).fill(0))
    stones = []; winLine = null; over = false; turn = 1
    onPhase('黑方行棋')
    const [cx, cy] = choose()
    cursor = { x: pad + cx * g, y: pad + cy * g }
    stepT = setTimeout(() => place(cx, cy), 900)
  }
  restart()

  function draw(ts) {
    raf = requestAnimationFrame(draw)
    const dt = Math.min(ts - (lastTs || ts), 50); lastTs = ts
    for (const s of stones) {
      if (s.phase < 1) s.phase = Math.min(1, s.phase + dt / 300)
      if (s.ripple > 0) s.ripple = Math.max(0, s.ripple - dt / 650)
    }
    ctx.clearRect(0, 0, size, size)
    // 盘面
    const bg = ctx.createRadialGradient(size / 2, size / 2, g, size / 2, size / 2, size / 1.5)
    bg.addColorStop(0, '#2B3643'); bg.addColorStop(1, '#212B36')
    ctx.fillStyle = bg
    ctx.fillRect(0, 0, size, size)
    // 网格
    ctx.strokeStyle = 'rgba(255,255,255,.15)'; ctx.lineWidth = 1
    ctx.beginPath()
    for (let i = 0; i < N; i++) {
      const p = pad + i * g
      ctx.moveTo(pad, p); ctx.lineTo(pad + (N - 1) * g, p)
      ctx.moveTo(p, pad); ctx.lineTo(p, pad + (N - 1) * g)
    }
    ctx.stroke()
    // 星位
    ctx.fillStyle = 'rgba(255,255,255,.38)'
    for (const [sx, sy] of [[3, 3], [11, 3], [7, 7], [3, 11], [11, 11]]) {
      ctx.beginPath(); ctx.arc(pad + sx * g, pad + sy * g, 2.4, 0, Math.PI * 2); ctx.fill()
    }
    // 行棋光标
    if (cursor && !over) {
      const ph = Math.sin(ts / 260) * 0.5 + 0.5
      ctx.strokeStyle = 'rgba(255,255,255,' + (0.28 + ph * 0.3).toFixed(2) + ')'
      ctx.lineWidth = 1.8
      ctx.beginPath(); ctx.arc(cursor.x, cursor.y, g * 0.55, 0, Math.PI * 2); ctx.stroke()
    }
    // 胜线
    if (winLine) {
      const x0 = pad + winLine[0][0] * g, y0 = pad + winLine[0][1] * g
      const x1 = pad + winLine[winLine.length - 1][0] * g, y1 = pad + winLine[winLine.length - 1][1] * g
      const fl = 0.5 + 0.5 * Math.sin(ts / 140)
      ctx.strokeStyle = 'rgba(' + acc + ',.95)'; ctx.lineWidth = 2.6
      ctx.shadowColor = 'rgba(' + acc + ',' + (0.5 + fl * 0.4).toFixed(2) + ')'
      ctx.shadowBlur = 8 * (0.6 + fl)
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke()
      ctx.shadowBlur = 0
    }
    // 棋子（淡入 + 水波，无坠落）
    for (const s of stones) {
      const r = s.r * (0.4 + 0.6 * s.phase)
      const inR = 1 - s.phase * 0.3
      ctx.globalAlpha = 0.25 + 0.75 * s.phase
      if (s.kind === 1) {
        const gr = ctx.createRadialGradient(s.x - r * 0.3, s.y - r * 0.34, r * 0.1, s.x, s.y, r)
        gr.addColorStop(0, '#3E4856'); gr.addColorStop(0.55, '#1B212B'); gr.addColorStop(1, '#0E1218')
        ctx.fillStyle = gr
      } else {
        const gr = ctx.createRadialGradient(s.x - r * 0.3, s.y - r * 0.34, r * 0.1, s.x, s.y, r)
        gr.addColorStop(0, '#FFFFFF'); gr.addColorStop(0.6, '#EEF1F5'); gr.addColorStop(1, '#C9D2DC')
        ctx.fillStyle = gr
      }
      ctx.beginPath(); ctx.arc(s.x, s.y, r * inR, 0, Math.PI * 2); ctx.fill()
      ctx.globalAlpha = 1
      if (s.kind === 1) { // 黑子细白描边，盘上可辨
        ctx.strokeStyle = 'rgba(255,255,255,.28)'; ctx.lineWidth = 1
        ctx.beginPath(); ctx.arc(s.x, s.y, r * inR - 0.5, 0, Math.PI * 2); ctx.stroke()
      }
      // 落子水波
      if (s.phase < 1) {
        ctx.strokeStyle = 'rgba(255,255,255,' + ((1 - s.phase) * 0.5).toFixed(2) + ')'
        ctx.lineWidth = 1.4
        ctx.beginPath(); ctx.arc(s.x, s.y, r + (1 - s.phase) * 10, 0, Math.PI * 2); ctx.stroke()
      }
    }
    window.__gameStones = stones.length
  }
  raf = requestAnimationFrame(draw)

  return { stop() { cancelAnimationFrame(raf); if (stepT) clearTimeout(stepT); window.removeEventListener('resize', resize) } }
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
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  overflow: hidden;
  background: linear-gradient(160deg, var(--bg) 0%, var(--card2) 100%);
}
.login-frame { width: 100%; max-width: 380px; }
.login-side { display: none; }
.login-card {
  width: 100%;
  max-width: 380px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: 0 14px 40px rgba(15, 23, 42, .12);
  padding: 28px 30px 24px;
}
/* 移动端：卡片顶部小棋盘 */
.m-board-box { margin: -6px auto 18px; width: 100%; max-width: 264px; text-align: center; }
.board { display: block; width: 100%; aspect-ratio: 1; border-radius: 10px; box-shadow: 0 10px 26px rgba(15, 23, 42, .25); }
.b-cap { display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 12.5px; color: var(--mut); margin: 0 0 8px; }
.b-cap b { font-weight: 650; }
.b-cap.m { color: var(--mut); }
.cap-dot { width: 9px; height: 9px; border-radius: 50%; }
.cap-dot.wk { background: #fff; border: 1px solid rgba(0, 0, 0, .3); box-shadow: 0 0 0 1px rgba(255, 255, 255, .6); }
.cap-dot.bk { background: #14181F; border: 1px solid rgba(255, 255, 255, .4); }
.b-quote { font-size: 11.5px; color: var(--mut); margin-top: 8px; letter-spacing: 1px; }
.b-quote.m { color: var(--sh); font-size: 11px; }

@media (min-width: 900px) {
  .login-page { padding: 30px; }
  .login-frame {
    display: flex;
    max-width: 1000px;
    min-height: 600px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 24px 60px rgba(15, 23, 42, .14);
  }
  /* ── 左栏：品牌 + 对弈棋盘 ── */
  .login-side {
    display: flex;
    flex: 1.1;
    flex-direction: column;
    gap: 18px;
    position: relative;
    color: #fff;
    padding: 40px 46px 34px;
    background: linear-gradient(160deg, var(--acc) 0%, rgba(var(--acc-rgb), .7) 60%, rgba(var(--acc-rgb), .9) 100%);
  }
  .side-top .mk {
    width: 50px; height: 50px; border-radius: 12px; margin-bottom: 18px;
    background: rgba(255, 255, 255, .16); border: 1px solid rgba(255, 255, 255, .35);
    display: flex; align-items: center; justify-content: center;
    color: #fff; font-weight: 800; font-size: 25px;
  }
  .st-title { font-size: 20px; font-weight: 700; line-height: 1.45; margin: 0 0 18px; }
  .st-feats { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 11px; }
  .st-feats li { font-size: 13px; display: flex; align-items: center; gap: 8px; opacity: .92; }
  .st-feats li::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: #fff; flex: none; opacity: .95; }
  .board-box { width: 100%; text-align: center; }
  .board-box .board { max-width: 340px; margin: 0 auto; border-radius: 12px; box-shadow: 0 16px 36px rgba(0, 0, 0, .35); }
  .b-cap { color: rgba(255, 255, 255, .95); font-size: 13px; margin-bottom: 10px; }
  .b-quote { color: rgba(255, 255, 255, .75); }
  .m-board-box { display: none; }
  /* ── 右栏：账号密码 ── */
  .login-col { flex: 1; display: flex; align-items: center; justify-content: center; padding: 44px 48px; }
  .login-card { max-width: 340px; box-shadow: none; border: 0; background: transparent; padding: 0; }
  .login-logo { text-align: left; margin-bottom: 26px; }
  .login-title { font-size: 20px; font-weight: 700; }
  .login-tip { color: var(--mut); }
}
.login-logo { text-align: center; margin-bottom: 24px; }
.login-title { font-size: 17px; font-weight: 650; letter-spacing: .3px; }
.fld { display: block; margin-bottom: 16px; }
.fl { display: block; font-size: 12.5px; color: var(--mut); margin-bottom: 6px; font-weight: 600; }
.login-btn { width: 100%; padding: 12px; font-size: 15px; margin-top: 6px; }
.login-err { color: var(--err); font-size: 12.5px; margin: 0 0 10px; }
.login-tip { text-align: center; font-size: 12px; color: var(--mut); margin-top: 18px; }
</style>