/**
 * 公共 UI 组件统一出口。
 *
 * 组件清单：
 *   - AppHeader / AppSidebar：应用级外壳
 *   - PageHeader / SectionHeader：页面与区块标题
 *   - StatCard / IconTile / StatusDot / EmptyState：通用展示件
 *   - BrandMark：品牌图标
 *   - ChatComposer / ChatMessageList / ChatMessageItem：对话流
 *   - SessionList / SourceChips / ToolCallCard：对话附属件
 *
 * 用法：import { PageHeader, StatCard } from '../components'
 */
export { default as AppHeader } from './AppHeader.vue'
export { default as AppSidebar } from './AppSidebar.vue'
export { default as BrandMark } from './BrandMark.vue'
export { default as ChatComposer } from './ChatComposer.vue'
export { default as ChatContextPanel } from './ChatContextPanel.vue'
export { default as ChatMessageItem } from './ChatMessageItem.vue'
export { default as ChatMessageList } from './ChatMessageList.vue'
export { default as ChatWelcome } from './ChatWelcome.vue'
export { default as EmptyState } from './EmptyState.vue'
export { default as IconTile } from './IconTile.vue'
export { default as PageHeader } from './PageHeader.vue'
export { default as SectionHeader } from './SectionHeader.vue'
export { default as SessionList } from './SessionList.vue'
export { default as SourceChips } from './SourceChips.vue'
export { default as StatCard } from './StatCard.vue'
export { default as StatusDot } from './StatusDot.vue'
export { default as ToolCallCard } from './ToolCallCard.vue'
