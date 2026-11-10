<script setup>
// 图片双指缩放 / 放大后单指拖动 / 未放大时左右滑动切换（emit swipe）/ 双击切换 / 单击关闭
import { ref } from 'vue'
const props = defineProps({ src: String, alt: String })
const emit = defineEmits(['close', 'swipe'])
const img = ref(null)

let curScale = 1
let tx = 0, ty = 0
let pinchDist0 = 0, pinchScale0 = 1
let panSX = 0, panSY = 0, panTX = 0, panTY = 0
let tapTimer = null
// 未放大（curScale === 1）时的单指滑动：用于左右切图
let swipeSX = 0, swipeSY = 0, swipeDir = 0
let suppressClick = false

function apply() {
  const el = img.value
  if (!el) return
  el.style.transform = `translate(${tx}px, ${ty}px) scale(${curScale})`
}
function dist(ts) { return Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY) }

function onTouchStart(e) {
  if (e.touches.length === 2) {
    pinchDist0 = dist(e.touches)
    pinchScale0 = curScale
  } else if (e.touches.length === 1) {
    if (curScale > 1) {
      panSX = e.touches[0].clientX; panSY = e.touches[0].clientY
      panTX = tx; panTY = ty
    } else {
      // 未放大：记录起点用作水平滑动判定（向左滑 = 下一张）
      swipeSX = e.touches[0].clientX; swipeSY = e.touches[0].clientY
      swipeDir = 0
    }
  }
}
function onTouchMove(e) {
  if (e.touches.length === 2) {
    e.preventDefault()
    const d = dist(e.touches)
    if (pinchDist0 > 0) {
      curScale = Math.min(4, Math.max(1, (pinchScale0 * d) / pinchDist0))
      apply()
    }
  } else if (e.touches.length === 1) {
    if (curScale > 1) {
      e.preventDefault()
      tx = panTX + (e.touches[0].clientX - panSX)
      ty = panTY + (e.touches[0].clientY - panSY)
      apply()
    } else if (!swipeDir) {
      const dx = e.touches[0].clientX - swipeSX
      const dy = e.touches[0].clientY - swipeSY
      if (Math.abs(dx) > 30 && Math.abs(dx) > Math.abs(dy) * 1.15) swipeDir = dx > 0 ? -1 : 1
    }
  }
}
function onTouchEnd() {
  pinchDist0 = 0
  if (curScale === 1 && swipeDir) {
    suppressClick = true
    emit('swipe', swipeDir)
    swipeDir = 0
  }
}

function toggleZoom() {
  if (curScale > 1) { curScale = 1; tx = 0; ty = 0 }
  else {
    curScale = 2.2
    tx = 0; ty = 0
  }
  apply()
}

function onClick() {
  if (suppressClick) { suppressClick = false; return }
  if (tapTimer) {
    clearTimeout(tapTimer); tapTimer = null
    toggleZoom() // 双击 → 切换缩放
    return
  }
  tapTimer = setTimeout(() => {
    tapTimer = null
    emit('close') // 单击 → 关闭
  }, 280)
}
</script>

<template>
  <div class="pz" @click="onClick"
       @touchstart.passive="onTouchStart" @touchmove.prevent="onTouchMove" @touchend="onTouchEnd">
    <img ref="img" :src="src" :alt="alt || ''" draggable="false" />
  </div>
</template>

<style scoped>
.pz{position:relative;width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  overflow:hidden;touch-action:none;cursor:zoom-in}
.pz img{display:block;max-width:100%;max-height:100%;object-fit:contain;
  transform-origin:center;user-select:none;-webkit-user-select:none;-webkit-user-drag:none;
  touch-action:none;transition:transform .12s ease-out}
</style>