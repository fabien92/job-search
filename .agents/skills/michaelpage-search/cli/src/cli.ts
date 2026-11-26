#!/usr/bin/env bun
// Self-contained CLI for Michael Page Austria job offers on www.michaelpage.at. No external CLI
// framework and zero runtime dependencies: it runs anywhere `bun` is available. No keyword search
// (robots.txt disallows /search/): it walks the public IT listings. Keep volume low.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { l: "location", n: "limit", q: "query" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith("-")) {
      const key = alias[a.replace(/^-+/, "")] ?? a.replace(/^-+/, "")
      const next = argv[i + 1]
      if (next === undefined || next.startsWith("-")) {
        flags[key] = true
      } else {
        flags[key] = next
        i++
      }
    } else {
      ;(flags._ as string[]).push(a)
    }
  }
  return flags
}

const HELP = `michaelpage-cli — list Michael Page Austria IT job offers on www.michaelpage.at

USAGE
  bun run src/cli.ts search [-l "<place>"] [flags]
  bun run src/cli.ts detail <url> [--format json|plain]

SEARCH FLAGS
  --location, -l <text>   Wien (Vienna, Vienne; default) or Österreich (Austria); comma-separated
                          walks each IT listing once. Any other place is refused.
  --query, -q <words>     Keep titles containing every word (client-side: robots.txt disallows
                          the site's /search/).
  --page <n>              One page of 30 (1-indexed). Default: every page (at most 10).
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.
  No --jobage: the list shows no date (detail has it). Requests are 3 s apart
  (MICHAELPAGE_CLI_DELAY_MS).

DETAIL
  <url> is the posting URL from search (/job-detail/<slug>/ref/<ref>): a bare ref is not enough.

EXAMPLES
  bun run src/cli.ts search -l Wien --format table
  bun run src/cli.ts search -q manager --format plain
  bun run src/cli.ts detail https://www.michaelpage.at/job-detail/project-service-delivery-manager-wmd/ref/jn-112026-7140475
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["location", "query", "page", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

function fail(error: string, code: string): number {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
  return 1
}

async function main(): Promise<number> {
  const flags = parseFlags(process.argv.slice(2))
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      return fail(
        `unknown flag --${key} for '${cmd}' - flags are never silently ignored, because a discarded filter changes what the search returns; see --help`,
        "UNKNOWN_FLAG",
      )
    }
  }

  if (cmd === "search") {
    const text: Record<string, string | undefined> = {}
    for (const name of ["location", "query"]) {
      const raw = flags[name]
      if (raw === undefined) continue
      if (typeof raw !== "string" || !raw.trim()) return fail(`--${name} requires a non-empty value`, "BAD_ARG")
      text[name] = raw.trim()
    }
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) return fail(`--format must be one of json|table|plain, got "${fmt}"`, "BAD_ARG")
    const ints: Record<string, number | undefined> = {}
    for (const name of ["page", "limit"]) {
      const raw = flags[name]
      if (raw === undefined) continue
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      const min = name === "page" ? 1 : 0
      if (!Number.isInteger(val) || val < min) {
        return fail(`--${name} must be a whole number of at least ${min}, got "${raw}"`, "BAD_ARG")
      }
      ints[name] = val
    }
    const opts: SearchOpts = { location: text.location, query: text.query, page: ints.page, limit: ints.limit, format: fmt as SearchOpts["format"] }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) return fail("detail requires a posting <url>", "NO_ID")
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "plain"].includes(fmt)) return fail(`--format must be one of json|plain, got "${fmt}"`, "BAD_ARG")
    const opts: DetailOpts = { id, format: fmt as DetailOpts["format"] }
    return runDetail(opts)
  }

  return fail(`Unknown command "${cmd}"`, "BAD_CMD")
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    process.stderr.write(JSON.stringify({ error: e instanceof Error ? e.message : String(e), code: "INTERNAL_ERROR" }) + "\n")
    process.exit(1)
  })
