import { BASE, htmlFetch, parseSearchPage, stripInvisible, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  page: number // only 1: the whole board (~20 openings) fits on one page
  limit?: number
  format: "json" | "table" | "plain"
}

const LOCATION_ALIASES: Record<string, string> = { wien: "Vienna", vienne: "Vienna" }

export function locationName(location: string | undefined): string {
  return location ? (LOCATION_ALIASES[location.trim().toLowerCase()] ?? location.trim()) : ""
}

export function buildUrl(opts: SearchOpts): string {
  const loc = locationName(opts.location)
  const p = new URLSearchParams({ q: opts.query?.trim() ?? "", locationsearch: loc })
  return `${BASE}/search/?${p.toString()}`
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(11) + " " + "TITLE".padEnd(50) + " " + "GRADE".padEnd(6) + " " + "CATEGORY".padEnd(20) + " " + "LOCATION".padEnd(22) + " DEADLINE"
  const rows = cards.map((c) =>
    [c.id.padEnd(11), c.title.slice(0, 50).padEnd(50), (c.grade || "—").slice(0, 6).padEnd(6),
     (c.category || "—").slice(0, 20).padEnd(20), (c.location || "—").slice(0, 22).padEnd(22), c.deadline || "—"].join(" "))
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const html = await htmlFetch(buildUrl(opts))
    if (!html) {
      writeError("search page returned 404 or an error page", "NOT_FOUND")
      return 1
    }
    const page = parseSearchPage(html)
    let cards = stripInvisible(page.cards)
    if (opts.location) {
      // A location that matches nothing makes the site return every opening: keep only real matches.
      const want = locationName(opts.location).toLowerCase()
      cards = cards.filter((c) => (c.location ?? "").toLowerCase().includes(want))
    }
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)
    const hasMore = page.total !== null ? page.total > page.cards.length : null
    const total = opts.location && cards.length < page.cards.length ? cards.length : page.total
    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards.map((c) => `${c.title}${c.grade ? ` (${c.grade})` : ""}\n  UNIDO · ${c.location || "—"} · closes ${c.deadline || "—"}\n  id: ${c.id}\n  ${c.url}`).join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(JSON.stringify({ meta: { count: cards.length, page: 1, total, hasMore }, results: cards }, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
