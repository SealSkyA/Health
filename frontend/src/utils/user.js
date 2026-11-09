// 当前登录用户状态（响应式）：登录 / 刷新资料后同步右上角头像与昵称
import { reactive } from 'vue'

export const userState = reactive({
  name: '',        // 显示名（昵称优先）
  username: '',
  role: '',
  avatar: '',      // 头像相对路径（avatars/x.jpg），空则显示昵称首字
  avatarTs: 0,     // 头像版本（覆盖同名文件后破除浏览器缓存）
})

/** 从 localStorage 恢复（App 首次挂载 / 刷新页面时） */
export function loadUser() {
  try {
    const u = JSON.parse(localStorage.getItem('user') || 'null')
    if (u) applyUser(u)
  } catch { /* ignore */ }
}

/** 写入状态 + localStorage */
export function applyUser(u) {
  if (!u) return
  const prev = userState.avatar
  userState.name = u.name || u.nickname || u.username || ''
  userState.username = u.username || ''
  userState.role = u.role || ''
  userState.avatar = u.avatar || ''
  if (userState.avatar && userState.avatar !== prev) userState.avatarTs = Date.now()
  try {
    localStorage.setItem('user', JSON.stringify({
      name: userState.name,
      username: userState.username,
      role: userState.role,
      avatar: userState.avatar,
    }))
  } catch { /* ignore */ }
}

/** 用后端 UserOut 更新（登录返回 /auth/me / 资料保存后） */
export function applyUserFromApi(u) {
  applyUser({
    name: u.nickname || u.username || '',
    username: u.username,
    role: u.role,
    avatar: u.avatar,
  })
}

export function clearUser() {
  userState.name = ''
  userState.username = ''
  userState.role = ''
  userState.avatar = ''
  userState.avatarTs = 0
  try {
    localStorage.removeItem('user')
  } catch { /* ignore */ }
}

/** 头像完整 URL（后端静态托管在 /static），带版本参数破除缓存 */
export function avatarUrl(p, ts) {
  if (!p) return ''
  const s = String(p)
  if (s.startsWith('http')) return s
  const base = s.startsWith('/') ? s : `/static/${s}`
  return ts ? `${base}?v=${ts}` : base
}
