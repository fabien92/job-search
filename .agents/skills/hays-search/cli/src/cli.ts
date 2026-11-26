#!/usr/bin/env bun
// Self-contained CLI for Hays Austria job offers on www.hays.at. No external CLI framework and
// zero runtime dependencies: it runs anywhere `bun` is available. robots.txt asks Crawl-delay
// 10: the CLI waits 10 s between its own requests. Keep volume low.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit" }
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

const HELP = `hays-cli — search Hays Austria job offers on www.hays.at (openings in Austria)

USAGE
  bun run src/cli.ts search [-q "<keywords>"] [-l "<place>"] [flags]
  bun run src/cli.ts detail <ref|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords, sent to Hays (all words must match). Double quotes inside
                          the argument make an exact phrase, word order included; no OR.
  --location, -l <text>   Place, e.g. "Vienna" (or "Wien"); several comma-separated
                          ("Vienna,Graz") match any. Filtered client-side on the card location.
  --jobage <days>         Only openings online for at most this many days (client-side filter
                          on "Online since"; every page is still read).
  --page <n>              One page of 20 (1-indexed). Default: every page (at most 6).
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.
  Requests are 10 s apart (robots.txt Crawl-delay): a full walk of Austria (~4 pages) takes ~30 s.

EXAMPLES
  bun run src/cli.ts search -l Vienna --jobage 14 --format table
  bun run src/cli.ts search -q "project manager" -l Wien
  bun run src/cli.ts detail 903672-1 --format plain
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["query", "location", "jobage", "page", "limit", "format", "help", "h"]),
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
    for (const name of ["query", "location"]) {
      if (flags[name] !== undefined && (typeof flags[name] !== "string" || !(flags[name] as string).trim())) {
        return fail(`--${name} requires a non-empty value`, "BAD_ARG")
      }
    }
    const query = typeof flags.query === "string" ? flags.query.trim() : undefined
    if (query && query.length > 100) return fail("--query is limited to 100 characters (the portal's own limit)", "BAD_ARG")
    const location = typeof flags.location === "string" ? flags.location.trim() : undefined

    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) return fail(`--format must be one of json|table|plain, got "${fmt}"`, "BAD_ARG")

    const ints: Record<string, number | undefined> = {}
    for (const name of ["jobage", "page", "limit"]) {
      const raw = flags[name]
      if (raw === undefined) continue
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      const min = name === "page" ? 1 : 0
      if (!Number.isInteger(val) || val < min) {
        return fail(`--${name} must be a whole number of at least ${min}, got "${raw}"`, "BAD_ARG")
      }
      ints[name] = val
    }

    const opts: SearchOpts = {
      query,
      location,
      jobage: ints.jobage,
      page: ints.page,
      limit: ints.limit,
      format: fmt as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) return fail("detail requires a <ref|url>", "NO_ID")
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
