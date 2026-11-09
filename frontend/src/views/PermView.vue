<script setup>
import { ref, onMounted } from 'vue'
import { roleApi } from '../api'

const roles = ref([])
const permDefs = ref([])       // PERM_GROUPS: [{group, items:[{key,label}]}]
const toastMsg = ref('')
function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

const mdl = ref(false)
const saving = ref(false)
const isEdit = ref(false)
const form = ref({ code: '', name: '', desc: '', perms: [] })
const errMsg = ref('')

async function load() {
  try {
    roles.value = (await roleApi.list()) || []
  } catch (e) { toast('加载失败：' + (e.response?.data?.detail || e.message)) }
}

async function loadDefs() {
  try {
    permDefs.value = (await roleApi.permDefs()) || []
  } catch (e) { toast('权限清单加载失败：' + (e.response?.data?.detail || e.message)) }
}

const groupSel = ref({}) // 每组全选框状态（按渲染临时取）
function groupKeys() { return permDefs.value.map((g) => g.group) }

function hasPerm(p) { return form.value.perms.includes(p) }
function togglePerm(p) {
  const i = form.value.perms.indexOf(p)
  if (i >= 0) form.value.perms.splice(i, 1)
  else form.value.perms.push(p)
}
function groupAllChecked(group) {
  const items = permDefs.value.filter((g) => g.group === group)[0]?.items || []
  return items.length > 0 && items.every((it) => form.value.perms.includes(it.key))
}
function groupSomeChecked(group) {
  const items = permDefs.value.filter((g) => g.group === group)[0]?.items || []
  const n = items.filter((it) => form.value.perms.includes(it.key)).length
  return n > 0 && n < items.length
}
function toggleGroup(group) {
  const items = permDefs.value.filter((g) => g.group === group)[0]?.items || []
  if (groupAllChecked(group)) form.value.perms = form.value.perms.filter((p) => !items.some((it) => it.key === p))
  else {
    for (const it of items) if (!form.value.perms.includes(it.key)) form.value.perms.push(it.key)
  }
}
function selectGroup(group, val) {
  const items = permDefs.value.filter((g) => g.group === group)[0]?.items || []
  if (val) {
    for (const it of items) if (!form.value.perms.includes(it.key)) form.value.perms.push(it.key)
  } else {
    form.value.perms = form.value.perms.filter((p) => !items.some((it) => it.key === p))
  }
}

function openNew() {
  isEdit.value = false
  form.value = { code: '', name: '', desc: '', perms: [] }
  errMsg.value = ''
  mdl.value = true
}

function openEdit(r) {
  isEdit.value = true
  form.value = { code: r.code, name: r.name, desc: r.desc || '', perms: [...(r.perms || [])] }
  errMsg.value = ''
  mdl.value = true
}

function permCount(r) {
  if (r.code === 'admin') return `${permDefs.value.reduce((n, g) => n + g.items.length, 0)} 项`
  return `${(r.perms || []).length} 项`
}

async function save() {
  errMsg.value = ''
  const c = form.value.code.trim()
  const n = form.value.name.trim()
  if (!n) { errMsg.value = '请输入角色名称'; return }
  if (!isEdit.value) {
    if (!/^[a-zA-Z][a-zA-Z0-9_-]{1,31}$/.test(c)) { errMsg.value = '角色编码需字母开头、2~32 位字母/数字/下划线'; return }
  }
  saving.value = true
  try {
    const data = { name: n, desc: form.value.desc || null, perms: form.value.perms }
    if (isEdit.value) await roleApi.update(form.value.code, data)
    else await roleApi.create({ code: c, ...data })
    toast('已保存')
    mdl.value = false
    await load()
  } catch (e) { errMsg.value = e.response?.data?.detail || '保存失败，请稍后重试' } finally { saving.value = false }
}

async function del(r) {
  if (!confirm(`确定删除角色「${r.name}」？其下用户将无法登录。`)) return
  try {
    await roleApi.remove(r.code)
    toast('已删除')
    await load()
  } catch (e) { toast(e.response?.data?.detail || '删除失败') }
}

onMounted(() => { load(); loadDefs() })
</script>

