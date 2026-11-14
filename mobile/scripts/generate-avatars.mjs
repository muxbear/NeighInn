/**
 * 生成内置头像库（4 类 × 3 个）与通用占位图。
 * 运行：node scripts/generate-avatars.mjs
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const avatarDir = join(__dirname, '..', 'static', 'avatars')
const placeholderDir = join(__dirname, '..', 'static', 'placeholders')
mkdirSync(avatarDir, { recursive: true })
mkdirSync(placeholderDir, { recursive: true })

const A = (bg1, bg2, art, accent = '') => `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="${bg1}"/>
      <stop offset="1" stop-color="${bg2}"/>
    </linearGradient>
  </defs>
  <rect width="120" height="120" fill="url(#bg)"/>
  <circle cx="60" cy="60" r="46" fill="${accent || 'rgba(255,255,255,.20)'}"/>
  ${art}
</svg>
`

const avatars = {
  'avatar-person-1': A(
    '#FFE7D3',
    '#FFD0B0',
    `<circle cx="60" cy="47" r="20" fill="#F6C7A5"/>
     <path d="M38 46c0-14 10-23 22-23s22 9 22 23c-6-7-13-10-22-10s-16 3-22 10z" fill="#5A3A2A"/>
     <path d="M30 108c2-21 14-31 30-31s28 10 30 31z" fill="#FF8B57"/>
     <circle cx="53" cy="48" r="2" fill="#4B372B"/><circle cx="67" cy="48" r="2" fill="#4B372B"/>
     <path d="M55 56c3 3 7 3 10 0" stroke="#B26B58" stroke-width="2" stroke-linecap="round" fill="none"/>`
  ),
  'avatar-person-2': A(
    '#E6F4FF',
    '#CBE7FF',
    `<circle cx="60" cy="47" r="20" fill="#F7D4B8"/>
     <path d="M38 48c0-15 10-24 22-24 14 0 22 10 22 25-4-8-11-12-22-12-10 0-17 4-22 11z" fill="#7A4B32"/>
     <path d="M30 108c2-21 14-31 30-31s28 10 30 31z" fill="#6BB88A"/>
     <circle cx="53" cy="48" r="2" fill="#4B372B"/><circle cx="67" cy="48" r="2" fill="#4B372B"/>
     <path d="M55 57c3 2.5 7 2.5 10 0" stroke="#B26B58" stroke-width="2" stroke-linecap="round" fill="none"/>`
  ),
  'avatar-person-3': A(
    '#FFF2D9',
    '#FFE0AE',
    `<circle cx="60" cy="47" r="20" fill="#EFC3A0"/>
     <circle cx="40" cy="31" r="9" fill="#3E2B23"/><circle cx="80" cy="31" r="9" fill="#3E2B23"/>
     <path d="M39 46c0-14 9-22 21-22s22 8 22 22c-6-6-13-9-22-9s-16 3-21 9z" fill="#3E2B23"/>
     <path d="M30 108c2-21 14-31 30-31s28 10 30 31z" fill="#5DADE2"/>
     <circle cx="53" cy="49" r="2" fill="#4B372B"/><circle cx="67" cy="49" r="2" fill="#4B372B"/>
     <path d="M55 57c3 3 7 3 10 0" stroke="#B26B58" stroke-width="2" stroke-linecap="round" fill="none"/>`
  ),
  'avatar-animal-1': A(
    '#E9F8EF',
    '#CDEEDB',
    `<circle cx="43" cy="39" r="14" fill="#8B5E3C"/><circle cx="77" cy="39" r="14" fill="#8B5E3C"/>
     <circle cx="43" cy="39" r="7" fill="#D9A777"/><circle cx="77" cy="39" r="7" fill="#D9A777"/>
     <circle cx="60" cy="62" r="27" fill="#A9714B"/>
     <ellipse cx="60" cy="71" rx="13" ry="10" fill="#F3DCC3"/>
     <circle cx="51" cy="57" r="3" fill="#3E2B23"/><circle cx="69" cy="57" r="3" fill="#3E2B23"/>
     <ellipse cx="60" cy="67" rx="5" ry="4" fill="#3E2B23"/>
     <path d="M60 71v4M55 77c3 2 7 2 10 0" stroke="#6E4A32" stroke-width="2" stroke-linecap="round" fill="none"/>`
  ),
  'avatar-animal-2': A(
    '#FFF0E5',
    '#FFDCC6',
    `<path d="M40 42 34 18l22 10z" fill="#F0A46B"/><path d="M80 42 86 18 64 28z" fill="#F0A46B"/>
     <path d="M40 30l-2-7 9 4z" fill="#FFD5C0"/><path d="M80 30l2-7-9 4z" fill="#FFD5C0"/>
     <circle cx="60" cy="62" r="27" fill="#F3B581"/>
     <circle cx="51" cy="58" r="3" fill="#3E2B23"/><circle cx="69" cy="58" r="3" fill="#3E2B23"/>
     <path d="M56 68h8l-4 4z" fill="#C56B4A"/>
     <path d="M60 72v3M56 77c2.5 1.5 5.5 1.5 8 0" stroke="#8A4F35" stroke-width="2" stroke-linecap="round" fill="none"/>
     <path d="M38 68h10M38 73h9M82 68H72M82 73h-9" stroke="#D9905F" stroke-width="2" stroke-linecap="round"/>`
  ),
  'avatar-animal-3': A(
    '#F1EEFF',
    '#DDD6FF',
    `<ellipse cx="60" cy="38" rx="10" ry="22" fill="#F3E8E1"/>
     <ellipse cx="60" cy="38" rx="4" ry="14" fill="#FFC9C9"/>
     <circle cx="60" cy="64" r="26" fill="#FBE9DF"/>
     <circle cx="51" cy="60" r="3" fill="#3E2B23"/><circle cx="69" cy="60" r="3" fill="#3E2B23"/>
     <path d="M57 68h6l-3 3z" fill="#E88C8C"/>
     <path d="M60 71v3M56 77c2.5 1.5 5.5 1.5 8 0" stroke="#A36B62" stroke-width="2" stroke-linecap="round" fill="none"/>
     <circle cx="44" cy="71" r="5" fill="#FFC9C9" opacity=".6"/><circle cx="76" cy="71" r="5" fill="#FFC9C9" opacity=".6"/>`
  ),
  'avatar-landmark-1': A(
    '#FFF4E0',
    '#FFE3B0',
    `<path d="M28 100h64" stroke="#A57628" stroke-width="3" stroke-linecap="round"/>
     <path d="M38 100V63h44v37M32 63h56l-7-10H39z" fill="#E2B05E"/>
     <path d="M45 53h30l-5-9H50z" fill="#C68E3D"/>
     <path d="M52 44h16l-3-8h-10z" fill="#A57628"/>
     <path d="M56 36h8l-4-9z" fill="#C68E3D"/>
     <rect x="50" y="74" width="8" height="26" fill="#8A5E26"/><rect x="62" y="74" width="8" height="26" fill="#8A5E26"/>
     <path d="M38 100h44" stroke="#8A5E26" stroke-width="2"/>`
  ),
  'avatar-landmark-2': A(
    '#E8F3FF',
    '#C9E2FF',
    `<path d="M27 102h66" stroke="#447FA7" stroke-width="3" stroke-linecap="round"/>
     <path d="M44 102V52h32v50M38 52l22-25 22 25z" fill="#7FB6DC"/>
     <path d="M50 52h20M44 64h32M44 76h32M44 88h32" stroke="#4E94C4" stroke-width="2"/>
     <path d="M60 27V17M51 22h18" stroke="#4E94C4" stroke-width="2.5" stroke-linecap="round"/>
     <rect x="55" y="84" width="10" height="18" fill="#447FA7"/>`
  ),
  'avatar-landmark-3': A(
    '#F0F7EC',
    '#D6EBCE',
    `<path d="M22 102h76" stroke="#4E765F" stroke-width="3" stroke-linecap="round"/>
     <path d="M26 102 60 34l34 68z" fill="#8FBE9B"/>
     <path d="M40 102 60 64l20 38z" fill="#5E9870"/>
     <path d="M55 61h10v9H55z" fill="#F7F4EF"/>
     <path d="M60 33v-8" stroke="#4E765F" stroke-width="2.5" stroke-linecap="round"/>
     <path d="M52 47h16l-8-10z" fill="#F7F4EF" opacity=".8"/>
     <circle cx="36" cy="42" r="7" fill="#FFD98A"/><circle cx="85" cy="36" r="5" fill="#FFD98A"/>`
  ),
  'avatar-nature-1': A(
    '#FFF7DF',
    '#FFE8B8',
    `<circle cx="45" cy="43" r="18" fill="#FFB648"/>
     <path d="M18 98c8-24 22-36 42-36s34 12 42 36z" fill="#7DA981"/>
     <path d="M10 104c10-18 24-27 42-27s32 9 42 27z" fill="#5E8D68"/>
     <path d="M66 72c6-8 14-12 24-13-2 11-9 19-21 20z" fill="#4E765F"/>`
  ),
  'avatar-nature-2': A(
    '#EAF9F2',
    '#C9EEDC',
    `<path d="M60 105C38 88 30 70 38 52c8-17 26-25 48-27 2 24-6 46-26 63z" fill="#6BB88A"/>
     <path d="M60 105C48 84 40 68 38 52" stroke="#3F7E58" stroke-width="2.5" stroke-linecap="round" fill="none"/>
     <path d="M48 74c9-2 16-7 22-16M53 86c9-2 16-6 22-14" stroke="#3F7E58" stroke-width="2" stroke-linecap="round" fill="none"/>
     <circle cx="85" cy="30" r="7" fill="#FFD98A"/>`
  ),
  'avatar-nature-3': A(
    '#E8F6FF',
    '#C7E7FA',
    `<circle cx="42" cy="38" r="15" fill="#FFD98A"/>
     <path d="M6 98c12-16 24-24 38-24s27 8 38 24c6 9 11 14 20 16H6z" fill="#8FC7E8"/>
     <path d="M10 94c12-12 22-18 34-18s23 6 34 18" stroke="#5DADE2" stroke-width="2.5" fill="none" stroke-linecap="round"/>
     <path d="M58 70c8-9 16-13 27-14-2 12-10 20-24 21z" fill="#4E94C4"/>
     <path d="M28 78c6-5 12-7 19-7" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round"/>`
  ),
}

for (const [name, svg] of Object.entries(avatars)) {
  writeFileSync(join(avatarDir, `${name}.svg`), svg, 'utf8')
}

const placeholder = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="376" viewBox="0 0 400 376">
  <defs>
    <linearGradient id="p" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#FFF3E8"/>
      <stop offset="1" stop-color="#F4EDE6"/>
    </linearGradient>
  </defs>
  <rect width="400" height="376" fill="url(#p)"/>
  <g stroke="#E8B896" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M150 230l50-50 50 50 25-25 35 35"/>
    <rect x="130" y="150" width="140" height="110" rx="12"/>
    <circle cx="180" cy="185" r="12"/>
  </g>
  <text x="200" y="300" text-anchor="middle" font-family="-apple-system, sans-serif" font-size="16" fill="#C9A58D">图片加载中</text>
</svg>
`

const imageError = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="376" viewBox="0 0 400 376">
  <rect width="400" height="376" fill="#F7F2EC"/>
  <path d="M160 210l35-35 30 30 20-20 35 35" stroke="#D9C4B3" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="150" y="150" width="130" height="100" rx="10" stroke="#D9C4B3" stroke-width="5" fill="none"/>
  <text x="200" y="292" text-anchor="middle" font-family="-apple-system, sans-serif" font-size="16" fill="#BFA997">图片走丢了</text>
</svg>
`

const emptyBox = `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
  <rect width="160" height="160" rx="60" fill="#FFF1E5"/>
  <g stroke="#FF7A3D" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M50 70l30-16 30 16v34l-30 16-30-16zM50 70l30 16 30-16M80 86v34"/>
  </g>
</svg>
`

writeFileSync(join(placeholderDir, 'item-placeholder.svg'), placeholder, 'utf8')
writeFileSync(join(placeholderDir, 'image-error.svg'), imageError, 'utf8')
writeFileSync(join(placeholderDir, 'empty-box.svg'), emptyBox, 'utf8')

console.log(`[avatars] generated ${Object.keys(avatars).length} avatars + 3 placeholders`)
