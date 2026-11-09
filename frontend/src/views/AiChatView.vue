<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { aiApi, aiApi2 } from '../api'

const toastMsg = ref('')
function toast(m) { toastMsg.value = m; setTimeout(() => (toastMsg.value = ''), 2000) }

// 模型选择
const groups = ref([])
const alias = ref('')
const model = ref('')
const messages = ref([])        // { role, content, pending?, executed? }
const input = ref('')
const busy = ref(false)
const chatBox = ref(null)

async function loadModels() {
  if (groups.value.length) return
  try {
    const list = await aiApi.list({ limit: 100 })
    const map = {}
    for (const m of list) {
      if (!m.enabled) continue
      if (!map[m.alias]) map[m.alias] = { alias: m.alias, items: [] }
      map[m.alias].items.push({ name: m.name })
    }
    groups.value = Object.values(map)
    if (groups.value.length) {
      alias.value = groups.value[0].alias
      model.value = groups.value[0].items[0].name
    }
  } catch (e) { groups.value = [] }
}

function pickAlias() {
  const g = groups.value.find((x) => x.alias === alias.value)
  model.value = (g && g.items.length) ? g.items[0].name : ''
}

function scrollBottom() {
  nextTick(() => {
    if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
  })
}

// 发送提问
async function send() {
  const text = input.value.trim()
  if (!text) return
  if (!alias.value || !model.value) { toast('请先选择 AI 供应商和模型'); return }
  if (busy.value) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  scrollBottom()
  busy.value = true
  // 历史：只取 user/assistant 纯文本（未确认的写操作不传给模型）
  const history = messages.value
    .filter((m) => m.role === 'user' || (m.role === 'assistant' && !m.pending))
    .map((m) => ({ role: m.role, content: m.content }))
    .slice(0, -1)
  try {
    const r = await aiApi2.agentChat({ alias: alias.value, model: model.value, message: text, history })
    messages.value.push({
      role: 'assistant', content: r.reply || '（模型未返回内容）',
      pending: (r.pending_actions || []).map((a) => ({ ...a, status: 'wait' })),
    })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '出错了：' + (e.response?.data?.detail || e.message) })
  } finally {
    busy.value = false
    scrollBottom()
  }
}

// 确认执行写操作
async function confirmAction(a) {
  a.status = 'run'
  try {
    const r = await aiApi2.agentExecute({ action: { id: a.id, name: a.name, args: a.args, desc: a.desc } })
    a.status = 'done'
    messages.value.push({ role: 'assistant', content: (r.result_text || '操作已完成') + '（已同步到系统数据）', executed: true })
  } catch (e) {
    a.status = 'wait'
    toast('执行失败：' + (e.response?.data?.detail || e.message))
  } finally {
    scrollBottom()
  }
}

function cancelAction(a) { a.status = 'cancel' }

function clearChat() {
  if (!messages.value.length) return
  if (!confirm('清空当前对话？')) return
  messages.value = []
}

onMounted(async () => {
  await loadModels()
  messages.value.push({
    role: 'assistant',
    content: '你好，我是「壹健康」数据助手。你可以问我系统里的任何数据，比如：\n' +
      '· 有多少条检查记录？最近有哪些报告？\n' +
      '· 统计一下用药记录，或看看某位患者的开方详情\n' +
      '· 也可以让我帮你新增/修改/删除记录（每次都会先让你确认）',
  })
  scrollBottom()
})
</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div class="left">
        <div class="page-title"><h1>AI 问数助手</h1><div class="sub">直接提问或让 AI 操作你的数据，写操作需你确认后才会执行</div></div>
      </div>
      <div class="right">
        <SearchSelect v-model="alias" style="width:150px" @change="pickAlias"
          :options="groups.map((g) => ({ value: g.alias, label: g.alias + '（' + g.items.length + '）' }))"
          placeholder="供应商" />
        <SearchSelect v-model="model" style="width:190px"
          :options="(groups.find((g) => g.alias === alias)?.items || []).map((m) => ({ value: m.name, label: m.name }))"
          placeholder="模型" />
        <button class="sm" @click="clearChat" :disabled="!messages.length">清空对话</button>
      </div>
    </div>

    <div class="chat-wrap panel">
      <div ref="chatBox" class="chat-box">
        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="bubble">
            <div class="who">{{ m.role === 'user' ? '你' : 'AI 助手' }}</div>
            <div class="txt">{{ m.content }}</div>
            <!-- 待确认的写操作卡片 -->
            <div v-if="m.pending && m.pending.length" class="pends">
              <div v-for="a in m.pending" :key="a.id" class="pend" :class="'st-' + a.status">
                <div class="pend-head">
                  <span class="badge dan">写操作</span>
                  <b>{{ a.desc }}</b>
                </div>
                <div class="pend-args t-mut">{{ a.name }}({{ JSON.stringify(a.args) }})</div>
                <div class="pend-ops">
                  <template v-if="a.status === 'wait'">
                    <button class="mini pri" @click="confirmAction(a)">确认执行</button>
                    <button class="mini" @click="cancelAction(a)">取消</button>
                  </template>
                  <span v-else-if="a.status === 'run'" class="t-mut"><span class="spin"></span> 执行中…</span>
                  <span v-else-if="a.status === 'done'" class="rs normal">✓ 已执行</span>
                  <span v-else class="t-mut">已取消</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="busy" class="msg assistant">
          <div class="bubble"><div class="who">AI 助手</div><div class="txt"><span class="spin"></span> 正在处理…（若 AI 服务繁忙会自动重试，请稍候）</div></div>
        </div>
      </div>
      <div class="chat-input">
        <textarea v-model="input" rows="2" placeholder="例如：统计一下检查记录里有哪些异常项；或：帮我把昨天那条检查记录备注改成‘已复查'"
          @keydown.enter.exact.prevent="send"></textarea>
        <button class="pri" @click="send" :disabled="busy || !input.trim() || !alias || !model">{{ busy ? '发送中…' : '发送' }}</button>
      </div>
    </div>

    <div class="toast" :class="{ show: toastMsg }">{{ toastMsg }}</div>
  </section>
</template>

<style scoped>
.chat-wrap { display: flex; flex-direction: column; height: calc(100vh - 150px); overflow: hidden; }
.chat-box { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 78%; padding: 10px 14px; border-radius: 12px; background: var(--bg2, #f7f8fa); box-shadow: var(--in-sm); }
.msg.user .bubble { background: var(--acc); color: #fff; }
.bubble .who { font-size: 11px; opacity: .75; margin-bottom: 4px; font-weight: 600; }
.bubble .txt { font-size: 13.5px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; }
.pends { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.pend { border: 1px solid var(--bd); border-radius: 8px; padding: 8px 10px; background: #fff; }
.msg.user .pend { background: #fff; color: var(--tx); border-color: var(--bd); }
.pend-head { display: flex; align-items: center; gap: 8px; font-size: 12.5px; flex-wrap: wrap; }
.pend-args { font-size: 11.5px; margin: 4px 0 6px; word-break: break-all; }
.pend-ops { display: flex; align-items: center; gap: 8px; }
.chat-input { display: flex; gap: 10px; padding: 12px 16px; border-top: 1px solid var(--bd); }
.chat-input textarea { flex: 1; resize: none; font-family: inherit; font-size: 13.5px; border: 1px solid var(--bd); border-radius: 10px; padding: 8px 10px; outline: none; }
.chat-input textarea:focus { border-color: var(--acc); }
</style>
