<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AiBall from './components/AiBall.vue'

const route = useRoute()

// 折叠侧栏（记忆偏好）
import { loadPerms, hasPerm, permState } from './utils/perm'
import { userState, loadUser, clearUser, avatarUrl, applyUserFromApi } from './utils/user'
import { authApi } from './api'
const collapsed = ref(localStorage.getItem('sb') === '1')
function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem('sb', collapsed.value ? '1' : '0')
}

// 导航（perm 为需要的权限点；无 perm 表示对所有登录用户可见）
const menu = [
  { page: 'home', lbl: '首页', title: '首页', ico: 'M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z' },
  { page: 'tpl', lbl: '报告模板', title: '报告模板', perm: 'page.tpl', ico: 'M6 3h9l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v5h5M9 13h6M9 17h6' },
  { page: 'ai', lbl: 'AI 配置', title: 'AI 配置', perm: 'page.ai', ico: 'M9 3h6l-1.5 6H17l-8 12 1.5-8H5z' },
  { page: 'report', lbl: '检查报告', title: '检查报告', perm: 'page.report', ico: 'M12 3l8 4v6c0 4-3 7-8 8-5-1-8-4-8-8V7zM9 12l2 2 4-4' },
  { page: 'med', lbl: '用药记录', title: '用药记录', perm: 'page.med', ico: 'M9 3h6v4h5v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7h5zM12 10v6M9 13h6' },
  { page: 'files', lbl: '文件存储', title: '文件存储', perm: 'page.files', ico: 'M4 7l2-3h5l2 3h7a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z' },
  { page: 'users', lbl: '用户管理', title: '用户管理', perm: 'page.users', ico: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0' },
  { page: 'perms', lbl: '权限管理', title: '权限管理', perm: 'page.perms', ico: 'M12 1l2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4L4.2 6.7l5.4-.8z' },
]

// 主题
const theme = ref(localStorage.getItem('theme') || 'light')
const darkIco = 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z'
const lightIco = 'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4'
const applyTheme = () => {
  const m = window.matchMedia('(prefers-color-scheme: dark)')
  const actual = theme.value === 'system' ? (m.matches ? 'dark' : 'light') : theme.value
  document.documentElement.setAttribute('data-theme', actual)
}
function setTheme(v) { theme.value = v; localStorage.setItem('theme', v); tdrop.value = false; applyTheme() }
const tdrop = ref(false)
const udrop = ref(false)

// 当前登录用户：响应式共享状态（登录后无需刷新即可更新昵称/头像）
loadUser()
const displayName = () => userState.name || userState.username || '未登录'
const initial = () => (displayName().trim()[0] || '?')
const roleLbl = (r) => {
  if (permState.roleName) return permState.roleName
  const code = r || userState.role
  if (code === 'admin') return '超级管理员'
  if (code === 'viewer') return '只读'
  return code || '—'
}
const avatarSrc = () => avatarUrl(userState.avatar, userState.avatarTs)
const VERSION = 'v1.3.0'

// 退出登录
const router = useRouter()
function logout() {
  localStorage.removeItem('token')
  clearUser()
  udrop.value = false
  router.replace('/login')
}

// 面包屑
const crumbs = ref([])
function renderCrumb() {
  const t = route.meta.title || '首页'
  crumbs.value = t === '首页' ? ['首页'] : ['首页', t]
}

onMounted(() => {
  applyTheme()
  // 未登录时不拉权限：否则会把空权限当成"已加载"，登录后菜单不刷新（需手动刷新页面）
  if (localStorage.getItem('token') && !permState.loaded) loadPerms()
  if (localStorage.getItem('token')) {
    // 用后端最新资料校正昵称/头像（管理员可能改过昵称）
    authApi.me().then((u) => applyUserFromApi(u)).catch(() => {})
  }
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (theme.value === 'system') applyTheme()
  })
  renderCrumb()

  // ── 弹窗打开时锁定背景滚动（修复弹窗内容滑动带动页面滚动的穿透问题）──
  // 监测任意弹窗遮罩（含底部操作菜单）的显示/关闭，切换 body.modal-open
  // 移动端表单：label 列宽基线 116px，仅当某 label 更长时放大（--fl-w），保证全站名称列右端对齐
  function measureFormLabels() {
    requestAnimationFrame(() => {
      document.querySelectorAll('.fgrid').forEach((g) => {
        if (!g.isConnected) return
        const r = g.getBoundingClientRect()
        if (r.width === 0 && r.height === 0) return
        let w = 116
        g.querySelectorAll('.field .flabel').forEach((l) => {
          if (l.scrollWidth > w) w = l.scrollWidth
        })
        g.style.setProperty('--fl-w', w + 'px')
      })
    })
  }
  const refreshUi = () => {
    const open =
      !!document.querySelector('.modal-mask.show') ||
      !!document.querySelector('.rp-sheet-mask')
    document.body.classList.toggle('modal-open', open)
    requestAnimationFrame(measureFormLabels)
  }
  const lockScroll = new MutationObserver(refreshUi)
  lockScroll.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] })
  // 首屏表单（如个人资料页）也要对齐
  requestAnimationFrame(measureFormLabels)
  // iOS 兜底：弹窗打开时拦截弹窗外的 touchmove，避免背景页被拖动
  document.addEventListener(
    'touchmove',
    (e) => {
      if (!document.body.classList.contains('modal-open')) return
      if (e.target.closest && e.target.closest('.modal, .rp-sheet, .img-viewer')) return
      e.preventDefault()
    },
    { passive: false }
  )
})
</script>

