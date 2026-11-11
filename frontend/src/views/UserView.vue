<script setup>
import { ref, onMounted } from 'vue'
import { userApi, roleApi } from '../api'
import { watchBack } from '../utils/backstack'

const rows = ref([])
const query = ref('')
const roles = ref([])
const toastMsg = ref('')
function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

const mdl = ref(false)
const saving = ref(false)
const form = ref({
  id: 0, username: '', password: '', nickname: '', phone: '', email: '', org: '',
  role: 'viewer', is_active: true,
})

const ROLE_CACHE = new Map() // code -> name

async function load() {
  try {
    rows.value = (await userApi.list({ q: query.value })) || []
  } catch (e) { toast('加载失败：' + (e.response?.data?.detail || e.message)) }
}

async function loadRoles() {
  try {
    roles.value = (await roleApi.list()) || []
    for (const r of roles.value) ROLE_CACHE.set(r.code, r.name)
  } catch (e) {
    roles.value = [{ code: 'admin', name: '管理员' }, { code: 'viewer', name: '只读' }]
    for (const r of roles.value) ROLE_CACHE.set(r.code, r.name)
  }
}

function roleOptions() {
  return roles.value.map((r) => ({ value: r.code, label: r.name }))
}

function openMdl() {
  form.value = { id: 0, username: '', password: '', nickname: '', phone: '', email: '', org: '', role: 'viewer', is_active: true }
  mdl.value = true
}

function openEdit(u) {
  form.value = {
    id: u.id, username: u.username, password: '',
    nickname: u.nickname || '', phone: u.phone || '', email: u.email || '', org: u.org || '',
    role: u.role || 'viewer', is_active: !!u.is_active,
  }
  mdl.value = true
}

async function save() {
  if (!form.value.username.trim()) { toast('请输入用户名'); return }
  if (!form.value.id && form.value.password.length < 8) { toast('密码至少 8 位'); return }
  saving.value = true
  try {
    if (form.value.id) {
      const data = {
        nickname: form.value.nickname, phone: form.value.phone, email: form.value.email,
        org: form.value.org, role: form.value.role, is_active: form.value.is_active,
      }
      if (form.value.password) data.password = form.value.password
      await userApi.update(form.value.id, data)
    } else {
      await userApi.create({
        username: form.value.username, password: form.value.password,
        nickname: form.value.nickname, phone: form.value.phone, email: form.value.email,
        org: form.value.org, role: form.value.role,
      })
    }
    toast('已保存'); mdl.value = false; await load()
  } catch (e) { toast('保存失败：' + (e.response?.data?.detail || e.message)) } finally { saving.value = false }
}

async function toggleActive(u) {
  try {
    await userApi.update(u.id, { is_active: !u.is_active })
    await load()
  } catch (e) { toast('操作失败：' + (e.response?.data?.detail || e.message)) }
}

async function del(u) {
  if (!confirm('确定删除用户「' + u.username + '」？删除后无法恢复。')) return
  try {
    await userApi.remove(u.id)
    toast('已删除'); await load()
  } catch (e) { toast('删除失败：' + (e.response?.data?.detail || e.message)) }
}

function fmt(v) { return v ? String(v).replace('T', ' ').slice(0, 16) : '—' }
function roleLbl(r) {
  const n = ROLE_CACHE.get(r)
  if (n) return n
  return r === 'admin' ? '管理员' : (r === 'viewer' ? '只读' : r)
}

onMounted(() => { load(); loadRoles() })
// 系统返回键逐级返回：弹层进入返回栈
watchBack(() => mdl.value, () => { mdl.value = false })
</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div class="left">
        <button class="pri" @click="openMdl">＋ 新增用户</button>
      </div>
      <div class="right">
        <div class="searchbox"><input type="search" v-model="query" placeholder="搜索用户名 / 昵称 / 手机 / 机构" @keyup.enter="load"><svg class="lm" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4-4" stroke="currentColor" stroke-width="2"/></svg></div>
        <button class="sm" @click="load">搜索</button>
      </div>
    </div>

    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:40px">#</th>
          <th>用户名</th><th>昵称</th><th>手机号</th><th>邮箱</th><th>机构</th>
          <th style="width:80px">角色</th><th style="width:80px">状态</th>
          <th style="width:160px">创建时间</th><th style="width:170px;white-space:nowrap">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="(u, i) in rows" :key="u.id">
            <td class="t-mut">{{ i + 1 }}</td>
            <td><b>{{ u.username }}</b></td>
            <td>{{ u.nickname || '—' }}</td>
            <td class="t-num">{{ u.phone || '—' }}</td>
            <td class="t-mut">{{ u.email || '—' }}</td>
            <td class="t-mut">{{ u.org || '—' }}</td>
            <td><span class="badge info" style="font-size:11px">{{ roleLbl(u.role) }}</span></td>
            <td><span v-if="u.is_active" class="badge normal" style="font-size:11px">启用</span><span v-else class="badge warn" style="font-size:11px">停用</span></td>
            <td class="t-num t-mut">{{ fmt(u.created_at) }}</td>
            <td><div class="ops">
              <button class="mini" @click="openEdit(u)">编辑</button>
              <button class="mini" @click="toggleActive(u)">{{ u.is_active ? '停用' : '启用' }}</button>
              <button class="mini dan" @click="del(u)">删除</button>
            </div></td>
          </tr>
          <tr v-if="!rows.length"><td colspan="10" class="t-mut" style="text-align:center;padding:28px">暂无用户，点「＋ 新增用户」创建</td></tr>
        </tbody>
      </table>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>

    <!-- 新增 / 编辑用户 -->
    <div class="modal-mask" :class="{ show: mdl }">
      <div class="modal panel">
        <div class="mbar">
          <h3>{{ form.id ? '编辑用户' : '新增用户' }}</h3>
          <div class="mtools">
            <button class="mt-btn" title="关闭" @click="mdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">{{ form.id ? '编辑资料、角色、启停；密码留空表示不修改' : '创建系统账号，密码至少 8 位' }}</div>
        <div class="mbody">
          <div class="fgrid">
            <div class="field"><div class="flabel">用户名 <span style="color:var(--err)">*</span></div>
              <input type="text" v-model="form.username" placeholder="登录账号" :disabled="!!form.id">
            </div>
            <div class="field"><div class="flabel">{{ form.id ? '重置密码' : '初始密码' }}</div>
              <input type="password" v-model="form.password" :placeholder="form.id ? '留空则不修改' : '至少 8 位'">
            </div>
            <div class="field"><div class="flabel">昵称</div><input type="text" v-model="form.nickname" placeholder="显示名称"></div>
            <div class="field"><div class="flabel">手机号</div><input type="text" v-model="form.phone" placeholder="手机号"></div>
            <div class="field"><div class="flabel">邮箱</div><input type="text" v-model="form.email" placeholder="邮箱"></div>
            <div class="field"><div class="flabel">所属机构</div><input type="text" v-model="form.org" placeholder="机构 / 科室"></div>
            <div class="field"><div class="flabel">角色</div>
              <SearchSelect v-model="form.role" :options="roleOptions()" placeholder="选择角色" />
            </div>
            <div class="field" v-if="form.id"><div class="flabel">账号状态</div>
              <label class="sw" style="height:34px"><input type="checkbox" v-model="form.is_active"><i></i></label>
              <span class="t-mut" style="font-size:12px;margin-left:8px">{{ form.is_active ? '启用中' : '已停用' }}</span>
            </div>
          </div>
        </div>
        <div class="modal-ft">
          <button class="pri" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </section>
</template>