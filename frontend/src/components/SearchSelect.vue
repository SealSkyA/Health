<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue: { default: null },
  options: { type: Array, default: () => [] },   // [{ value, label }]
  placeholder: { type: String, default: '请选择' },
  searchable: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue', 'change'])

const open = ref(false)
const kw = ref('')
const root = ref(null)

const label = computed(() => {
  if (props.modelValue === null || props.modelValue === undefined || props.modelValue === '') return null
  const hit = props.options.find((o) => o.value === props.modelValue)
  return hit ? hit.label : null
})

const filtered = computed(() => {
  const q = kw.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((o) => String(o.label).toLowerCase().includes(q))
})

function toggle() {
  open.value = !open.value
  if (open.value) kw.value = ''
}

function pick(o) {
  emit('update:modelValue', o.value)
  emit('change', o.value)
  open.value = false
}

function onDocClick(e) {
  if (root.value && !root.value.contains(e.target)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div class="ssl" ref="root">
    <button type="button" class="ssl-trigger" @click.stop="toggle" @keydown.esc="open = false">
      <span class="ssl-val" :class="{ ph: !label }">{{ label ?? placeholder }}</span>
      <svg class="ssl-ico" :class="{ up: open }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
    </button>
    <div v-if="open" class="ssl-panel">
      <div v-if="searchable" class="ssl-search">
        <svg class="ssl-sico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
        <input v-model="kw" type="text" placeholder="搜索…" autofocus>
      </div>
      <div class="ssl-list">
        <div v-for="(o, i) in filtered" :key="i" class="ssl-opt" :class="{ on: o.value === modelValue }" @click.stop="pick(o)">
          <span class="ssl-lbl">{{ o.label }}</span>
          <svg v-if="o.value === modelValue" class="ssl-check" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
        </div>
        <div v-if="!filtered.length" class="ssl-none">无匹配选项</div>
      </div>
    </div>
  </div>
</template>