<template>
  <div v-if="route.name === 'login'" class="login-app">
    <RouterView />
  </div>

  <div v-else class="app" :class="{ 'sb-collapsed': collapsed }">
    <aside class="sidebar">
      <div class="logo">
        <div class="mk">壹</div>
        <div><b>壹健康</b><span>检查报告管理系统</span></div>
      </div>
      <ul class="nav" id="nav">
        <li v-for="m in menu.filter((x) => x.perm ? hasPerm(x.perm) : true)" :key="m.page">
          <RouterLink :to="'/' + m.page" :title="m.title" :class="{ on: route.path === '/' + m.page }">
            <svg class="ico" viewBox="0 0 24 24"><path :d="m.ico" /></svg>
            <span class="lbl">{{ m.lbl }}</span>
          </RouterLink>
        </li>
      </ul>
      <div class="ver" title="系统版本（部署后请强制刷新以加载新版）">{{ VERSION }}</div>
    </aside>

    <main class="side-main">
      <header class="g-topbar">
        <div class="gb-left">
          <button class="gb-toggle" id="sbToggle" @click="toggleSidebar" title="折叠 / 展开侧边栏">
            <svg class="ico" viewBox="0 0 24 24"><path d="M4 5h16M4 12h10M4 19h16" /></svg>
          </button>
          <nav class="crumb">
            <template v-for="(c, i) in crumbs" :key="i">
              <span v-if="i > 0" class="sep"> / </span>
              <a class="cur">{{ c }}</a>
            </template>
          </nav>
        </div>

        <div class="theme-wrap">
          <button class="gb-toggle" id="themeBtn" title="切换主题" @click="tdrop = !tdrop">
            <svg class="ico" viewBox="0 0 24 24"><path :d="theme === 'light' ? lightIco : darkIco" /></svg>
          </button>
          <div class="tdrop" :class="{ open: tdrop }">
            <button :class="{ on: theme === 'light' }" @click="setTheme('light')"><span class="t-dot"></span>亮色</button>
            <button :class="{ on: theme === 'dark' }" @click="setTheme('dark')"><span class="t-dot"></span>暗色</button>
            <button :class="{ on: theme === 'system' }" @click="setTheme('system')"><span class="t-dot"></span>跟随系统</button>
          </div>
        </div>

        <div class="userbox">
          <div class="usub"><b>{{ displayName() }}</b><span>{{ roleLbl() }}</span></div>
          <button class="avatar" @click="udrop = !udrop" :title="displayName()">
            <img v-if="avatarSrc()" :src="avatarSrc()" alt="头像">
            <span v-else>{{ initial() }}</span>
          </button>
          <div class="udrop" :class="{ open: udrop }">
            <div class="uname">{{ displayName() }} · {{ roleLbl() }}</div>
            <hr>
            <RouterLink to="/profile" @click="udrop = false">个人中心</RouterLink>
            <RouterLink v-if="hasPerm('page.settings')" to="/settings" @click="udrop = false">系统设置</RouterLink>
            <hr>
            <button class="dan" @click="logout">退出登录</button>
          </div>
        </div>
      </header>

      <RouterView v-slot="{ Component }">
        <component :is="Component" />
      </RouterView>
    </main>

    <!-- AI 问数悬浮球（全局常显） -->
    <AiBall />
  </div>
</template>