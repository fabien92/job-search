#!/usr/bin/env bun
// Self-contained CLI for Jobgether remote job offers, through the public JSON API Jobgether
// publishes for AI agents (/astroapi/ai/jobs.json). No external CLI framework and zero runtime
// dependencies: it runs anywhere `bun` is available. Never fetches the offer pages.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

const BOOLEAN_FLAGS = new Set(["strict", "help", "h"])

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith("-")) {
      const key = alias[a.replace(/^-+/, "")] ?? a.replace(/^-+/, "")
      const next = argv[i + 1]
      if (BOOLEAN_FLAGS.has(key) || next === undefined || next.startsWith("-")) {
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

const HELP = `jobgether-cli — search Jobgether remote job offers (public API for AI agents)

USAGE
  bun run src/cli.ts search [-q "<keywords>"] [-l <slug,...>] [flags]
  bun run src/cli.ts detail <offer-url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (title, job function, skills, company). Every word must
                          match; quotes and word order change nothing; no OR.
  --location, -l <slugs>  Jobgether location slugs, comma-separated: country, continent or city
                          (austria, vienna, europe, anywhere…). An unknown slug is refused.
                          Offers are remote: the API keeps those open to candidates there.
  --strict                Keep only offers whose eligibility names Europe / EU / EMEA / DACH or
                          the searched place; drops "Anywhere"-only offers (mostly US employers).
  --jobage <days>         Only offers posted at most this many days ago (client-side; with
                          --sort date the walk stops at the first older page).
  --sort <date|relevance> Default: date (newest first).
  --page <n>              One page of 25 (1-indexed, at most 10). Default: walk up to 10 pages.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

EXAMPLES
  bun run src/cli.ts search -q "delivery manager" -l austria --strict --format table
  bun run src/cli.ts search -q "project manager" -l austria --strict --jobage 7
  bun run src/cli.ts detail https://jobgether.com/offer/6ad67e28a8fae18ba2cdd2c0-delivery-manager
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["query", "location", "strict", "jobage", "sort", "page", "limit", "format", "help", "h"]),
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
    for (const name of ["query", "location", "sort"]) {
      if (flags[name] !== undefined && (typeof flags[name] !== "string" || !(flags[name] as string).trim())) {
        return fail(`--${name} requires a non-empty value`, "BAD_ARG")
      }
    }
    const query = typeof flags.query === "string" ? flags.query.trim() : undefined
    if (query && query.length > 100) return fail("--query is limited to 100 characters", "BAD_ARG")
    const locations = typeof flags.location === "string"
      ? flags.location.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean)
      : []
    for (const slug of locations) {
      if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) return fail(`--location takes slugs like austria or vienna, got "${slug}"`, "BAD_ARG")
    }
    const sort = typeof flags.sort === "string" ? flags.sort.trim() : "date"
    if (!["date", "relevance"].includes(sort)) return fail(`--sort must be date or relevance, got "${sort}"`, "BAD_ARG")

    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) return fail(`--format must be one of json|table|plain, got "${fmt}"`, "BAD_ARG")

    const ints: Record<string, number | undefined> = {}
    for (const name of ["jobage", "page", "limit"]) {
      const raw = flags[name]
      if (raw === undefined) continue
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      const min = name === "page" ? 1 : 0
      if (!Number.isInteger(val) || val < min || (name === "page" && val > 10)) {
        return fail(`--${name} must be a whole number of at least ${min}${name === "page" ? " and at most 10" : ""}, got "${raw}"`, "BAD_ARG")
      }
      ints[name] = val
    }

    const opts: SearchOpts = {
      query,
      locations,
      jobage: ints.jobage,
      page: ints.page,
      limit: ints.limit,
      sort: sort as SearchOpts["sort"],
      strict: flags.strict === true,
      format: fmt as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) return fail("detail requires an <offer-url>", "NO_ID")
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
