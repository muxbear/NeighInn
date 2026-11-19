<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { AlertCircle, Eye, EyeOff, Lock, ShieldCheck } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const error = ref('')
const submitting = ref(false)

const newPasswordValid = computed(() => {
  const value = newPassword.value
  if (value.length < 12) return false
  // 与后端策略一致：大小写字母、数字、符号四类中至少三类
  const kinds = [
    /[a-z]/.test(value), /[A-Z]/.test(value), /\d/.test(value), /[^A-Za-z0-9]/.test(value),
  ].filter(Boolean).length
  return kinds >= 3
})
const formError = computed(() => {
  if (!oldPassword.value) return '请输入当前密码'
  if (newPassword.value.length < 12) return '新密码最短 12 位'
  if (!newPasswordValid.value) return '新密码需包含大小写字母、数字、符号中的至少三类'
  if (newPassword.value !== confirmPassword.value) return '两次输入的新密码不一致'
  return ''
})

async function submit() {
  if (submitting.value) return
  error.value = formError.value
  if (error.value) return
  submitting.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    router.replace('/dashboard')
  } catch (exc: any) {
    error.value = exc?.message || '密码修改失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}

async function logout() {
  await auth.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="change-password-page">
    <section class="change-password-card">
      <div class="change-password-brand">
        <span><ShieldCheck :size="20" /></span>
        <div>
          <strong>邻里小栈 · 账户安全</strong>
          <p v-if="auth.mustChangePassword">首次登录需要修改初始密码后才能进入工作台。</p>
          <p v-else>定期修改密码可降低账号被盗风险。</p>
        </div>
      </div>

      <form class="change-password-form" @submit.prevent="submit">
        <label>
          <span>当前密码</span>
          <div class="change-password-input">
            <Lock :size="17" />
            <input v-model="oldPassword" :type="showPassword ? 'text' : 'password'"
                   autocomplete="current-password" placeholder="请输入当前密码" />
          </div>
        </label>
        <label>
          <span>新密码</span>
          <div class="change-password-input">
            <Lock :size="17" />
            <input v-model="newPassword" :type="showPassword ? 'text' : 'password'"
                   autocomplete="new-password" placeholder="至少 12 位，含大小写/数字/符号三类" />
          </div>
        </label>
        <label>
          <span>确认新密码</span>
          <div class="change-password-input">
            <Lock :size="17" />
            <input v-model="confirmPassword" :type="showPassword ? 'text' : 'password'"
                   autocomplete="new-password" placeholder="请再次输入新密码" />
          </div>
        </label>

        <div class="change-password-tools">
          <button type="button" class="link-button" @click="showPassword = !showPassword">
            <EyeOff v-if="!showPassword" :size="15" /><Eye v-else :size="15" />
            {{ showPassword ? '隐藏密码' : '显示密码' }}
          </button>
          <span>至少 12 位，大小写字母/数字/符号至少三类</span>
        </div>

        <div v-if="error" class="change-password-error">
          <AlertCircle :size="15" /><span>{{ error }}</span>
        </div>

        <div class="change-password-actions">
          <button type="button" class="ghost-button" @click="logout">退出登录</button>
          <button type="submit" class="primary-button" :disabled="submitting">
            {{ submitting ? '正在保存…' : '保存并进入工作台' }}
          </button>
        </div>
      </form>
    </section>
  </div>
</template>

<style scoped>
.change-password-page { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 32px 18px; background: #f7f7fa; }
.change-password-card { width: min(480px, 100%); padding: 30px 30px 26px; border: 1px solid #ebe9ef; border-radius: 18px; background: #fff; box-shadow: 0 20px 48px rgba(33, 29, 56, .08); }
.change-password-brand { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 24px; }
.change-password-brand > span { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; border-radius: 12px; color: #6f59d4; background: #f1edfc; }
.change-password-brand strong { display: block; color: #211d38; font-size: 17px; }
.change-password-brand p { margin: 4px 0 0; color: #8a8494; font-size: var(--font-size-body); line-height: 1.6; }
.change-password-form { display: flex; flex-direction: column; gap: 16px; }
.change-password-form label > span { display: block; margin-bottom: 6px; color: #5b5566; font-size: var(--font-size-body); font-weight: 500; }
.change-password-input { display: flex; align-items: center; gap: 9px; height: 42px; padding: 0 12px; border: 1px solid #e1dee5; border-radius: 10px; color: #a8a2b3; background: #fff; }
.change-password-input input { flex: 1; min-width: 0; height: 100%; border: 0; outline: none; color: #3d3945; background: transparent; font-size: var(--font-size-body); }
.change-password-tools { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #98929f; font-size: var(--font-size-caption); }
.link-button { display: inline-flex; align-items: center; gap: 5px; border: 0; color: #6f59d4; background: transparent; font-size: var(--font-size-caption); cursor: pointer; }
.change-password-error { display: flex; align-items: center; gap: 7px; padding: 9px 11px; border-radius: 8px; color: #b54a55; background: #fff5f6; font-size: var(--font-size-body); }
.change-password-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 4px; }
.ghost-button { height: 38px; padding: 0 15px; border: 1px solid #e1dee5; border-radius: 9px; color: #6e6879; background: #fff; font-size: var(--font-size-body); cursor: pointer; }
</style>
