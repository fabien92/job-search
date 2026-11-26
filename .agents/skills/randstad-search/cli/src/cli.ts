#!/usr/bin/env bun
// Self-contained CLI for Randstad Austria job offers on www.randstad.at. No external CLI framework
// and zero runtime dependencies: it runs anywhere `bun` is available. No keyword search (robots.txt
// disallows the search parameters): it walks the public city listings. Keep volume low.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { l: "location", n: "limit", s: "specialism" }
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

const HELP = `randstad-cli — list Randstad Austria job offers on www.randstad.at (openings in Austria)

USAGE
  bun run src/cli.ts search [-l "<place>"] [-s <berufsfeld>] [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --location, -l <text>   Place: Wien (Vienna, Vienne), Graz, Linz or Salzburg; several
                          comma-separated ("Wien,Graz") walk each listing. Without it, the whole
                          of Austria (~18 pages). No keyword search: robots.txt disallows it.
  --specialism, -s <slug> Only one Berufsfeld's listing, e.g. edv-it (IT: /jobs/s-edv-it/wien/wien/);
                          slugs as in the sitemaps (sitemap-joblistings-<slug>.xml).
  --jobage <days>         Only openings published at most this many days ago (client-side
                          filter on "veröffentlicht am"; every page is still read).
  --page <n>              One page of 30 (1-indexed). Default: every page (at most 25).
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.
  Requests are 2 s apart (RANDSTAD_CLI_DELAY_MS).

EXAMPLES
  bun run src/cli.ts search -l Wien --jobage 14 --format table
  bun run src/cli.ts search -l Wien -s edv-it --format plain
  bun run src/cli.ts detail 47720442 --format plain
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["location", "specialism", "jobage", "page", "limit", "format", "help", "h"]),
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
    if (flags.location !== undefined && (typeof flags.location !== "string" || !flags.location.trim())) {
      return fail("--location requires a non-empty value", "BAD_ARG")
    }
    const location = typeof flags.location === "string" ? flags.location.trim() : undefined
    if (flags.specialism !== undefined && (typeof flags.specialism !== "string" || !flags.specialism.trim())) {
      return fail("--specialism requires a non-empty value", "BAD_ARG")
    }
    const specialism = typeof flags.specialism === "string" ? flags.specialism.trim() : undefined

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
      location,
      specialism,
      jobage: ints.jobage,
      page: ints.page,
      limit: ints.limit,
      format: fmt as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) return fail("detail requires an <id|url>", "NO_ID")
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
