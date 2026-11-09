<script setup>
import { ref, computed, onMounted } from 'vue'
import { authApi } from '../api'
import { userState, loadUser, applyUserFromApi, avatarUrl } from '../utils/user'

const toastMsg = ref('')
function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

// 基本资料
const profile = ref({ nickname: '', phone: '', email: '', org: '' })
const savingProfile = ref(false)
const uploading = ref(false)
const fileInput = ref(null)

// 头像预览（优先本地最新状态）
const avatarSrc = computed(() => avatarUrl(userState.avatar, userState.avatarTs))
const initial = computed(() => (profile.value.nickname || userState.name || '?').trim()[0] || '?')

// 修改密码
const pwdForm = ref({ old_password: '', new_password: '', confirm: '' })
const savingPwd = ref(false)

// 登录记录
const logs = ref([])

async function loadMe() {
  try {
    const u = await authApi.me()
    profile.value = {
      nickname: u.nickname || '',
      phone: u.phone || '',
      email: u.email || '',
      org: u.org || '',
      role: u.role,
    }
    applyUserFromApi(u)
  } catch (e) { /* 401 由拦截器处理 */ }
}

async function saveProfile() {
  savingProfile.value = true
  try {
    const u = await authApi.updateProfile(profile.value)
    applyUserFromApi(u)   // 右上角昵称立即同步
    toast('资料已保存')
  } catch (e) { toast('保存失败：' + (e.response?.data?.detail || e.message)) } finally { savingProfile.value = false }
}

function pickAvatar() { fileInput.value && fileInput.value.click() }

/** 读取图片并压缩到 ≤512px 的 data URL（头像无需原图，也避免超出大小限制） */
function readImageCompressed(file, maxSide = 512) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onerror = () => reject(new Error('读取文件失败'))
    fr.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('图片格式无法识别'))
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height))
        const w = Math.max(1, Math.round(img.width * scale))
        const h = Math.max(1, Math.round(img.height * scale))
        const cv = document.createElement('canvas')
        cv.width = w; cv.height = h
        cv.getContext('2d').drawImage(img, 0, 0, w, h)
        // 统一转 JPEG（透明背景填白），体积小且后端扩展名兜底为 .jpg
        resolve(cv.toDataURL('image/jpeg', 0.9))
      }
      img.src = fr.result
    }
    fr.readAsDataURL(file)
  })
}

