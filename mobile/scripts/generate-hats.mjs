/**
 * 生成物品卡片卖家等级官帽（1–9 级，汉制意形）。
 * 1–3 级进贤冠（梁数递增）、4–6 级武冠（缨数递增）、7–9 级冕冠（旒数递增）。
 * 运行：node scripts/generate-hats.mjs
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const outDir = join(__dirname, '..', 'static', 'hats')
mkdirSync(outDir, { recursive: true })

const C = {
  cap: '#2E2722',
  brim: '#1E1916',
  ribbon: '#B5483A',
  bronze: '#B58A56',
  bronzeDark: '#7E5A32',
  bronzeLine: '#6E4A27',
  red: '#7E3128',
  redDark: '#5A211B',
  redLight: '#C84A3A',
  gold: '#D4A055',
  goldDark: '#9C6F2C',
  goldDeep: '#8A5F2C',
  jade: '#5FA98A',
}

const base = `
  <path d="M13 26V18.8C13 15.7 17.9 13.6 24 13.6s11 2.1 11 5.2V26z" fill="${C.cap}"/>
  <rect x="8" y="22.2" width="32" height="3.6" rx="1.8" fill="${C.brim}"/>
  <path d="M12.5 23.2c-2.4 1.2-3.8 2.5-4.5 4.1" stroke="${C.ribbon}" stroke-width="1.7" stroke-linecap="round" fill="none"/>
  <path d="M35.5 23.2c2.4 1.2 3.8 2.5 4.5 4.1" stroke="${C.ribbon}" stroke-width="1.7" stroke-linecap="round" fill="none"/>
`

function civil(n) {
  const ridges = Array.from({ length: n }, (_, i) => {
    const x = 24 + (i - (n - 1) / 2) * 5
    return `<path d="M${x} 8.8 24 14.4" stroke="${C.bronzeLine}" stroke-width="1.1" stroke-linecap="round"/>`
  }).join('')
  return `
  <path d="M11 15.2 37 13.2 34 8.2 14 8.2Z" fill="${C.bronze}" stroke="${C.bronzeDark}" stroke-width="1" stroke-linejoin="round"/>
  ${ridges}
  `
}

function military(n) {
  const plumes = Array.from({ length: n }, (_, i) => {
    const x = 24 + (i - (n - 1) / 2) * 4
    return `<path d="M${x} 10.2c-1.8-3-1.6-6 .6-8.2" stroke="${C.redLight}" stroke-width="1.8" stroke-linecap="round" fill="none"/>`
  }).join('')
  return `
  <path d="M12.5 14.6c0-4.3 5.1-7.1 11.5-7.1s11.5 2.8 11.5 7.1Z" fill="${C.red}" stroke="${C.redDark}" stroke-width="1"/>
  <path d="M13.6 15.6h20.8" stroke="${C.gold}" stroke-width="1.2" stroke-linecap="round"/>
  ${plumes}
  `
}

function imperial(n) {
  const beads = Array.from({ length: n }, (_, i) => {
    const x = 24 + (i - (n - 1) / 2) * 6
    return `<path d="M${x} 15.2v4.4" stroke="${C.goldDeep}" stroke-width=".8"/><circle cx="${x}" cy="20.2" r="1.3" fill="${C.jade}"/>`
  }).join('')
  return `
  <path d="M13.5 14.4 34.5 14.4 32 8.8 16 8.8Z" fill="${C.gold}" stroke="${C.goldDark}" stroke-width="1" stroke-linejoin="round"/>
  <path d="M16.4 9.4c0-3.6 3.2-6 7.6-6s7.6 2.4 7.6 6Z" fill="${C.gold}" stroke="${C.goldDark}" stroke-width="1"/>
  <path d="M10.5 15.3h27" stroke="${C.goldDark}" stroke-width="1"/>
  ${beads}
  <circle cx="24" cy="2.8" r="1.5" fill="${C.ribbon}"/>
  `
}

for (let level = 1; level <= 9; level += 1) {
  let top = ''
  if (level <= 3) top = civil(level)
  else if (level <= 6) top = military(level - 3)
  else top = imperial(level - 6)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="28" viewBox="0 0 48 28">
${top}
${base}
</svg>
`
  writeFileSync(join(outDir, `han-hat-${level}.svg`), svg, 'utf8')
}

console.log('[hats] generated 9 svg files -> ' + outDir)
