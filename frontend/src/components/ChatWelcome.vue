<template>
  <!--
    聊天欢迎页：品牌标识 + 欢迎文案 + 2×2 快捷提问卡片。

    快捷提问卡片点击后由父组件填入输入框并发送（事件冒泡），
    本组件不持有任何业务状态。
  -->
  <div class="welcome">
    <!-- 品牌标识 -->
    <div class="welcome-brand">
      <span class="welcome-logo">
        <el-icon><Cpu /></el-icon>
      </span>
    </div>

    <!-- 欢迎文案 -->
    <h1 class="welcome-title">{{ title }}</h1>
    <p class="welcome-desc">{{ description }}</p>

    <!-- 能力标签 -->
    <div class="welcome-tags">
      <span v-for="tag in tags" :key="tag" class="welcome-tag">
        <el-icon><component :is="tag.icon" /></el-icon>
        {{ tag.label }}
      </span>
    </div>

    <!-- 2×2 快捷提问卡片 -->
    <div class="suggest-grid">
      <button
        v-for="s in suggestions"
        :key="s.q"
        type="button"
        class="suggest-card"
        @click="$emit('use-suggestion', s.q)"
      >
        <span class="suggest-icon" :class="`suggest-icon--${s.tone || 'primary'}`">
          <el-icon><component :is="s.icon" /></el-icon>
        </span>
        <span class="suggest-text">
          <span class="suggest-title">{{ s.label }}</span>
          <span class="suggest-q">{{ s.q }}</span>
        </span>
        <el-icon class="suggest-arrow"><ArrowRight /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  // 能力标签：[{ label, icon }]
  tags: { type: Array, default: () => [] },
  // 快捷提问：[{ q, label, icon, tone }]
  suggestions: { type: Array, default: () => [] },
})

defineEmits(['use-suggestion'])
</script>

<style scoped>
.welcome {
  max-width: 680px;
  margin: 4vh auto 0;
  padding: 0 var(--ss-space-6);
  text-align: center;
}

/* ---------- 品牌标识 ---------- */
.welcome-brand {
  display: flex;
  justify-content: center;
  margin-bottom: var(--ss-space-5);
}

.welcome-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 60px;
  height: 60px;
  border-radius: 18px;
  background: var(--ss-gradient-brand);
  color: var(--ss-text-inverse);
  font-size: 30px;
  box-shadow: var(--ss-shadow-brand);
}

/* ---------- 欢迎文案 ---------- */
.welcome-title {
  margin: 0 0 var(--ss-space-2);
  font-size: var(--ss-fs-2xl);
  font-weight: 680;
  letter-spacing: -0.02em;
  line-height: 1.35;
  color: var(--ss-text);
}

.welcome-desc {
  margin: 0 auto;
  max-width: 480px;
  font-size: var(--ss-fs-base);
  line-height: var(--ss-lh-relaxed);
  color: var(--ss-text-secondary);
}

/* ---------- 能力标签 ---------- */
.welcome-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--ss-space-2);
  margin-top: var(--ss-space-4);
}

.welcome-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 11px;
  border: 1px solid var(--ss-border);
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-elevated);
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-tertiary);
  transition: var(--ss-transition);
}

.welcome-tag:hover {
  border-color: var(--ss-primary-border);
  color: var(--ss-primary-text);
}

.welcome-tag .el-icon {
  color: var(--ss-primary);
  font-size: var(--ss-icon-xs);
}

/* ---------- 2×2 快捷提问卡片 ---------- */
.suggest-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--ss-space-3);
  margin-top: var(--ss-space-8);
}

.suggest-card {
  display: flex;
  align-items: center;
  gap: var(--ss-space-3);
  padding: var(--ss-space-4);
  border: 1px solid var(--ss-border);
  border-radius: var(--ss-radius-lg);
  background: var(--ss-bg-elevated);
  box-shadow: var(--ss-shadow-xs);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: var(--ss-transition);
}

.suggest-card:hover {
  border-color: var(--ss-primary-border);
  background: var(--ss-primary-softer);
  transform: translateY(-2px);
  box-shadow: var(--ss-shadow-hover);
}

.suggest-card:focus-visible {
  outline: none;
  border-color: var(--ss-primary);
  box-shadow: var(--ss-ring);
}

.suggest-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 38px;
  height: 38px;
  border-radius: var(--ss-radius);
  font-size: var(--ss-icon-md);
}

.suggest-icon--primary {
  background: var(--ss-primary-soft);
  color: var(--ss-primary);
}

.suggest-icon--success {
  background: var(--ss-success-soft);
  color: var(--ss-success);
}

.suggest-icon--warning {
  background: var(--ss-warning-soft);
  color: var(--ss-warning);
}

.suggest-icon--danger {
  background: var(--ss-danger-soft);
  color: var(--ss-danger);
}

.suggest-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.suggest-title {
  font-size: var(--ss-fs-sm);
  font-weight: 620;
  color: var(--ss-text);
}

.suggest-q {
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-tertiary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.suggest-arrow {
  flex: none;
  color: var(--ss-text-disabled);
  font-size: var(--ss-icon-xs);
  opacity: 0;
  transform: translateX(-4px);
  transition: var(--ss-transition);
}

.suggest-card:hover .suggest-arrow {
  opacity: 1;
  transform: translateX(0);
  color: var(--ss-primary);
}

@media (max-width: 720px) {
  .welcome {
    margin-top: 2vh;
    padding: 0 var(--ss-space-4);
  }
  .suggest-grid {
    grid-template-columns: 1fr;
    margin-top: var(--ss-space-5);
  }
  .welcome-logo {
    width: 52px;
    height: 52px;
    font-size: 26px;
    border-radius: 16px;
  }
}
</style>
