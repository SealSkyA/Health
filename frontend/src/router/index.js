import { createRouter, createWebHashHistory } from 'vue-router'
import { loadPerms, hasPerm, permState, resetPerms } from '../utils/perm'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { title: '登录' } },
  { path: '/', redirect: '/home' },
  { path: '/home', name: 'home', component: () => import('../views/HomeView.vue'), meta: { title: '首页', auth: true } },
  { path: '/tpl', name: 'tpl', component: () => import('../views/TplView.vue'), meta: { title: '报告模板', auth: true, perm: 'page.tpl' } },
  { path: '/ai', name: 'ai', component: () => import('../views/AiView.vue'), meta: { title: 'AI 配置', auth: true, perm: 'page.ai' } },
  { path: '/report', name: 'report', component: () => import('../views/ReportView.vue'), meta: { title: '检查报告', auth: true, perm: 'page.report' } },
  { path: '/med', name: 'med', component: () => import('../views/MedView.vue'), meta: { title: '用药记录', auth: true, perm: 'page.med' } },
  { path: '/files', name: 'files', component: () => import('../views/FilesView.vue'), meta: { title: '文件存储', auth: true, perm: 'page.files' } },
  { path: '/users', name: 'users', component: () => import('../views/UserView.vue'), meta: { title: '用户管理', auth: true, perm: 'page.users' } },
  { path: '/perms', name: 'perms', component: () => import('../views/PermView.vue'), meta: { title: '权限管理', auth: true, perm: 'page.perms' } },
  { path: '/profile', name: 'profile', component: () => import('../views/ProfileView.vue'), meta: { title: '个人中心', auth: true } },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置', auth: true, perm: 'page.settings' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 全局守卫：未登录跳登录；首次进入加载权限；按页面权限拦截
router.beforeEach(async (to) => {
  const token = localStorage.getItem('token')
  if (to.name === 'login') {
    resetPerms()
    // 已有 token：直接回首页（token 无效会在首次权限拉取时被 401 踢回登录页）
    if (token) return { name: 'home' }
  }
  if (to.meta.auth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (token && (!permState.loaded || !permState.role)) {
    await loadPerms()
  }
  if (to.meta.perm && token && !hasPerm(to.meta.perm)) {
    return { name: 'home' }
  }
  return true
})

export default router