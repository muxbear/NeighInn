<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed } from 'vue'
import AppShell from '@/layouts/AppShell.vue'
import NiConfirmDialog from '@/components/NiConfirmDialog.vue'

const route = useRoute()
const isPublic = computed(() => Boolean(route.meta.public))
</script>

<template>
  <RouterView v-if="isPublic" />
  <AppShell v-else />
  <NiConfirmDialog />
</template>
