<script setup>
// 移动端分页：加载更多（每页加载 N 条）+ 上/下一页 + 跳页。PC 端隐藏（用原 .pager）
import { ref, computed, watch } from 'vue'
const props = defineProps({
  total: { type: Number, default: 0 },
  visible: { type: Number, default: 10 },
  pageSize: { type: Number, default: 10 },
  unit: { type: String, default: '条' },
})
const emit = defineEmits(['update:visible'])
const jump = ref('1') // 页码输入框，默认当前页（1）

const maxPage = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const page = computed(() =>
  Math.max(1, Math.min(maxPage.value, Math.ceil(Math.max(1, props.visible) / props.pageSize))),
)
const allLoaded = computed(() => props.total > 0 && props.visible >= props.total)

function setV(n) {
  emit('update:visible', Math.min(props.total, Math.max(1, n)))
}
function more() { setV(props.visible + props.pageSize) }
function prev() { setV((page.value - 1) * props.pageSize) }
function next() { setV(page.value * props.pageSize) }
function go() {
  const n = parseInt(jump.value, 10)
  if (!isNaN(n) && n >= 1) setV(n * props.pageSize)
  else jump.value = String(page.value) // 无效输入恢复为当前页
}
// 翻页 / 加载更多后，输入框同步为当前页码
watch(page, (v) => { jump.value = String(v) })
</script>

<template>
  <div class="mpg">
    <button class="mpg-more" @click="more" :disabled="allLoaded || !total">
      <template v-if="allLoaded">已全部加载 · 第 {{ page }}/{{ maxPage }} 页</template>
      <template v-else>加载更多（第 {{ page }}/{{ maxPage }} 页）· 点击再加载 {{ pageSize }} 条</template>
    </button>
    <div class="mpg-nav">
      <button @click="prev" :disabled="page <= 1">‹ 上一页</button>
      <button @click="next" :disabled="allLoaded || !total">下一页 ›</button>
    </div>
    <div class="mpg-jump">
      <span class="mpg-info">第 <b>{{ page }}</b>/<b>{{ maxPage }}</b> 页，共 <b>{{ total }}</b> {{ unit }}</span>
      <input type="number" v-model="jump" min="1" :max="maxPage" />
      <button class="mpg-go" @click="go" :disabled="!jump">翻页</button>
    </div>
  </div>
</template>

<style scoped>
.mpg{display:flex;flex-direction:column;gap:8px;margin:14px 0 6px}
.mpg-more{width:100%;padding:12px;font-size:13.5px;border-radius:8px;
  background:var(--card2);color:var(--fg);border:1px dashed var(--sh)}
.mpg-more:not(:disabled):active{background:var(--acc-soft)}
.mpg-nav{display:flex;gap:10px}
.mpg-nav button{flex:1;padding:11px;border-radius:8px;font-size:13.5px}
.mpg-jump{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.mpg-info{font-size:12.5px;color:var(--mut)}
.mpg-info b{color:var(--fg);font-variant-numeric:tabular-nums}
.mpg-jump input{width:56px;text-align:center;padding:7px 4px;font-size:13px}
.mpg-jump .mpg-go{padding:7px 14px;font-size:13px}
@media (min-width: 561px){ .mpg{display:none} }
</style>