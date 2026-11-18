<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed } from 'vue'
import AppShell from '@/layouts/AppShell.vue'
import NiConfirmDialog from '@/components/NiConfirmDialog.vue'

const route = useRoute()
// 首帧路由尚未解析时 matched 为空；此时不能挂载 AppShell，
// 否则登录页会提前触发待办/社区等需登录接口并产生 401 噪声。
const isPublic = computed(() => route.matched.length === 0 || Boolean(route.meta.public))
</script>

<template>
  <RouterView v-if="isPublic" />
  <AppShell v-else />
  <NiConfirmDialog />
</template>
