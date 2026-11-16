/**
 * 生成 24×24 线性图标的多状态 SVG 资源。
 * 非 Web 端不支持内联 SVG 换色，因此按状态导出多份（详见详细设计 4.5 / 14.3）。
 * 运行：node scripts/generate-icons.mjs
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const outDir = join(__dirname, '..', 'static', 'icons')
mkdirSync(outDir, { recursive: true })

const COLORS = {
  default: '#8F8A86',
  active: '#FF7A3D',
  white: '#FFFFFF',
  dark: '#4B372B',
  secondary: '#666666',
  tertiary: '#999999',
  green: '#4E9870',
  blue: '#4E94C4',
  gold: '#A8772F',
  danger: '#B95A31',
  wechat: '#07C160',
}

const S = (d, extra = '') =>
  `<path d="${d}" stroke="%C%" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"${extra}/>`
const C = (cx, cy, r, extra = '') =>
  `<circle cx="${cx}" cy="${cy}" r="${r}" stroke="%C%" stroke-width="1.8"${extra}/>`
const R = (x, y, w, h, rx) =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" stroke="%C%" stroke-width="1.8"/>`

const ICONS = {
  home: {
    line: S('M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z'),
    filled: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z" fill="%C%"/>',
  },
  pin: {
    line: S('M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11z') + C(12, 10, 2.5),
    filled:
      '<path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11z" fill="%C%"/>' +
      '<circle cx="12" cy="10" r="2.5" fill="#FFFFFF"/>',
  },
  plus: { line: S('M12 5v14M5 12h14') },
  message: {
    line: S('M21 11.5a8.5 8.5 0 0 1-8.5 8.5H6l-3 2 .8-4.6A8.5 8.5 0 1 1 21 11.5z'),
    filled:
      '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H6l-3 2 .8-4.6A8.5 8.5 0 1 1 21 11.5z" fill="%C%"/>' +
      '<circle cx="8.5" cy="11.5" r="1" fill="#FFFFFF"/><circle cx="12.5" cy="11.5" r="1" fill="#FFFFFF"/><circle cx="16.5" cy="11.5" r="1" fill="#FFFFFF"/>',
  },
  user: {
    line: C(12, 8, 4) + S('M4 21c0-4.2 3.6-6.5 8-6.5s8 2.3 8 6.5'),
    filled:
      '<circle cx="12" cy="8" r="4" fill="%C%"/><path d="M4 21c0-4.2 3.6-6.5 8-6.5s8 2.3 8 6.5z" fill="%C%"/>',
  },
  search: { line: C(11, 11, 7) + S('M20 20l-4-4') },
  bell: {
    line:
      S('M18 8a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9') +
      S('M10.5 21a2 2 0 0 0 3 0'),
  },
  chevron: { line: S('M9 5l7 7-7 7') },
  heart: {
    line: S('M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z'),
    filled:
      '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z" fill="%C%"/>',
  },
  walk: {
    line:
      C(13, 4.5, 2) +
      S('M13 7l-2.5 5 3.5 2.5-1.5 6.5M10.5 12l-2.5 4M13 9l4 2.5 2 .5'),
  },
  bike: {
    line:
      C(5.5, 17.5, 3.2) +
      C(18.5, 17.5, 3.2) +
      S('M8.5 17.5 12.5 7h3l3 10.5M10 7h5M12.5 17.5h3'),
  },
  car: {
    line:
      S('M4 16l1.6-6.2A2 2 0 0 1 7.5 8h9a2 2 0 0 1 1.9 1.8L20 16M3 16h18v3H3z') +
      C(7, 19, 1.6) +
      C(17, 19, 1.6) +
      S('M6 12h12'),
  },
  shield: {
    line: S('M12 3l8 3v6c0 5-3.4 8.5-8 9-4.6-.5-8-4-8-9V6z') + S('M9 12l2 2 4-4'),
  },
  spark: {
    line:
      S('M12 3l1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z') +
      S('M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z'),
  },
  star: {
    line: S('M12 3.2 14.6 8.9 20.8 9.7 16.2 14.1 17.4 20.3 12 17.2 6.6 20.3 7.8 14.1 3.2 9.7 9.4 8.9Z'),
    filled:
      '<path d="M12 3.2 14.6 8.9 20.8 9.7 16.2 14.1 17.4 20.3 12 17.2 6.6 20.3 7.8 14.1 3.2 9.7 9.4 8.9Z" fill="%C%"/>',
  },
  sliders: {
    line:
      S('M4 7h8M16 7h4M4 12h4M12 12h8M4 17h10M18 17h2') +
      C(14, 7, 2) +
      C(10, 12, 2) +
      C(16, 17, 2),
  },
  arrow: { line: S('M4 12h16M14 6l6 6-6 6') },
  share: { line: S('M4 12v8h16v-8M12 16V3M8 7l4-4 4 4') },
  camera: {
    line: S('M4 8h3l2-3h6l2 3h3v11H4z') + C(12, 13, 3.4),
  },
  box: {
    line: S('M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8'),
  },
  wallet: {
    line: R(3, 6, 18, 13, 2) + S('M3 10h18M16 14h2'),
  },
  order: {
    line: S('M7 3h10v18l-2.5-1.6L12 21l-2.5-1.6L7 21z') + S('M10 8h4M10 12h4'),
  },
  settings: {
    line:
      C(12, 12, 3) +
      S('M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z'),
  },
  friend: {
    line: C(9, 8, 3) + S('M3 20c0-3 2.5-5 6-5s6 2 6 5') + C(17, 9, 2.5) + S('M16 15c3 0 5 1.5 5 4'),
  },
  check: { line: S('M4.5 12.5l5 5L20 7') },
  swap: { line: S('M4 8h14l-3.5-3.5M20 16H6l3.5 3.5') },
  gift: {
    line:
      S('M3 9h18v4H3zM5 13h14v8H5zM12 9v12') +
      S('M12 9c-2.2 0-4.5-.8-4.5-2.7C7.5 4.5 10 4 12 9zM12 9c2.2 0 4.5-.8 4.5-2.7C16.5 4.5 14 4 12 9z'),
  },
  clock: { line: C(12, 12, 9) + S('M12 7v5.5l3.5 2') },
  child: {
    line: C(12, 5.5, 2.2) + S('M12 8v5M8 21v-4l-2-3 3-2h6l3 2-2 3v4M9 12l-1 5M15 12l1 5'),
  },
  pet: {
    line:
      C(7, 9, 1.7) +
      C(10.5, 6.5, 1.7) +
      C(14, 6.5, 1.7) +
      C(17, 9, 1.7) +
      S('M12 12c2.8 0 5 2.1 5 4.6 0 2-1.7 3.4-3.6 3.4-.8 0-1-.4-1.4-.4s-.6.4-1.4.4C8.7 20 7 18.6 7 16.6 7 14.1 9.2 12 12 12z'),
  },
  book: {
    line: S('M4 5a2 2 0 0 1 2-2h14v18H6a2 2 0 0 0-2 2V5z') + S('M8 3v18M12 7h5M12 11h4'),
  },
  cake: {
    line:
      S('M4 20h16M5 20v-6h14v6M5 14c0-1.7 1.3-3 3-3s3 1.3 3 3 1.3 3 3 3 3-1.3 3-3 1.3-3 3-3 3 1.3 3 3M12 8V4'),
  },
  megaphone: {
    line: S('M4 10v4l3 .8L16 20V4L7 9.2 4 10z') + S('M19 8a3 3 0 0 1 0 8M7 14.8V19'),
  },
  alert: { line: S('M12 3l10 18H2z') + S('M12 9v5M12 18h.01') },
  phone: {
    line: S('M5 3h3.5l2 5-2.2 1.6a13 13 0 0 0 5.1 5.1L15 12.5l5 2V18a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2z'),
  },
  lock: {
    line: R(4.5, 10.5, 15, 10, 2) + S('M8 10.5V7a4 4 0 0 1 8 0v3.5'),
  },
  wechat: {
    line:
      S('M9.5 4C5.9 4 3 6.4 3 9.4c0 1.7.9 3.2 2.4 4.2L5 16l2.6-1.4c.6.2 1.2.3 1.9.3') +
      S('M15 8.5c3.3 0 6 2.2 6 5s-2.7 5-6 5c-.6 0-1.2-.1-1.7-.2L11 19.5l.4-2.1c-1.4-.9-2.4-2.3-2.4-3.9 0-2.8 2.7-5 6-5z') +
      `<circle cx="7" cy="8.5" r=".8" fill="%C%"/><circle cx="11" cy="8.5" r=".8" fill="%C%"/><circle cx="13.5" cy="13" r=".8" fill="%C%"/><circle cx="17" cy="13" r=".8" fill="%C%"/>`,
  },
  play: {
    line: S('M8 5.5 19 12 8 18.5z'),
    filled: '<path d="M8 5.5 19 12 8 18.5z" fill="%C%"/>',
  },
  image: {
    line: R(3, 3, 18, 18, 3) + C(8.5, 8.5, 1.5) + S('M21 15l-5-5L5 21'),
  },
  eye: {
    line: S('M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z') + C(12, 12, 3),
  },
}

function wrap(body, color, filled) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="${filled ? color : 'none'}">
${body.split('%C%').join(color)}
</svg>
`
}

let count = 0
for (const [name, def] of Object.entries(ICONS)) {
  for (const [state, color] of Object.entries(COLORS)) {
    const lineFile = join(outDir, `icon-${name}-24--${state}.svg`)
    writeFileSync(lineFile, wrap(def.line, color, false), 'utf8')
    count += 1

    if (def.filled) {
      const filledFile = join(outDir, `icon-${name}-24-filled--${state}.svg`)
      writeFileSync(filledFile, wrap(def.filled, color, true), 'utf8')
      count += 1
    }
  }
}

// 半星无法由 line/filled 两态表达，单独生成金色半星（信用星级）。
const STAR_PATH = 'M12 3.2 14.6 8.9 20.8 9.7 16.2 14.1 17.4 20.3 12 17.2 6.6 20.3 7.8 14.1 3.2 9.7 9.4 8.9Z'
writeFileSync(
  join(outDir, 'icon-star-24-half--gold.svg'),
  `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <path d="${STAR_PATH}" fill="#F1ECE5"/>
  <path d="M12 3.2 9.4 8.9 3.2 9.7 7.8 14.1 6.6 20.3 12 17.2Z" fill="${COLORS.gold}"/>
  <path d="${STAR_PATH}" fill="none" stroke="${COLORS.gold}" stroke-width="1.2" stroke-linejoin="round"/>
</svg>
`,
  'utf8',
)
count += 1

console.log(`[icons] generated ${count} svg files -> ${outDir}`)
