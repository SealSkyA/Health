/**
 * 移动端系统返回键「逐级返回」层级栈
 *
 * 原理：
 *  - 每个弹层打开时，向浏览器历史 push 一个「哨兵条目」（{ bs: n }，与当前 URL 相同 hash）。
 *  - 用户按系统返回：浏览器退一步 → popstate 触发。若退到的是哨兵（e.state.bs 存在），
 *    说明本次返回对应某个弹层 → 关闭最上层弹层，不改变路由。
 *  - 当哨兵全部清空后再按返回：退到真实历史条目（hash 变化）→ 放行，由 vue-router 正常回退，
 *    实现「弹层先关 → 页面逐级回退」。
 *  - 手动关闭弹层（点遮罩/取消）时自动出栈并把本层哨兵替换为普通条目，保证历史顺序不被打乱。
 */
import { watch } from 'vue'

const stack = []      // 打开的弹层栈：[{ idx, close }]
let seq = 0
let listening = false

function onPop(e) {
  const st = e.state
  if (!st || typeof st.bs !== 'number') {
    // 退到了普通条目：若仍有弹层（历史中残留虚拟条目挡路），收敛一层；否则放行
    if (stack.length) {
      const top = stack.pop()
      try { top.close() } catch (err) { console.error('[backstack]', err) }
    }
    return
  }
  // 退到哨兵条目：关闭最上层弹层（不改变路由）
  if (stack.length) {
    const top = stack.pop()
    try { top.close() } catch (err) { console.error('[backstack]', err) }
  }
}

function ensureListener() {
  if (listening || typeof window === 'undefined') return
  listening = true
  window.addEventListener('popstate', onPop)
}

/**
 * 让「弹层开关（响应式源）」进入返回键层级栈。
 * @param src        () => boolean，弹层是否打开
 * @param closeFn    () => void，返回键/收敛时执行的关闭动作
 * @returns () => void 停止监听（组件卸载时调用）
 */
export function watchBack(src, closeFn) {
  let depth = null
  const check = () => {
    const open = src()
    if (open && depth === null) {
      seq += 1
      depth = seq
      ensureListener()
      try { history.pushState({ bs: depth }, '') } catch (e) {}
      stack.push({ idx: depth, close: closeFn })
    } else if (!open && depth !== null) {
      const i = stack.findIndex((x) => x.idx === depth)
      if (i >= 0) stack.splice(i, 1)
      // 让本层哨兵退化为普通条目，避免残留虚拟历史打乱后续返回顺序
      try {
        if (history.state && history.state.bs === depth) {
          history.replaceState({ bs: 0 }, '')
        }
      } catch (e) {}
      depth = null
    }
  }
  check()
  const stop = watch(src, check)
  return () => { stop(); }
}