<template>
  <section class="page">
    <div class="card" style="padding:16px 20px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <b style="font-size:14px">角色与权限</b>
        <span class="t-mut" style="font-size:12.5px">
          自定义角色并勾选权限点：页面访问控制菜单与路由，可写操作控制各业务页的增删改按钮。
          「超级管理员」恒拥有全部权限。
        </span>
        <button class="pri" style="margin-left:auto" @click="openNew">＋ 新建角色</button>
      </div>
    </div>

    <div class="card" style="padding:0">
      <div class="tbl-wrap">
        <table>
          <thead><tr>
            <th style="width:46px">#</th>
            <th>角色编码</th><th>角色名称</th><th>描述</th>
            <th style="width:90px">用户数</th><th style="width:90px">权限</th>
            <th style="width:80px">类型</th><th style="width:120px;white-space:nowrap">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="(r, i) in roles" :key="r.code">
              <td class="t-mut">{{ i + 1 }}</td>
              <td><code>{{ r.code }}</code></td>
              <td><b>{{ r.name }}</b></td>
              <td class="t-mut" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.desc || '—' }}</td>
              <td class="t-num">{{ r.user_count }}</td>
              <td class="t-num">{{ permCount(r) }}</td>
              <td>
                <span v-if="r.is_system" class="badge info" style="font-size:11px">内置</span>
                <span v-else class="badge" style="font-size:11px">自定义</span>
              </td>
              <td><div class="ops">
                <button class="mini" @click="openEdit(r)" v-if="!r.is_system">编辑</button>
                <button class="mini dan" @click="del(r)" v-if="!r.is_system">删除</button>
                <span v-else class="t-mut" style="font-size:12px">不可操作</span>
              </div></td>
            </tr>
            <tr v-if="!roles.length"><td colspan="8" class="t-mut" style="text-align:center;padding:28px">暂无角色</td></tr>
          </tbody>
        </table>
      </div>
      <div class="t-mut" style="padding:12px 20px;border-top:1px solid var(--line);font-size:12.5px">
        提示：删除角色前需先在「用户管理」将该角色下的用户调整到其他角色。
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>

    <!-- 新建 / 编辑角色 -->
    <div class="modal-mask" :class="{ show: mdl }">
      <div class="modal panel" style="width:680px">
        <div class="mbar">
          <h3>{{ isEdit ? '编辑角色' : '新建角色' }}</h3>
          <div class="mtools">
            <button class="mt-btn" title="关闭" @click="mdl = false"><span style="font-size:13px">✕</span></button>
          </div>
        </div>
        <div class="msub">设置角色信息并勾选权限点；保存后所有该角色的用户立即生效</div>
        <div class="mbody">
          <div class="f-err" v-if="errMsg">{{ errMsg }}</div>
          <div class="fgrid">
            <div class="field"><div class="flabel">角色编码 <span style="color:var(--err)">*</span></div>
              <input type="text" v-model="form.code" placeholder="如 doctor、nurse" :disabled="isEdit">
            </div>
            <div class="field"><div class="flabel">角色名称 <span style="color:var(--err)">*</span></div>
              <input type="text" v-model="form.name" placeholder="如 医生、护士">
            </div>
            <div class="field span2"><div class="flabel">描述</div>
              <input type="text" v-model="form.desc" placeholder="角色用途说明（可选）">
            </div>
          </div>

          <div style="height:1px;background:var(--line);margin:14px 0"></div>
          <div style="font-size:13px;font-weight:600;margin-bottom:10px">权限点勾选</div>

          <div v-for="g in permDefs" :key="g.group" style="margin-bottom:14px">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
              <label class="sw" style="height:22px">
                <input type="checkbox" :checked="groupAllChecked(g.group)" @change="selectGroup(g.group, $event.target.checked)"><i></i>
              </label>
              <b style="font-size:13px">{{ g.group }}</b>
              <span class="t-mut" style="font-size:12px">{{ groupAllChecked(g.group) ? '已全部勾选' : '未全部勾选' }}</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:8px;padding-left:30px">
              <label v-for="it in g.items" :key="it.key"
                class="perm-chk" :class="{ on: hasPerm(it.key) }"
                style="display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer;font-size:12.5px">
                <input type="checkbox" :checked="hasPerm(it.key)" @change="togglePerm(it.key)" style="display:none">
                <span class="pdot"></span>{{ it.label }}
              </label>
            </div>
          </div>
          <div v-if="!permDefs.length" class="t-mut" style="font-size:13px">权限清单加载中…</div>
        </div>
        <div class="modal-ft">
          <button class="pri" @click="save" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.perm-chk { transition: all .15s; user-select: none }
.perm-chk:hover { border-color: var(--acc) }
.perm-chk.on { border-color: var(--acc); background: color-mix(in srgb, var(--acc) 8%, transparent) }
.perm-chk .pdot { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid var(--line); background: transparent; transition: all .15s }
.perm-chk.on .pdot { background: var(--acc); border-color: var(--acc) }
.f-err { background: color-mix(in srgb, var(--err) 10%, transparent); border: 1px solid color-mix(in srgb, var(--err) 45%, transparent); color: var(--err); border-radius: 9px; padding: 8px 12px; font-size: 13px; margin-bottom: 12px }
</style>