<template>
  <div class="login-page">
    <canvas ref="bgCanvas" class="login-bg"></canvas>

    <div class="login-frame">
      <aside class="login-side">
        <span class="deco d1"></span>
        <span class="deco d2"></span>
        <span class="deco d3"></span>
        <div class="side-inner">
          <div class="mk">壹</div>
          <h1 class="st-title">壹健康 · 检查报告管理系统</h1>
          <p class="st-sub">报告 · 用药 · AI · 文件，一站式管理</p>
          <ul class="st-feats">
            <li>检查报告模板一键套用</li>
            <li>用药记录趋势可视化</li>
            <li>AI 智能问答与配置</li>
            <li>文件归档与安全存储</li>
          </ul>
        </div>
      </aside>

      <div class="login-col">
        <div class="login-card">
          <div class="m-brand">
            <div class="mk">壹</div>
            <div class="mt">壹健康 · 检查报告管理系统</div>
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

// ── 棋盘背景：健康如对弈，白黑交错、步步为营 ──
const bgCanvas = ref(null)
let raf = 0
let ctl = null

onMounted(() => { ctl = startBoard(bgCanvas.value) })
onBeforeUnmount(() => { if (raf) cancelAnimationFrame(raf); if (ctl) ctl.stop() })

function startBoard(cv) {
  if (!cv) return null
  const ctx = cv.getContext('2d')
  const COLS = 15
  const stones = []
  let W = 0, H = 0, g = 10, rows = 30, yOff = 0
  let time = 0, nextSpawn = 400, turn = 0
  let acc = '90,146,229'

  const readAccent = () => {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--acc-rgb').trim()
    if (v) acc = v.replace(/\s+/g, '')
  }
  readAccent()

  const rnd = (a, b) => a + Math.random() * (b - a)
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    W = innerWidth; H = innerHeight
    cv.width = W * dpr; cv.height = H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    g = Math.max(16, Math.floor(W / (COLS - 1)))
    rows = Math.max(12, Math.floor(H / g))
    yOff = (H - (rows - 1) * g) / 2 - g * 0.5
  }
  resize()
  window.addEventListener('resize', resize)

  // 开局预置：几颗星位残子，画面不空
  for (let i = 0; i < 12; i++) {
    stones.push({
      x: 0, y: 0, r: 0, kind: i % 2, landed: true,
      bounce: 0, fadeAt: 0, dead: false, ripple: 0,
    })
    const s = stones[stones.length - 1]
    s.c = Math.floor(rnd(0, COLS)); s.rw = Math.floor(rnd(1, rows - 3))
    s.x = s.c * g; s.y = yOff + s.rw * g; s.r = g * 0.42
    s.setAt = performance.now()
  }

  const spawn = () => {
    const c = Math.floor(rnd(0, COLS))
    const rw = Math.floor(rnd(2, Math.max(5, rows - 6)))
    stones.push({
      x: c * g, y: yOff - 40, r: g * 0.42, kind: turn, landed: false,
      vy: rnd(3.4, 6.0), bounce: 0, yT: yOff + rw * g,
      ripple: 0, fadeAt: 0, dead: false, setAt: performance.now(),
      c, rw,
    })
    turn = 1 - turn
    if (stones.length > 110) stones.splice(0, stones.length - 110)
  }

  const loop = (ts) => {
    raf = requestAnimationFrame(loop)
    const dt = Math.min(ts - (time || ts), 50)
    time = ts

    // 产子
    nextSpawn -= dt
    if (nextSpawn <= 0) { spawn(); nextSpawn = rnd(520, 1250) }

    // 棋子物理
    const now = performance.now()
    for (const s of stones) {
      if (s.dead) continue
      if (!s.landed) {
        s.y += s.vy * dt * 0.06
        if (s.y >= s.yT) {
          s.y = s.yT
          if (s.bounce < 2 && s.vy > 1.1) { s.vy = -s.vy * 0.42; s.bounce++; s.ripple = 1 }
          else { s.landed = true; s.ripple = 1; s.fadeAt = now + rnd(9000, 16000) }
        }
      } else if (s.fadeAt && now > s.fadeAt + 2400) {
        s.dead = true
      }
    }
    if (stones.length && stones[0].dead) stones.shift()

    // 涟漪衰减
    for (const s of stones) if (s.ripple > 0) s.ripple = Math.max(0, s.ripple - dt / 620)

    // ── 绘制 ──
    ctx.clearRect(0, 0, W, H)
    const alphaFor = (s) => {
      if (!s.fadeAt) return 1
      const k = (now - s.fadeAt) / 2400
      return k >= 1 ? 0 : Math.max(0, 1 - k)
    }

    // 1) 基础网格（细线，缓呼吸）
    const breath = 0.05 + 0.02 * Math.sin(ts * 0.0011)
    ctx.strokeStyle = 'rgba(255,255,255,' + breath.toFixed(3) + ')'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let c = 0; c < COLS; c++) {
      const x = c * g
      ctx.moveTo(x, yOff - g); ctx.lineTo(x, yOff + (rows - 1) * g + g)
    }
    for (let r = 0; r < rows; r++) {
      const y = yOff + r * g
      ctx.moveTo(-g, y); ctx.lineTo(W + g, y)
    }
    ctx.stroke()

    // 2) 线条流动：光点沿格线滑动（dash 动画）
    ctx.setLineDash([2, 26])
    ctx.lineDashOffset = -(time * 0.045)
    ctx.strokeStyle = 'rgba(255,255,255,.16)'
    ctx.beginPath()
    for (let c = 0; c < COLS; c++) {
      const x = c * g
      ctx.moveTo(x, yOff - g); ctx.lineTo(x, yOff + (rows - 1) * g + g)
    }
    for (let r = 0; r < rows; r++) {
      const y = yOff + r * g
      ctx.moveTo(-g, y); ctx.lineTo(W + g, y)
    }
    ctx.stroke()
    ctx.setLineDash([])

    // 3) 主题色扫描光带（十字，穿过整个棋局）
    const sweep = ((time * 0.09) % (W + 360)) - 180
    const vg = ctx.createLinearGradient(sweep - 90, 0, sweep + 90, 0)
    vg.addColorStop(0, 'rgba(' + acc + ',0)')
    vg.addColorStop(0.5, 'rgba(' + acc + ',.10)')
    vg.addColorStop(1, 'rgba(' + acc + ',0)')
    ctx.fillStyle = vg
    ctx.fillRect(sweep - 90, 0, 180, H)
    const sweepY = ((time * 0.06) % (H + 360)) - 180
    const hg = ctx.createLinearGradient(0, sweepY - 90, 0, sweepY + 90)
    hg.addColorStop(0, 'rgba(' + acc + ',0)')
    hg.addColorStop(0.5, 'rgba(' + acc + ',.09)')
    hg.addColorStop(1, 'rgba(' + acc + ',0)')
    ctx.fillStyle = hg
    ctx.fillRect(0, sweepY - 90, W, 180)

    // 4) 棋子：白黑交错 + 落地涟漪
    for (const s of stones) {
      const al = alphaFor(s)
      if (al <= 0) continue
      // 落子投影
      ctx.fillStyle = 'rgba(0,0,0,.35)'
      ctx.beginPath()
      ctx.ellipse(s.x, s.y + s.r * 0.62, s.r * 0.85, s.r * 0.28, 0, 0, Math.PI * 2)
      ctx.fill()
      // 涟漪
      if (s.ripple > 0) {
        ctx.strokeStyle = 'rgba(255,255,255,' + (s.ripple * 0.55).toFixed(3) + ')'
        ctx.lineWidth = 1.6
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r + (1 - s.ripple) * 14, 0, Math.PI * 2)
        ctx.stroke()
      }
      // 棋子本体（白/黑 + 立体高光）
      ctx.globalAlpha = al
      if (s.kind === 0) {
        const gr = ctx.createRadialGradient(s.x - s.r * 0.32, s.y - s.r * 0.34, s.r * 0.12, s.x, s.y, s.r)
        gr.addColorStop(0, '#ffffff'); gr.addColorStop(0.55, '#eef2f6'); gr.addColorStop(1, '#c8d2dd')
        ctx.fillStyle = gr
      } else {
        const gr = ctx.createRadialGradient(s.x - s.r * 0.32, s.y - s.r * 0.34, s.r * 0.12, s.x, s.y, s.r)
        gr.addColorStop(0, '#3d4653'); gr.addColorStop(0.6, '#1e252e'); gr.addColorStop(1, '#0d1117')
        ctx.fillStyle = gr
      }
      ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill()
      // 黑子 rim 高光，暗底可辨
      if (s.kind === 1) {
        ctx.strokeStyle = 'rgba(255,255,255,.30)'; ctx.lineWidth = 1
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r - 0.4, 0, Math.PI * 2); ctx.stroke()
      }
      ctx.globalAlpha = 1
    }

    window.__boardStones = stones.filter(s => !s.dead && (s.landed || true)).length
  }

  raf = requestAnimationFrame(loop)
  return { stop() { cancelAnimationFrame(raf); window.removeEventListener('resize', resize) } }
}

