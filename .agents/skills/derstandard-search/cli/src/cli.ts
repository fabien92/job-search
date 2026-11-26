#!/usr/bin/env bun
// Self-contained CLI for searching jobs on jobs.derstandard.at (DER STANDARD Jobs, Austria). No external
// CLI framework and zero runtime dependencies: it runs anywhere `bun` is
// available. Keep volume low: a handful of requests per run.

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

const HELP = `derstandard-cli — search jobs on jobs.derstandard.at (Austria)

USAGE
  bun run src/cli.ts search [-q "<keywords>"] [-l "<location>"] [flags]
  bun run src/cli.ts detail <uuid|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill). e.g. "Delivery Manager".
  --location, -l <text>   Austrian location (city or Bundesland), e.g. "Wien", "Graz".
                          Default: all of Austria.
  --jobage <days>         Keep postings published within N days (client-side filter;
                          the portal has no public age parameter). Unknown dates are kept.
  --page <n>              Only 1 is supported: the portal serves page 1 only (20 results,
                          relevance order); the rest is loaded client-side.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.
  At least one of --query / --location is required.

EXAMPLES
  bun run src/cli.ts search -q "Delivery Manager" -l "Wien" --format table
  bun run src/cli.ts search -q "IT Projektmanager" -l "Wien" --jobage 2
  bun run src/cli.ts detail 417ad32a-0b7b-3f3c-87a9-2404ca45b101 --format plain
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
    const location = typeof flags.location === "string" ? flags.location.trim() : undefined
    if (!query && !location) return fail("search needs --query and/or --location", "NO_QUERY")

    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) return fail(`--format must be one of json|table|plain, got "${fmt}"`, "BAD_ARG")

    const ints: Record<string, number | undefined> = {}
    for (const name of ["jobage", "page", "limit"]) {
      const raw = flags[name]
      if (raw === undefined) continue
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      const min = name === "limit" ? 0 : 1
      if (!Number.isInteger(val) || val < min) {
        return fail(`--${name} must be a whole number of at least ${min}, got "${raw}"`, "BAD_ARG")
      }
      ints[name] = val
    }

    if ((ints.page ?? 1) > 1) {
      return fail("--page above 1 is not available: jobs.derstandard.at serves only the first 20 results as HTML", "PAGE_UNSUPPORTED")
    }

    const opts: SearchOpts = {
      query,
      location,
      jobage: ints.jobage,
      page: 1,
      limit: ints.limit,
      format: fmt as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) return fail("detail requires a <uuid|url>", "NO_ID")
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
