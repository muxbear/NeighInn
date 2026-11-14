<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, FileClock } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const title = computed(() => (route.meta.title as string) || '页面')
const isError = computed(() => ['forbidden', 'not-found'].includes(String(route.name)))
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>邻里小栈 / {{ title }}</p><h1>{{ title }}</h1><span>{{ isError ? '当前页面不可访问或不存在。' : '该页面已纳入扩展设计，数据接口可按同一设计系统继续接入。' }}</span></div>
    <button v-if="isError" class="primary-button" @click="router.push('/dashboard')"><ArrowLeft :size="17" />返回工作台</button>
  </section>
  <section class="table-panel">
    <div class="empty-state" style="height: 320px">
      <FileClock :size="30" />
      <strong>{{ isError ? '无法访问此页面' : '功能建设中' }}</strong>
      <span>{{ isError ? '请检查链接或联系系统管理员。' : '主流程页面已可用，扩展页面将按排期接入。' }}</span>
    </div>
  </section>
</template>
