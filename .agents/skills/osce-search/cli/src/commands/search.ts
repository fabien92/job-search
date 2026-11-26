import { BASE, MAX_PAGES, PAGE_SIZE, htmlFetch, parseSearchPage, politeDelay, searchId, stripInvisible, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  page?: number // undefined = the whole board (about 5 pages)
  limit?: number
  format: "json" | "table" | "plain"
}

const LOCATION_ALIASES: Record<string, string> = { wien: "Vienna", vienne: "Vienna", varsovie: "Warsaw", warschau: "Warsaw" }

export function locationName(location: string | undefined): string {
  return location ? (LOCATION_ALIASES[location.trim().toLowerCase()] ?? location.trim()) : ""
}

/** Client-side keyword filter: every word must appear in the title, snippet, location or category. */
export function matchesQuery(card: JobCard, query: string | undefined): boolean {
  const words = (query ?? "").toLowerCase().replace(/["']/g, " ").split(/\s+/).filter(Boolean)
  if (words.length === 0) return true
  const hay = [card.title, card.summary, card.location, card.category].join(" ").toLowerCase()
  return words.every((w) => hay.includes(w))
}

/** Comma-separated duty stations ("Vienna,Bratislava"): a row matches if it names any of them. */
export function matchesLocation(card: JobCard, location: string | undefined): boolean {
  const wanted = (location ?? "").split(",").map((l) => locationName(l).toLowerCase()).filter(Boolean)
  if (wanted.length === 0) return true
  const where = (card.location ?? "").toLowerCase()
  return wanted.some((w) => where.includes(w))
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(6) + " " + "TITLE".padEnd(60) + " LOCATION"
  const rows = cards.map((c) => [c.id.padEnd(6), c.title.slice(0, 60).padEnd(60), c.location || "—"].join(" "))
  return [header, "-".repeat(header.length + 30), ...rows].join("\n")
}

/** Fetch the requested page(s). The first request lands on a fresh saved search /jobs/search/<jsid>. */
async function fetchCards(page: number | undefined): Promise<{ cards: JobCard[]; total: number | null } | null> {
  const first = await htmlFetch(`${BASE}/jobs/search/`)
  if (!first) return null
  const p1 = parseSearchPage(first.html)
  const jsid = searchId(first.url)
  const pages = p1.total !== null ? Math.min(MAX_PAGES, Math.max(1, Math.ceil(p1.total / PAGE_SIZE))) : 1
  const wanted = page === undefined ? Array.from({ length: pages - 1 }, (_, i) => i + 2) : page > 1 ? [page] : []
  if (wanted.length && !jsid) throw new Error(`search did not land on a saved search (/jobs/search/<id>): ${first.url}`)
  const cards = page === undefined || page === 1 ? [...p1.cards] : []
  for (const n of wanted) {
    if (n > pages) break
    await politeDelay()
    const next = await htmlFetch(`${BASE}/jobs/search/${jsid}/page${n}`)
    if (!next) break
    const parsed = parseSearchPage(next.html)
    if (parsed.currentPage !== null && parsed.currentPage !== n) break // the site fell back to another page
    cards.push(...parsed.cards)
  }
  const seen = new Set<string>()
  return { cards: cards.filter((c) => !seen.has(c.id) && seen.add(c.id)), total: p1.total }
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const fetched = await fetchCards(opts.page)
    if (!fetched) {
      writeError("search page returned 404", "NOT_FOUND")
      return 1
    }
    const filtered = opts.query !== undefined || opts.location !== undefined
    let cards = stripInvisible(fetched.cards).filter((c) => matchesLocation(c, opts.location) && matchesQuery(c, opts.query))
    const total = filtered ? (opts.page === undefined ? cards.length : null) : fetched.total
    const page = opts.page ?? 1
    const hasMore = opts.page !== undefined && fetched.total !== null ? page * PAGE_SIZE < fetched.total : false
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)
    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(cards.map((c) => `${c.title}\n  OSCE · ${c.location || "—"}\n  id: ${c.id}\n  ${c.url}`).join("\n\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify({ meta: { count: cards.length, page, total, hasMore }, results: cards }, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
