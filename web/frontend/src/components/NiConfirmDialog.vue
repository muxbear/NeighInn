<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'
import { useConfirm } from '@/composables/useConfirm'

const { confirmState, resolveConfirm } = useConfirm()

function onKeydown(event: KeyboardEvent): void {
  if (confirmState.open && event.key === 'Escape') resolveConfirm(false)
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="confirmState.open" class="modal-backdrop" @click.self="resolveConfirm(false)">
    <section class="modal-card ni-confirm-card" role="alertdialog" aria-modal="true" :aria-label="confirmState.title">
      <header>
        <span :class="['ni-confirm-heading', { danger: confirmState.danger }]">
          <AlertTriangle :size="18" />{{ confirmState.title }}
        </span>
      </header>
      <div class="modal-body">
        <p class="ni-confirm-message">{{ confirmState.message }}</p>
        <p v-for="(detail, index) in confirmState.details" :key="index" class="ni-confirm-detail">{{ detail }}</p>
      </div>
      <footer>
        <button @click="resolveConfirm(false)">{{ confirmState.cancelText }}</button>
        <button :class="confirmState.danger ? 'danger-button' : 'primary-button'" @click="resolveConfirm(true)">{{ confirmState.confirmText }}</button>
      </footer>
    </section>
  </div>
</template>
