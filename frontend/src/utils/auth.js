// 当前登录用户角色工具：localStorage 由登录时写入 { name, role }
export function curUser() {
  try { return JSON.parse(localStorage.getItem('user')) || {} } catch { return {} }
}

export function curRole() {
  const r = curUser().role
  // 兼容旧版本 localStorage 里存的「管理员」中文角色
  if (r === '管理员') return 'admin'
  if (r === '只读') return 'viewer'
  return r || 'admin'
}

export const isAdmin = () => curRole() === 'admin'