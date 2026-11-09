<script setup>
import { ref, onMounted } from 'vue'
import { settingsApi } from '../api'
import { hasPerm } from '../utils/perm'

const canWrite = hasPerm('op.settings.write')

const toastMsg = ref('')
function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 1800) }

const form = ref({
  system_name: '', version: '', timezone: 'Asia/Shanghai (UTC+8)', data_unit: '公制 (国际单位)',
  report_signature: '', sms_notify: false, highlight_abnormal: false, ai_summary: false,
})
const saving = ref(false)

async function load() {
  try {
    const d = await settingsApi.get()
    form.value = {
      system_name: d.system_name || '',
      version: d.version || '',
      timezone: d.timezone || 'Asia/Shanghai (UTC+8)',
      data_unit: d.data_unit || '公制 (国际单位)',
      report_signature: d.report_signature || '',
      sms_notify: !!d.sms_notify,
      highlight_abnormal: !!d.highlight_abnormal,
      ai_summary: !!d.ai_summary,
    }
  } catch (e) {}
}

async function save() {
  saving.value = true
  try {
    await settingsApi.save(form.value)
    toast('系统设置已保存')
  } catch (e) { toast('保存失败：' + (e.response?.data?.detail || e.message)) } finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <div class="card">
      <big style="font-size:15px;font-weight:650">基本设置</big>
      <div class="fgrid" style="margin-top:12px">
        <div class="field"><div class="flabel">系统名称</div><input type="text" v-model="form.system_name" placeholder="系统名称"></div>
        <div class="field"><div class="flabel">版本号</div><input type="text" v-model="form.version" placeholder="版本号"></div>
        <div class="field"><div class="flabel">默认时区</div><SearchSelect v-model="form.timezone" :options="[{ value: 'Asia/Shanghai (UTC+8)', label: 'Asia/Shanghai (UTC+8)' }, { value: 'UTC', label: 'UTC' }]" placeholder="选择时区" /></div>
        <div class="field"><div class="flabel">数据单位</div><SearchSelect v-model="form.data_unit" :options="[{ value: '公制 (国际单位)', label: '公制 (国际单位)' }, { value: '英制', label: '英制' }]" placeholder="选择单位" /></div>
        <div class="field span2"><div class="flabel">报工签名</div><input type="text" v-model="form.report_signature" placeholder="报告签名"></div>
      </div>
      <div class="modal-ft" style="border-top:0;padding-top:14px">
        <button class="pri" @click="save" :disabled="saving" v-if="canWrite">{{ saving ? '保存中…' : '保存设置' }}</button>
        <span v-else class="t-mut" style="font-size:12px">当前角色无保存权限（只读）</span>
      </div>
    </div>

    <div class="card">
      <big style="font-size:15px;font-weight:650">通知与展示</big>
      <div class="row">
        <div class="lbl"><b>新报告短信提醒</b><span>新增检查报告时发送提醒</span></div>
        <label class="sw"><input type="checkbox" v-model="form.sms_notify"><i></i></label>
      </div>
      <div class="row">
        <div class="lbl"><b>异常指标高亮</b><span>超出参考范围的结果标红提示</span></div>
        <label class="sw"><input type="checkbox" v-model="form.highlight_abnormal"><i></i></label>
      </div>
      <div class="row">
        <div class="lbl"><b>AI 自动摘要</b><span>保存报告后用 AI 生成解读</span></div>
        <label class="sw"><input type="checkbox" v-model="form.ai_summary"><i></i></label>
      </div>
      <div class="modal-ft" style="border-top:0;padding-top:14px">
        <button class="pri" @click="save" :disabled="saving" v-if="canWrite">{{ saving ? '保存中…' : '保存设置' }}</button>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>