async function onAvatarChange(e) {
  const f = e.target.files && e.target.files[0]
  e.target.value = ''            // 允许重复选同一文件
  if (!f) return
  if (!/^image\//.test(f.type)) { toast('请选择图片文件'); return }
  if (f.size > 8 * 1024 * 1024) { toast('图片不能超过 8MB'); return }
  uploading.value = true
  try {
    // 走 base64 JSON 接口：部分网络环境会重置 multipart 请求（表现为 Network Error）
    const dataUrl = await readImageCompressed(f)
    const u = await authApi.uploadAvatarJson({ data: dataUrl, filename: (f.name || 'avatar').replace(/\.[^.]+$/, '') + '.jpg', content_type: 'image/jpeg' })
    applyUserFromApi(u)
    toast('头像已更新')
  } catch (err) {
    toast('上传失败：' + (err.response?.data?.detail || err.message || '请重试'))
  } finally { uploading.value = false }
}

async function removeAvatar() {
  uploading.value = true
  try {
    const u = await authApi.removeAvatar()
    applyUserFromApi(u)
    toast('头像已移除')
  } catch (err) { toast('操作失败：' + (err.response?.data?.detail || err.message)) } finally { uploading.value = false }
}

async function changePwd() {
  if (!pwdForm.value.old_password || !pwdForm.value.new_password) { toast('请填写完整'); return }
  if (pwdForm.value.new_password !== pwdForm.value.confirm) { toast('两次输入的新密码不一致'); return }
  if (pwdForm.value.new_password.length < 8) { toast('新密码至少 8 位'); return }
  savingPwd.value = true
  try {
    await authApi.changePassword({ old_password: pwdForm.value.old_password, new_password: pwdForm.value.new_password })
    toast('密码已修改，下次登录生效')
    pwdForm.value = { old_password: '', new_password: '', confirm: '' }
  } catch (e) { toast('修改失败：' + (e.response?.data?.detail || e.message)) } finally { savingPwd.value = false }
}

async function loadLogs() {
  try { logs.value = await authApi.loginLogs({ limit: 10 }) } catch (e) { logs.value = [] }
}

onMounted(async () => { await loadMe(); await loadLogs() })
</script>

<template>
  <section class="page">
    <div class="card">
      <big style="font-size:15px;font-weight:650">基本资料</big>
      <div class="userline">
        <button class="avatar lg" @click="pickAvatar" :disabled="uploading" title="点击上传头像">
          <img v-if="avatarSrc" :src="avatarSrc" alt="头像">
          <span v-else>{{ initial }}</span>
        </button>
        <input ref="fileInput" type="file" accept="image/*" style="display:none" @change="onAvatarChange">
        <div class="usub">
          <b>{{ profile.nickname || userState.name || '未设置昵称' }}</b>
          <span>{{ profile.role === 'admin' ? '超级管理员' : (profile.role || '') }}</span>
          <div style="margin-top:6px;display:flex;gap:8px">
            <button class="mini" @click="pickAvatar" :disabled="uploading">{{ uploading ? '上传中…' : '更换头像' }}</button>
            <button v-if="avatarSrc" class="mini dan" @click="removeAvatar" :disabled="uploading">移除</button>
          </div>
        </div>
      </div>
      <div class="fgrid" style="margin-top:16px">
        <div class="field"><div class="flabel">姓名</div><input type="text" v-model="profile.nickname" placeholder="姓名"></div>
        <div class="field"><div class="flabel">手机号</div><input type="text" v-model="profile.phone" placeholder="手机号"></div>
        <div class="field"><div class="flabel">邮箱</div><input type="text" v-model="profile.email" placeholder="邮箱"></div>
        <div class="field"><div class="flabel">角色</div><input type="text" :value="profile.role === 'admin' ? '管理员' : profile.role" disabled></div>
        <div class="field span2"><div class="flabel">所属机构</div><input type="text" v-model="profile.org" placeholder="所属机构"></div>
      </div>
      <div class="modal-ft" style="border-top:0;padding-top:14px">
        <button class="pri" @click="saveProfile" :disabled="savingProfile">{{ savingProfile ? '保存中…' : '保存资料' }}</button>
      </div>
    </div>

    <div class="card">
      <big style="font-size:15px;font-weight:650">修改密码</big>
      <div class="fgrid" style="margin-top:12px">
        <div class="field span2"><div class="flabel">原密码</div><input type="password" v-model="pwdForm.old_password" placeholder="输入当前密码"></div>
        <div class="field"><div class="flabel">新密码</div><input type="password" v-model="pwdForm.new_password" placeholder="至少 8 位"></div>
        <div class="field"><div class="flabel">确认新密码</div><input type="password" v-model="pwdForm.confirm" placeholder="再次输入新密码"></div>
      </div>
      <div class="modal-ft" style="border-top:0;padding-top:14px">
        <button class="pri" @click="changePwd" :disabled="savingPwd">{{ savingPwd ? '提交中…' : '修改密码' }}</button>
      </div>
    </div>

    <div class="card">
      <big style="font-size:15px;font-weight:650">登录记录</big>
      <div class="sub" style="font-size:12px;color:var(--mut);margin:4px 0 12px">最近登录操作</div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>时间</th><th>登录方式</th><th>IP / 设备</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="l in logs" :key="l.id">
              <td class="t-num">{{ l.created_at ? l.created_at.replace('T', ' ').slice(0, 16) : '—' }}</td>
              <td>账号密码</td>
              <td><code>{{ l.ip || '—' }} {{ l.device ? '· ' + l.device : '' }}</code></td>
              <td><span class="badge" :class="l.status === '成功' ? 'normal' : 'warn'">{{ l.status }}</span></td>
            </tr>
            <tr v-if="!logs.length"><td colspan="4" class="t-mut" style="text-align:center;padding:24px">暂无登录记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>
