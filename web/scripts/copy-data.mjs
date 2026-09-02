// Copies the scraper's export (../data/latest.json) into public/data/ so Vite serves it
// at <base>/data/latest.json in dev and bundles it into dist/ on build.
// Wired as the "predev" and "prebuild" npm scripts. public/data/ is gitignored.
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '..', '..', 'data', 'latest.json')
const dstDir = resolve(here, '..', 'public', 'data')
const dst = resolve(dstDir, 'latest.json')

if (!existsSync(src)) {
  console.error(`[copy-data] ${src} not found.`)
  console.error('[copy-data] Run the scraper first (from the repo root): ./.venv/bin/python scraper/run.py')
  process.exit(1)
}

mkdirSync(dstDir, { recursive: true })
copyFileSync(src, dst)
const kb = (statSync(dst).size / 1024).toFixed(1)
console.log(`[copy-data] ${src} -> ${dst} (${kb} kB)`)
