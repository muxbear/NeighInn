<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { MoreHorizontal } from 'lucide-vue-next'

/** 行内更多操作菜单：三点图标按钮触发，菜单项 = 图标 + 文字。 */
type ActionMenuItem = {
  key: string
  label: string
  icon?: any
  danger?: boolean
  disabled?: boolean
}

const props = withDefaults(defineProps<{
  items: ActionMenuItem[]
  label?: string
  iconSize?: number
}>(), { label: '更多操作', iconSize: 17 })

const emit = defineEmits<{ select: [key: string] }>()

const trigger = ref<HTMLElement | null>(null)
const menuEl = ref<HTMLElement | null>(null)
const open = ref(false)
const position = ref({ top: 0, left: 0 })

const MENU_WIDTH = 172
const ITEM_HEIGHT = 34
const MENU_PADDING = 5

function place() {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const height = props.items.length * ITEM_HEIGHT + MENU_PADDING * 2
  let left = rect.right - MENU_WIDTH
  if (left < 8) left = 8
  let top = rect.bottom + 6
  if (top + height > window.innerHeight - 8) {
    top = Math.max(8, rect.top - height - 6)
  }
  position.value = { top, left }
}

function onDocumentMouseDown(event: MouseEvent) {
  const target = event.target as Node | null
  if (!target) return
  if (trigger.value?.contains(target) || menuEl.value?.contains(target)) return
  close()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

function bindListeners() {
  document.addEventListener('mousedown', onDocumentMouseDown, true)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', close)
  window.addEventListener('scroll', close, true)
}

function unbindListeners() {
  document.removeEventListener('mousedown', onDocumentMouseDown, true)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', close)
  window.removeEventListener('scroll', close, true)
}

function close() {
  if (!open.value) return
  open.value = false
  unbindListeners()
}

function toggle() {
  if (open.value) {
    close()
    return
  }
  open.value = true
  bindListeners()
  nextTick(place)
}

function choose(item: ActionMenuItem) {
  if (item.disabled) return
  close()
  emit('select', item.key)
}

onBeforeUnmount(close)
</script>

<template>
  <span class="ni-action-menu">
    <button
      ref="trigger"
      type="button"
      class="ni-action-trigger"
      :class="{ active: open }"
      :aria-label="label"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <MoreHorizontal :size="iconSize" />
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        ref="menuEl"
        class="ni-action-menu-list"
        role="menu"
        :style="{ top: `${position.top}px`, left: `${position.left}px` }"
        @mousedown.stop
        @click.stop
      >
        <button
          v-for="item in items"
          :key="item.key"
          type="button"
          role="menuitem"
          class="ni-action-menu-item"
          :class="{ danger: item.danger, 'is-disabled': item.disabled }"
          :disabled="item.disabled"
          @click="choose(item)"
        >
          <component :is="item.icon" v-if="item.icon" :size="15" />
          <span>{{ item.label }}</span>
        </button>
      </div>
    </Teleport>
  </span>
</template>

<style scoped>
.ni-action-menu { display: inline-flex; align-items: center; }
.ni-action-trigger {
  width: 30px;
  height: 30px;
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #8f8a97;
  background: transparent;
  cursor: pointer;
  transition: color .15s ease, background .15s ease, border-color .15s ease;
}
.ni-action-trigger:hover,
.ni-action-trigger.active {
  color: #5f4abd;
  border-color: #e4def7;
  background: #f3f0fd;
}
.ni-action-trigger:focus-visible { outline: 2px solid #8d7ce0; outline-offset: 1px; }
.ni-action-menu-list {
  position: fixed;
  z-index: 2000;
  width: 172px;
  padding: 5px;
  border: 1px solid #e7e3ef;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 14px 36px rgba(38, 30, 66, .16);
}
.ni-action-menu-item {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 7px;
  color: #504b5b;
  font-size: var(--font-size-body);
  text-align: left;
  cursor: pointer;
}
.ni-action-menu-item svg { flex: 0 0 auto; color: #837c95; }
.ni-action-menu-item:hover { background: #f6f3fd; color: #5c46bd; }
.ni-action-menu-item:hover svg { color: #6a53c9; }
.ni-action-menu-item.danger { color: #c9525e; }
.ni-action-menu-item.danger svg { color: #cf5f6a; }
.ni-action-menu-item.danger:hover { background: #fdf2f3; color: #b8404c; }
.ni-action-menu-item.danger:hover svg { color: #b8404c; }
.ni-action-menu-item.is-disabled { opacity: .42; cursor: not-allowed; }
.ni-action-menu-item.is-disabled:hover { background: transparent; color: #504b5b; }
.ni-action-menu-item.is-disabled.danger:hover { color: #c9525e; }
</style>
