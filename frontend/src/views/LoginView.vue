<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">
        <div class="mk">壹</div>
        <div class="login-title">壹健康 · 检查报告管理系统</div>
        <div class="login-sub">请登录以继续</div>
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
.login-card {
  width: 100%;
  max-width: 380px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: 0 14px 40px rgba(15, 23, 42, .12);
  padding: 32px 30px 26px;
}
.login-logo { text-align: center; margin-bottom: 24px; }
.login-logo .mk {
  width: 52px; height: 52px; margin: 0 auto 14px; border-radius: 12px;
  background: var(--card); border: 1px solid var(--acc);
  display: flex; align-items: center; justify-content: center;
  color: var(--acc); font-weight: 800; font-size: 26px;
}
.login-title { font-size: 17px; font-weight: 650; letter-spacing: .3px; }
.login-sub { font-size: 12px; color: var(--mut); margin-top: 6px; }
.fld { display: block; margin-bottom: 16px; }
.fl { display: block; font-size: 12.5px; color: var(--mut); margin-bottom: 6px; font-weight: 600; }
.login-btn { width: 100%; padding: 12px; font-size: 15px; margin-top: 6px; }
.login-err { color: var(--err); font-size: 12.5px; margin: 0 0 10px; }
.login-tip { text-align: center; font-size: 12px; color: var(--mut); margin-top: 18px; }
</style>
