<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, FileClock } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const isError = computed(() => ['forbidden', 'not-found'].includes(String(route.name)))
</script>

<template>
  <section class="table-panel">
    <div class="empty-state" style="height: 320px">
      <FileClock :size="30" />
      <strong>{{ isError ? '无法访问此页面' : '功能建设中' }}</strong>
      <span>{{ isError ? '请检查链接或联系系统管理员。' : '主流程页面已可用，扩展页面将按排期接入。' }}</span>
      <button v-if="isError" class="primary-button" style="margin-top: 14px" @click="router.push('/dashboard')"><ArrowLeft :size="17" />返回工作台</button>
    </div>
  </section>
</template>