async function doLogin() {
  if (loading.value) return
  err.value = ''
  loading.value = true
  try {
    const data = await authApi.login({ username: username.value.trim(), password: password.value })
    localStorage.setItem('token', data.access_token)
    // 同步昵称/头像到响应式用户状态（右上角立即显示，无需刷新）
    applyUserFromApi(data.user || {})
    // 登录成功后必须清掉上一次的权限缓存（未登录时 App 挂载曾拉过空的权限并置 loaded=true），
    // 否则路由守卫认为"已加载"而跳过拉取，菜单会只剩首页，需手动刷新才恢复
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
  background: radial-gradient(1200px 720px at 68% 24%, #16222f 0%, #0d141c 55%, #0a1016 100%);
}
.login-bg {
  position: absolute; inset: 0; width: 100%; height: 100%;
  z-index: 0; pointer-events: none;
}
.login-frame { position: relative; z-index: 1; width: 100%; max-width: 380px; }
.login-side { display: none; }
.login-card {
  width: 100%;
  max-width: 380px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: 0 14px 40px rgba(15, 23, 42, .12);
  padding: 32px 30px 26px;
}
.m-brand { display: block; text-align: center; margin-bottom: 20px; }
.m-brand .mk {
  width: 46px; height: 46px; margin: 0 auto 10px; border-radius: 12px;
  background: var(--card); border: 1px solid var(--acc);
  display: flex; align-items: center; justify-content: center;
  color: var(--acc); font-weight: 800; font-size: 22px;
}
.m-brand .mt { font-size: 14.5px; font-weight: 650; }
@media (min-width: 900px) {
  .login-page { padding: 30px; }
  .login-frame {
    display: flex;
    max-width: 940px;
    min-height: 540px;
    background: rgba(18, 26, 36, .30);
    -webkit-backdrop-filter: blur(8px);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, .14);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 24px 60px rgba(0, 0, 0, .4);
  }
  /* ── 左侧品牌区（主题色渐变，随主题色板联动）── */
  .login-side {
    display: flex;
    flex: 1.08;
    position: relative;
    color: #fff;
    background: linear-gradient(160deg, var(--acc) 0%, rgba(var(--acc-rgb), .72) 58%, rgba(var(--acc-rgb), .9) 100%);
    overflow: hidden;
  }
  .side-inner { position: relative; z-index: 2; margin: auto; padding: 48px 0 48px 52px; max-width: 360px; }
  .login-side .mk {
    width: 56px; height: 56px; border-radius: 14px; margin-bottom: 28px;
    background: rgba(255, 255, 255, .16); border: 1px solid rgba(255, 255, 255, .35);
    display: flex; align-items: center; justify-content: center;
    color: #fff; font-weight: 800; font-size: 28px;
  }
  .st-title { font-size: 22px; font-weight: 700; line-height: 1.45; margin: 0 0 10px; }
  .st-sub { font-size: 13px; opacity: .85; margin: 0 0 36px; }
  .st-feats { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 14px; }
  .st-feats li { font-size: 13.5px; display: flex; align-items: center; gap: 9px; opacity: .92; }
  .st-feats li::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #fff; flex: none; opacity: .9; }
  .deco { position: absolute; border-radius: 50%; background: rgba(255, 255, 255, .10); pointer-events: none; }
  .deco.d1 { width: 280px; height: 280px; top: -90px; right: -70px; }
  .deco.d2 { width: 180px; height: 180px; bottom: -60px; left: -50px; background: rgba(255, 255, 255, .08); }
  .deco.d3 { width: 90px; height: 90px; top: 44%; left: 14%; background: rgba(255, 255, 255, .06); }
  /* ── 右侧账号密码区（浮在棋盘上的玻璃白卡）── */
  .login-col { flex: 1; display: flex; align-items: center; justify-content: center; padding: 44px 48px; }
  .login-card {
    max-width: 340px;
    box-shadow: 0 22px 60px rgba(0, 0, 0, .38);
    border-radius: 14px;
    padding: 34px 32px 28px;
  }
  .m-brand { display: none; }
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
