// AI 分析文本的 Markdown 渲染（安全子集）
// - 链接 / 图片语法一律转为纯文本（避免 href 注入与外跳）
// - 原始 HTML 特殊字符转义，仅允许 Markdown 语法生成的标签
import { marked } from 'marked'

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
))

// 把 [文字](链接) / ![说明](链接) 转为纯文本文字（保留链接描诉）
const toPlainLinks = (s) => String(s)
  .replace(/!\[([^\]]*)\]\((https?:[^)\s]+|#[^\s)]+)\)/g, '$1')
  .replace(/\[([^\]]*)\]\((https?:[^)\s]+|#[^\s)]+)\)/g, '$1（$2）')

export function mdToHtml(src = '') {
  if (!src) return ''
  const safe = toPlainLinks(esc(src))
  return marked.parse(safe, { gfm: true, breaks: true })
}