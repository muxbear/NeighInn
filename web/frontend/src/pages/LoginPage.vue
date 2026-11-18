<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  Coffee,
  Eye,
  EyeOff,
  Fingerprint,
  HandHeart,
  Home,
  Lock,
  LockKeyhole,
  Megaphone,
  ShieldCheck,
  ShoppingBag,
  UserRound,
  Users,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const rememberDevice = ref(true)
const captcha = ref('')
const failedAttempts = ref(0)
const error = ref('')
const capsLock = ref(false)
const submitting = ref(false)
const locked = ref(false)
let lockTimer: number | undefined

const needsCaptcha = computed(() => failedAttempts.value >= 2)

const capabilities = [
  { icon: Megaphone, title: '社区喇叭', text: '重要消息及时抵达', value: '82.4% 触达' },
  { icon: ShoppingBag, title: '社区物品', text: '让闲置在邻里流转', value: '386 件在售' },
  { icon: HandHeart, title: '邻里互助', text: '每一次求助都有回应', value: '94.6% 完成' },
  { icon: Coffee, title: '社区生活', text: '发现家门口的好生活', value: '248 篇内容' },
]

function clearError() {
  error.value = ''
}

function fail(message: string) {
  failedAttempts.value += 1
  error.value = message
  if (failedAttempts.value >= 5) {
    locked.value = true
    error.value = '连续失败次数过多，登录已临时锁定 30 秒'
    lockTimer = window.setTimeout(() => {
      locked.value = false
      failedAttempts.value = 0
      captcha.value = ''
      error.value = ''
    }, 30000)
  }
}

async function handleSubmit() {
  if (locked.value || submitting.value) return
  error.value = ''
  if (!username.value.trim() || password.value.length < 8) {
    fail('账号或密码不正确，请检查后重试')
    return
  }
  if (needsCaptcha.value && captcha.value.toUpperCase() !== '7K9P') {
    fail('安全验证码不正确，请重新输入')
    return
  }
  submitting.value = true
  try {
    await auth.login(username.value, password.value)
    router.replace((route.query.redirect as string) || '/dashboard')
  } catch (exc: any) {
    fail(exc?.code === 40102 ? '账号或密码不正确，请检查后重试' : (exc?.message || '账号或密码不正确，请检查后重试'))
  } finally {
    submitting.value = false
  }
}

function onPasswordKeyUp(event: KeyboardEvent) {
  capsLock.value = event.getModifierState?.('CapsLock') ?? false
}

function forgetPassword() {
  error.value = '请联系系统管理员重置密码'
}

function footerAction(label: string) {
  error.value = `${label}：请联系系统管理员`
}

onMounted(() => {
  if (auth.isAuthenticated) router.replace('/dashboard')
})

onUnmounted(() => {
  if (lockTimer) window.clearTimeout(lockTimer)
})
</script>

