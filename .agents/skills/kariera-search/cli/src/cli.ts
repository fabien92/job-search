#!/usr/bin/env bun
// Self-contained CLI for Kariéra.sk job offers (Slovakia). No external CLI framework and zero
// runtime dependencies: it runs anywhere `bun` is available. Search walks the public category
// listings of one region (30 cards per page, newest first); no portal keyword search (robots.txt
// disallows ?q=): --query filters titles client-side. Keep volume low.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { CATEGORIES, DEFAULT_CATEGORIES } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { l: "location", n: "limit", c: "category", q: "query" }
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

const HELP = `kariera-cli — list job offers from Kariéra.sk (kariera.zoznam.sk, Slovakia)

USAGE
  bun run src/cli.ts search -l "<place>" [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --location, -l <text>   Slovak region town(s), comma-separated (required): Bratislava, Trnava,
                          Nitra, Trenčín, Žilina, Banská Bystrica, Prešov, Košice (or the region,
                          "Bratislavský kraj"). The whole region's listing is read (Senec,
                          Pezinok… included).
  --category, -c <list>   Listing categories, comma-separated (default:
                          ${DEFAULT_CATEGORIES.join(",")}). One of:
                          ${CATEGORIES.join(", ")}.
  --query, -q <words>     Client-side filter: every word in the title (accents/case ignored). The
                          portal's own keyword search is disallowed by robots.txt and never used.
  --jobage <days>         Keep cards dated within n days, and walk the next pages while a page is
                          entirely that fresh (see --max-pages).
  --page <n>              First listing page (1-indexed, 30 cards each; default 1).
  --max-pages <n>         Pages per category at most with --jobage (default 3).
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.
  One request per page and category, 2 s apart (KARIERA_CLI_DELAY_MS). Offers listed in several
  categories are merged.

EXAMPLES
  bun run src/cli.ts search -l Bratislava --jobage 2 --format table
  bun run src/cli.ts search -l Bratislava -q "project manager" --format table
  bun run src/cli.ts detail 1559635 --format plain
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["location", "category", "query", "jobage", "page", "max-pages", "limit", "format", "help", "h"]),
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
    for (const name of ["location", "category", "query"]) {
      if (flags[name] !== undefined && (typeof flags[name] !== "string" || !(flags[name] as string).trim())) {
        return fail(`--${name} requires a non-empty value`, "BAD_ARG")
      }
    }
    if (typeof flags.location !== "string") return fail("--location is required (e.g. -l Bratislava)", "BAD_ARG")
    const categories = typeof flags.category === "string"
      ? [...new Set(flags.category.split(",").map((c) => c.trim()).filter(Boolean))]
      : DEFAULT_CATEGORIES
    for (const c of categories) {
      if (!(CATEGORIES as readonly string[]).includes(c)) return fail(`--category must be among ${CATEGORIES.join("|")}, got "${c}"`, "BAD_ARG")
    }

    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) return fail(`--format must be one of json|table|plain, got "${fmt}"`, "BAD_ARG")

    const ints: Record<string, number | undefined> = {}
    for (const [name, min] of [["jobage", 0], ["page", 1], ["max-pages", 1], ["limit", 0]] as const) {
      const raw = flags[name]
      if (raw === undefined) continue
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      if (!Number.isInteger(val) || val < min) return fail(`--${name} must be a whole number of at least ${min}, got "${raw}"`, "BAD_ARG")
      ints[name] = val
    }

    const opts: SearchOpts = {
      location: flags.location.trim(),
      categories,
      query: typeof flags.query === "string" ? flags.query.trim() : undefined,
      jobage: ints.jobage,
      page: ints.page ?? 1,
      maxPages: ints["max-pages"] ?? 3,
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
