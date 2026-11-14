/**
 * 校验路由、相对导入与组件标签引用。
 * 运行：node scripts/check-links.mjs
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const cfg = JSON.parse(readFileSync(join(root, 'pages.json'), 'utf8'))
const routes = new Set()
cfg.pages.forEach((page) => routes.add(page.path))
;(cfg.subPackages ?? []).forEach((sub) => sub.pages.forEach((page) => routes.add(`${sub.root}/${page.path}`)))

const files = []
function walk(directory) {
  for (const entry of readdirSync(directory)) {
    const full = join(directory, entry)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      if (entry === 'node_modules' || entry === 'unpackage') continue
      walk(full)
    } else if (/\.(uvue|ts)$/.test(entry)) {
      files.push(full)
    }
  }
}
;['pages', 'components', 'stores', 'composables', 'services', 'api', 'utils', 'config', 'models', 'tests'].forEach(
  (directory) => {
    if (existsSync(join(root, directory))) walk(join(root, directory))
  },
)
files.push(join(root, 'App.uvue'))

const components = new Set(readdirSync(join(root, 'components')))
const builtin = new Set([
  'view', 'text', 'image', 'input', 'textarea', 'scroll-view', 'swiper', 'swiper-item', 'button', 'navigator',
  'slot', 'template', 'block', 'video', 'audio', 'camera', 'map', 'cover-view', 'cover-image', 'rich-text',
  'progress', 'checkbox', 'radio', 'picker', 'picker-view', 'picker-view-column', 'slider', 'switch', 'form',
  'label', 'icon', 'canvas', 'web-view', 'page-meta', 'navigation-bar', 'root-portal', 'list-view', 'list-item',
  'sticky-header', 'sticky-section', 'match-media', 'movable-area', 'movable-view', 'page-container',
])

const badRoutes = new Set()
const badImports = []
const missingTags = new Set()

for (const file of files) {
  const source = readFileSync(file, 'utf8')
  const display = file.slice(root.length + 1)
  if (file.endsWith('.uvue')) {
    for (const match of source.matchAll(/\/pages\/[A-Za-z0-9_/-]+/g)) {
      if (!routes.has(match[0].slice(1))) badRoutes.add(`${display}: ${match[0]}`)
    }
    for (const match of source.matchAll(/<([a-z][a-z0-9]*(?:-[a-z0-9]+)+)[\s>]/g)) {
      const tag = match[1]
      if (!builtin.has(tag) && !components.has(tag)) missingTags.add(`${display}: ${tag}`)
    }
  }
  for (const match of source.matchAll(/from\s+['"]([^'"]+)['"]/g)) {
    const spec = match[1]
    if (!spec.startsWith('.')) continue
    const base = resolve(dirname(file), spec)
    const candidates = [
      base,
      `${base}.ts`,
      `${base}.uvue`,
      `${base}.js`,
      join(base, 'index.ts'),
      join(base, 'index.uvue'),
      join(base, 'index.js'),
    ]
    if (!candidates.some((candidate) => existsSync(candidate) && statSync(candidate).isFile())) {
      badImports.push(`${display}: ${spec}`)
    }
  }
}

console.log(`[check-links] ${files.length} files, ${routes.size} routes`)
console.log('bad routes:', badRoutes.size ? [...badRoutes] : 'none')
console.log('bad imports:', badImports.length ? badImports : 'none')
console.log('missing component tags:', missingTags.size ? [...missingTags] : 'none')
process.exit(badRoutes.size || badImports.length || missingTags.size ? 1 : 0)