<template>
  <div class="login-page">
    <section class="login-brand-panel">
      <div class="login-brand">
        <div class="login-brand-mark"><Home :size="20" :stroke-width="2.4" /></div>
        <div>
          <strong>邻里小栈</strong>
          <span>社区运营管理平台</span>
        </div>
        <div class="login-brand-status"><i />服务稳定运行</div>
      </div>

      <div class="login-brand-content">
        <div class="login-story-copy">
          <div class="login-eyebrow"><span />连接社区里的每一件小事</div>
          <h1>把社区里重要的事，<br />稳稳接住</h1>
          <p>让消息有回应，让闲置有去处，让邻里互助更快发生，也让每一位社区居民被妥善服务。</p>
        </div>

        <div class="login-community-scene">
          <div class="scene-location">
            <div class="scene-home"><Home :size="18" /></div>
            <div>
              <span>正在服务</span>
              <strong>云栖里社区</strong>
            </div>
            <em>4,582 位认证住户</em>
          </div>

          <div class="scene-capabilities">
            <div v-for="item in capabilities" :key="item.title">
              <span><component :is="item.icon" :size="16" /></span>
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.text }}</p>
              </div>
              <em>{{ item.value }}</em>
            </div>
          </div>

          <div class="scene-response">
            <div class="scene-response-avatars"><span>林</span><span>陈</span><span>周</span><span><Users :size="12" /></span></div>
            <div>
              <strong>今天，社区里已有 126 次温暖回应</strong>
              <p>“需要借用梯子”的求助刚刚完成匹配</p>
            </div>
            <span class="scene-response-live"><i />实时</span>
          </div>
        </div>
      </div>

      <div class="login-brand-footer">
        <span><ShieldCheck :size="14" />分级权限</span>
        <span><LockKeyhole :size="13" />数据隔离</span>
        <span><Fingerprint :size="13" />操作审计</span>
        <em>© 2025 邻里小栈</em>
      </div>
    </section>

    <section class="login-form-panel">
      <div class="login-form-wrap">
        <div class="login-mobile-brand">
          <div class="login-brand-mark"><Home :size="19" /></div>
          <strong>邻里小栈</strong>
        </div>

        <div class="login-welcome">
          <span>管理员安全登录</span>
          <h2>欢迎回来</h2>
          <p>登录邻里小栈后台，继续管理您的社区。</p>
        </div>

        <form class="login-form" @submit.prevent="handleSubmit">
          <label>
            <span>用户名</span>
            <div :class="error ? 'login-input error' : 'login-input'">
              <UserRound :size="17" />
              <input
                v-model="username"
                autocomplete="username"
                spellcheck="false"
                placeholder="请输入用户名"
                @input="clearError"
              />
            </div>
          </label>

          <label>
            <div class="login-label-row">
              <span>密码</span>
              <button type="button" @click="forgetPassword">忘记密码？</button>
            </div>
            <div :class="error ? 'login-input error' : 'login-input'">
              <Lock :size="17" />
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                placeholder="请输入密码"
                @input="clearError"
                @keyup="onPasswordKeyUp"
              />
              <button type="button" class="password-toggle" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
                <EyeOff v-if="showPassword" :size="17" /><Eye v-else :size="17" />
              </button>
            </div>
            <em v-if="capsLock" class="caps-lock"><AlertCircle :size="12" />大写锁定已开启</em>
          </label>

          <label v-if="needsCaptcha">
            <span>安全验证</span>
            <div class="captcha-row">
              <div :class="error ? 'login-input error' : 'login-input'">
                <Fingerprint :size="17" />
                <input v-model="captcha" maxlength="4" placeholder="输入右侧字符" @input="clearError" />
              </div>
              <div class="captcha-code" aria-label="安全验证码">7K9P<i /><i /><i /></div>
            </div>
          </label>

          <div v-if="error" class="login-error"><AlertCircle :size="15" /><span>{{ error }}</span></div>

          <div class="login-options">
            <label><input v-model="rememberDevice" type="checkbox" /><span>信任此设备 7 天</span></label>
            <span><LockKeyhole :size="12" />传输已加密</span>
          </div>

          <button class="login-submit" type="submit" :disabled="locked || submitting">
            <template v-if="submitting"><i />正在验证安全凭据</template>
            <template v-else-if="locked">登录已临时锁定</template>
            <template v-else>安全登录</template>
          </button>
        </form>

        <div class="login-security-card">
          <ShieldCheck :size="17" />
          <div>
            <strong>安全会话保护</strong>
            <p>登录行为将记录设备、时间与安全环境；连续失败 5 次将临时锁定。</p>
          </div>
        </div>
      </div>

      <footer class="login-form-footer">
        <button type="button" @click="footerAction('隐私政策')">隐私政策</button><i />
        <button type="button" @click="footerAction('安全中心')">安全中心</button><i />
        <button type="button" @click="footerAction('联系我们')">联系我们</button>
      </footer>
    </section>
  </div>
</template>
