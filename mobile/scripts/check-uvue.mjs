/**
 * .uvue 静态校验：
 * 1) 解析 SFC 结构；
 * 2) 编译模板，捕获模板语法错误；
 * 3) 转译 <script setup lang="ts">，捕获脚本语法错误；
 * 4) 编译 SCSS，捕获变量/语法错误。
 * 运行：node scripts/check-uvue.mjs
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { dirname } from 'node:path'
import { parse, compileTemplate } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as sass from 'sass'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const files = []

function walk(directory) {
  for (const entry of readdirSync(directory)) {
    const full = join(directory, entry)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      if (entry === 'node_modules' || entry === 'unpackage') continue
      walk(full)
    } else if (entry.endsWith('.uvue')) {
      files.push(full)
    }
  }
}

walk(root)

let errors = 0
for (const file of files) {
  const source = readFileSync(file, 'utf8')
  const display = relative(root, file)
  const parsed = parse(source, { filename: file })
  if (parsed.errors.length) {
    errors += parsed.errors.length
    console.log(`SFC ERROR ${display}`)
    parsed.errors.forEach((error) => console.log('  ', String(error)))
    continue
  }

  const { descriptor } = parsed
  if (descriptor.template) {
    const compiled = compileTemplate({
      source: descriptor.template.content,
      filename: file,
      id: display,
      compilerOptions: { mode: 'module' },
    })
    if (compiled.errors.length) {
      errors += compiled.errors.length
      console.log(`TEMPLATE ERROR ${display}`)
      compiled.errors.forEach((error) => console.log('  ', String(error)))
    }
  }

  const scriptContent = descriptor.scriptSetup?.content ?? descriptor.script?.content ?? ''
  if (scriptContent) {
    const result = ts.transpileModule(scriptContent, {
      compilerOptions: {
        target: ts.ScriptTarget.ES2020,
        module: ts.ModuleKind.ESNext,
        jsx: ts.JsxEmit.Preserve,
      },
      reportDiagnostics: true,
      fileName: file.replace(/\.uvue$/, '.ts'),
    })
    const diagnostics = (result.diagnostics ?? []).filter((item) => item.category === ts.DiagnosticCategory.Error)
    if (diagnostics.length) {
      errors += diagnostics.length
      console.log(`SCRIPT ERROR ${display}`)
      diagnostics.forEach((item) => {
        console.log('  ', ts.flattenDiagnosticMessageText(item.messageText, '\n'))
      })
    }
  }

  for (const style of descriptor.styles) {
    if (style.lang && style.lang !== 'scss') continue
    const scss = `@import "styles/tokens.scss";\n@import "styles/mixins.scss";\n${style.content}`
    try {
      sass.compileString(scss, {
        loadPaths: [root],
        quietDeps: true,
        silenceDeprecations: ['import', 'global-builtin'],
      })
    } catch (error) {
      errors += 1
      console.log(`STYLE ERROR ${display}`)
      console.log('  ', error.message?.split('\n').slice(0, 4).join('\n   '))
    }
  }
}

console.log(`\n[check-uvue] ${files.length} files, ${errors} error(s)`)
process.exit(errors > 0 ? 1 : 0)
