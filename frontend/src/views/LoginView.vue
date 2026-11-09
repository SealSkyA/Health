<template>
  <div class="login-page">
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
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../api/index.js'
import { resetPerms } from '../utils/perm'
import { applyUserFromApi } from '../utils/user'

const router = useRouter()
const username = ref('')
const password = ref('')
const err = ref('')
const loading = ref(false)

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
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: var(--bg);
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
  padding: 32px 30px 26px;
}
@media (min-width: 900px) {
  .login-page { padding: 30px; }
  .login-frame {
    display: flex;
    max-width: 940px;
    min-height: 540px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 24px 60px rgba(15, 23, 42, .14);
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
  /* ── 右侧账号密码区 ── */
  .login-col { flex: 1; display: flex; align-items: center; justify-content: center; padding: 44px 48px; }
  .login-card { max-width: 340px; box-shadow: none; border: 0; background: transparent; padding: 0; }
  .login-logo { text-align: left; margin-bottom: 26px; }
  .login-title { font-size: 20px; font-weight: 700; }
}
.login-logo { text-align: center; margin-bottom: 24px; }
.login-title { font-size: 17px; font-weight: 650; letter-spacing: .3px; }
.fld { display: block; margin-bottom: 16px; }
.fl { display: block; font-size: 12.5px; color: var(--mut); margin-bottom: 6px; font-weight: 600; }
.login-btn { width: 100%; padding: 12px; font-size: 15px; margin-top: 6px; }
.login-err { color: var(--err); font-size: 12.5px; margin: 0 0 10px; }
.login-tip { text-align: center; font-size: 12px; color: var(--mut); margin-top: 18px; }
</style>
