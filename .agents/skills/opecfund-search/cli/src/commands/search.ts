import { BASE, COMPANY, ageInDays, htmlFetch, parseSearchPage, stripInvisible, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  jobage?: number
  limit?: number
  format: "json" | "table" | "plain"
}

const LOCATION_ALIASES: Record<string, string> = { wien: "Vienna", vienne: "Vienna", "österreich": "Austria", autriche: "Austria" }

export function locationName(location: string): string {
  return LOCATION_ALIASES[location.trim().toLowerCase()] ?? location.trim()
}

/** Comma-separated locations ("Vienna,Bratislava"): a row matches if it names any of them. */
export function matchesLocation(card: JobCard, location: string | undefined): boolean {
  const wanted = (location ?? "").split(",").map((l) => locationName(l).toLowerCase()).filter(Boolean)
  if (wanted.length === 0) return true
  const where = (card.location ?? "").toLowerCase()
  return wanted.some((w) => where.includes(w))
}

/** Client-side keyword filter: every word must appear in the title. */
export function matchesQuery(card: JobCard, query: string | undefined): boolean {
  const words = (query ?? "").toLowerCase().replace(/["']/g, " ").split(/\s+/).filter(Boolean)
  const title = card.title.toLowerCase()
  return words.every((w) => title.includes(w))
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(11) + " " + "TITLE".padEnd(55) + " " + "LOCATION".padEnd(16) + " POSTED"
  const rows = cards.map((c) => [c.id.padEnd(11), c.title.slice(0, 55).padEnd(55), (c.location || "—").slice(0, 16).padEnd(16), c.date || "—"].join(" "))
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    // The board is tiny: always fetch all of it and filter here (the site's q/locationsearch are loose).
    const html = await htmlFetch(`${BASE}/search/?q=&locationsearch=`)
    if (!html) {
      writeError("search page returned 404 or an error page", "NOT_FOUND")
      return 1
    }
    const page = parseSearchPage(html)
    let cards = stripInvisible(page.cards).filter((c) => matchesLocation(c, opts.location) && matchesQuery(c, opts.query))
    if (opts.jobage !== undefined) {
      cards = cards.filter((c) => {
        const age = ageInDays(c.date)
        return age === null || age <= opts.jobage!
      })
    }
    const filtered = opts.query !== undefined || opts.location !== undefined || opts.jobage !== undefined
    const total = filtered ? cards.length : page.total
    if (opts.limit !== undefined) cards = cards.slice(0, opts.limit)
    const hasMore = page.total !== null ? page.total > page.cards.length : null
    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(cards.map((c) => `${c.title}\n  ${COMPANY} · ${c.location || "—"} · posted ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}`).join("\n\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify({ meta: { count: cards.length, page: 1, total, hasMore }, results: cards }, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
