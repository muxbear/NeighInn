<script setup lang="ts">
import { X } from 'lucide-vue-next'

defineProps<{ open: boolean; title: string; eyebrow?: string }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div v-if="open" class="drawer-backdrop" @mousedown.self="emit('close')">
    <section class="drawer" role="dialog" aria-modal="true" :aria-label="title" @mousedown.stop>
      <div class="drawer-header">
        <div>
          <span>{{ eyebrow || '维护档案' }}</span>
          <h2>{{ title }}</h2>
        </div>
        <button aria-label="关闭" @click="emit('close')"><X :size="19" /></button>
      </div>
      <div class="drawer-body"><slot /></div>
      <div v-if="$slots.footer" class="drawer-footer"><slot name="footer" /></div>
    </section>
  </div>
</template>
