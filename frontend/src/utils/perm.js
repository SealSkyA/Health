// 当前用户权限状态（RBAC）：登录/刷新后从后端拉取，供菜单、路由、按钮权限判断
import { reactive } from 'vue'
import { authApi } from '../api'

export const permState = reactive({
  loaded: false,   // 是否已从后端加载
  role: '',        // 角色编码（admin/viewer/自定义）
  roleName: '',    // 角色显示名
  perms: [],       // 权限点列表
})

// 进入登录页 / 切换账号时调用，确保下次登录重新拉取权限
export function resetPerms() {
  permState.loaded = false
  permState.role = ''
  permState.roleName = ''
  permState.perms = []
}

export async function loadPerms() {
  try {
    const r = await authApi.myPermissions()
    permState.role = r.role || ''
    permState.roleName = r.role_name || ''
    permState.perms = Array.isArray(r.perms) ? r.perms : []
  } catch {
    // 后端异常降级：
    // 1) 会话仍有效（token 还在）且本地记录的账号是 admin → admin 后端恒全权，可安全兜底，
    //    避免"服务重启/网络抖动瞬间超级管理员只剩首页"；后续请求若真的无权限会被后端 401/403 拦住。
    // 2) token 已被 401 拦截器清除 → 置空，由路由守卫跳回登录页。
    let lu = null
    try { lu = JSON.parse(localStorage.getItem('user') || 'null') } catch { /* ignore */ }
    if (localStorage.getItem('token') && lu && lu.role === 'admin') {
      permState.role = 'admin'
      permState.roleName = '管理员'
      permState.perms = []
      permState.loaded = true
      return
    }
    permState.role = ''
    permState.roleName = ''
    permState.perms = []
  } finally {
    permState.loaded = true
  }
}

// admin 超管恒拥有全部权限
export const hasPerm = (key) => permState.role === 'admin' || permState.perms.includes(key)