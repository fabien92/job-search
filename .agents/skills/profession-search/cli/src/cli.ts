#!/usr/bin/env bun
// Self-contained CLI for Profession.hu job offers (Hungary). No external CLI framework and zero
// runtime dependencies: it runs anywhere `bun` is available. Search reads the board's official
// RSS feed of one category (20 newest openings); no keyword search. Keep volume low.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { CATEGORIES } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { l: "location", n: "limit", c: "category" }
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

const HELP = `profession-cli — list job offers from Profession.hu (Hungary) through its RSS feeds

USAGE
  bun run src/cli.ts search [-l "<place>"] [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --category, -c <name>   Feed category (default: it). One of:
                          ${CATEGORIES.join(", ")}.
  --location, -l <text>   Hungarian town(s), comma-separated ("Budapest", "Budapest,Érd"). Cards
                          whose link names another town are dropped; cards whose link names none
                          are placed by reading their posting (see --lookups). Without it, the
                          whole feed (all of Hungary).
  --lookups <n>           At most n postings read to place such cards (default 10); the rest are
                          dropped and counted in meta.unresolved.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.
  One feed request (20 newest openings, no posting date: use detail). Requests are 2 s apart
  (PROFESSION_CLI_DELAY_MS). No keyword search.

EXAMPLES
  bun run src/cli.ts search -l Budapest --format table
  bun run src/cli.ts detail 3058862 --format plain
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["location", "category", "lookups", "limit", "format", "help", "h"]),
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
    const category = flags.category === undefined ? "it" : String(flags.category)
    if (!(CATEGORIES as readonly string[]).includes(category)) {
      return fail(`--category must be one of ${CATEGORIES.join("|")}, got "${category}"`, "BAD_ARG")
    }

    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) return fail(`--format must be one of json|table|plain, got "${fmt}"`, "BAD_ARG")

    const ints: Record<string, number | undefined> = {}
    for (const name of ["lookups", "limit"]) {
      const raw = flags[name]
      if (raw === undefined) continue
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      if (!Number.isInteger(val) || val < 0) return fail(`--${name} must be a whole number of at least 0, got "${raw}"`, "BAD_ARG")
      ints[name] = val
    }

    const opts: SearchOpts = {
      location,
      category,
      limit: ints.limit,
      lookups: ints.lookups ?? 10,
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
