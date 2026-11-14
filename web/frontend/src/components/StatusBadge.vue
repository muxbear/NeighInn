<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ value: string }>()

const tone = computed(() => {
  const value = props.value || ''
  if (/失败|有差异|高风险|违规/.test(value)) return 'danger'
  if (/已发布|正常|启用|已通过|已认证|已完成|生效中|营业中|在售|已采纳|已解决|一致|已到账|已放款|已退款|已交割|成功/.test(value)) return 'success'
  if (/审核|待|报名中|发送中|进行中|定时|匹配中|退款中|打款中|调解中|托管中|待放款/.test(value)) return 'warning'
  if (/停用|下架|暂停|草稿|补充|已驳回|已关闭|已撤回|已下线|已取消/.test(value)) return 'neutral'
  return 'info'
})
</script>

<template>
  <span :class="['status', tone]"><i />{{ value }}</span>
</template>
