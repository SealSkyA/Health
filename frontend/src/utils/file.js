/**
 * 文件转 data URL（base64），用于以 JSON 方式上传，规避部分网络对
 * multipart/form-data 的拦截。
 */
export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onload = () => resolve(String(fr.result || ''))
    fr.onerror = () => reject(new Error('读取图片失败'))
    fr.readAsDataURL(file)
  })
}