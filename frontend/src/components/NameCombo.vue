<script setup>
// 可输入 + 历史建议下拉：点击/聚焦即展开全部历史名称；输入时按包含过滤；
// 选中已有名称或直接输入新名称均可（新名称保存后由页面登记进 options）
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },  // 历史名称（去重）
  placeholder: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const root = ref(null)

const val = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 过滤列表：输入非空 → 包含匹配；输入为空 → 展示全部历史名称（最多 60 条）
const filtered = computed(() => {
  const q = val.value.trim().toLowerCase()
  if (!q) {
    return props.options.slice(0, 60).map((o) => String(o || '').trim()).filter(Boolean)
  }
  return props.options
    .map((o) => String(o || '').trim()).filter(Boolean)
    .filter((s) => s.toLowerCase().includes(q) && s.toLowerCase() !== q)
    .slice(0, 12)
})

function toggle() { open.value = !open.value }
function pick(o) {
  val.value = o
  open.value = false
}

function onBlur() {
  // 延迟关闭，让 mousedown 选择先生效
  setTimeout(() => { open.value = false }, 120)
}

function onDocClick(e) {
  if (root.value && !root.value.contains(e.target)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div class="ncombo" ref="root">
    <div class="nwrap">
      <input v-model="val" type="text" :placeholder="placeholder" autocomplete="off"
        @focus="open = true" @blur="onBlur" @keydown.enter.prevent="open = false">
      <span class="ni" @mousedown.prevent="toggle"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></span>
    </div>
    <div v-if="open && filtered.length" class="nlist">
      <div v-if="!val.trim()" class="ntip">历史名称（{{ props.options.length }} 个）：点击选择，或直接输入新名称</div>
      <div v-for="(o, i) in filtered" :key="i" class="nopt" @mousedown.prevent="pick(o)">{{ o }}</div>
    </div>
  </div>
</template>

<style scoped>
.ncombo { position: relative; }
.nwrap { position: relative; }
.ncombo input {
  width: 100%; height: 36px; padding: 0 30px 0 10px; border: 1px solid var(--line);
  border-radius: 9px; background: var(--card); color: var(--fg); font-size: 14px;
  outline: none; box-sizing: border-box; transition: border-color .15s;
}
.ncombo input:focus { border-color: var(--acc) }
.ni {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  display: flex; align-items: center; justify-content: center; width: 20px; height: 20px;
  color: var(--mut); cursor: pointer; pointer-events: auto;
}
.nlist {
  position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 95;
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: var(--up); max-height: 250px; overflow: auto; padding: 4px;
}
.ntip { padding: 6px 10px; font-size: 11.5px; color: var(--mut); border-bottom: 1px dashed var(--line); margin-bottom: 4px; }
.nopt {
  padding: 8px 10px; border-radius: 7px; font-size: 13px; color: var(--fg);
  cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.nopt:hover { background: var(--hl, rgba(128,128,128,.1)) }
</style>