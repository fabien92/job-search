import { MAX_PAGES, PAGE_SIZE, ageInDays, htmlFetch, parseSearchPage, politeDelay, searchUrl, stripInvisible, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  jobage?: number
  page?: number // undefined = every page (up to MAX_PAGES)
  limit?: number
  format: "json" | "table" | "plain"
}

/** Spellings of one place as Hays prints them ("Vienna", "Wien", "Wien und remote", "Himberg bei Wien"). */
const ALIASES: string[][] = [
  ["vienna", "wien", "vienne"],
  ["carinthia", "kärnten", "klagenfurt"],
  ["styria", "steiermark", "graz"],
  ["upper austria", "oberösterreich", "linz"],
  ["lower austria", "niederösterreich"],
  ["tyrol", "tirol", "innsbruck"],
]

function spellings(place: string): string[] {
  const p = place.trim().toLowerCase()
  return ALIASES.find((group) => group.includes(p)) ?? [p]
}

/** Comma-separated places ("Vienna,Graz"): a row matches if its location names any spelling of any. */
export function matchesLocation(card: JobCard, location: string | undefined): boolean {
  const wanted = (location ?? "").split(",").filter((l) => l.trim()).flatMap(spellings)
  if (wanted.length === 0) return true
  const where = (card.location ?? "").toLowerCase()
  return wanted.some((w) => where.includes(w))
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(9) + " " + "DATE".padEnd(10) + " " + "TITLE".padEnd(60) + " LOCATION"
  const rows = cards.map((c) => [c.id.padEnd(9), (c.date ?? "—").padEnd(10), c.title.slice(0, 60).padEnd(60), c.location || "—"].join(" "))
  return [header, "-".repeat(header.length + 25), ...rows].join("\n")
}

const tooOld = (c: JobCard, jobage: number | undefined) => jobage !== undefined && (ageInDays(c.date) ?? 0) > jobage

/**
 * Walk the requested page(s). The order is roughly newest first but not strictly (page 1 mixes
 * openings from this week with year-old ones), so --jobage never stops the walk early.
 */
async function fetchCards(opts: SearchOpts): Promise<{ cards: JobCard[]; total: number | null } | null> {
  const first = opts.page ?? 1
  const out: JobCard[] = []
  let total: number | null = null
  for (let n = first; n < first + (opts.page === undefined ? MAX_PAGES : 1); n++) {
    if (n > first) await politeDelay()
    const res = await htmlFetch(searchUrl(n, opts.query))
    if (!res) return n === first ? null : { cards: out, total }
    const parsed = parseSearchPage(res.html)
    if (total === null) total = parsed.total
    out.push(...parsed.cards)
    if (parsed.cards.length === 0) break
    if (total !== null && n * PAGE_SIZE >= total) break
  }
  const seen = new Set<string>()
  return { cards: out.filter((c) => !seen.has(c.id) && seen.add(c.id)), total }
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const fetched = await fetchCards(opts)
    if (!fetched) {
      writeError("search page returned 404", "NOT_FOUND")
      return 1
    }
    let cards = stripInvisible(fetched.cards).filter((c) => matchesLocation(c, opts.location) && !tooOld(c, opts.jobage))
    const filtered = opts.location !== undefined || opts.jobage !== undefined
    const total = filtered ? (opts.page === undefined ? cards.length : null) : fetched.total
    const page = opts.page ?? 1
    const hasMore = opts.page !== undefined && fetched.total !== null ? page * PAGE_SIZE < fetched.total : false
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)
    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards.map((c) => `${c.title}\n  via Hays · ${c.location || "—"} · ${c.date ?? "—"}\n  ${c.employmentType ?? ""}\n  id: ${c.id}\n  ${c.url}`).join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(JSON.stringify({ meta: { count: cards.length, page, total, hasMore }, results: cards }, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
