<template>
  <!--
    统一的品牌图标方块。
    只负责视觉，尺寸通过 size prop 控制（sm / md / lg）。
  -->
  <span class="ss-brand-mark" :class="sizeClass">
    <el-icon><component :is="icon" /></el-icon>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // Element Plus 图标组件名（已全局注册）
  icon: { type: String, default: 'Cpu' },
  // sm: 26px  md: 32px  lg: 44px
  size: { type: String, default: 'md' },
})

const sizeClass = computed(() => `ss-brand-mark--${props.size}`)
</script>

<style scoped>
.ss-brand-mark--sm {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  font-size: 14px;
  box-shadow: none;
}

.ss-brand-mark--md {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  font-size: 17px;
}

.ss-brand-mark--lg {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  font-size: 27px;
  box-shadow: var(--ss-shadow-brand);
}
</style>
