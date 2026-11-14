<script setup lang="ts">
import { Search } from 'lucide-vue-next'

withDefaults(defineProps<{ title?: string; description?: string }>(), {
  title: '暂无匹配内容',
  description: '请调整筛选或搜索条件',
})
</script>

<template>
  <div class="empty-state">
    <Search :size="28" />
    <strong>{{ title }}</strong>
    <span>{{ description }}</span>
  </div>
</template>
