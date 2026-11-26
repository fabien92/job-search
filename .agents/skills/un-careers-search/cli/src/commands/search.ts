import { API, ageInDays, apiFetch, locationCode, parseSearchData, stripInvisible, viennaToday, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  jobage?: number
  page: number // 1-indexed (the API is 0-indexed)
  limit?: number
  format: "json" | "table" | "plain"
}

export const PER_PAGE = 100

/** The portal's "Date Posted" filter only knows 1, 7 and 30 days: the smallest that covers jobage. */
export function spanFor(jobage: number | undefined): string | null {
  if (jobage === undefined) return null
  for (const s of [1, 7, 30]) if (jobage <= s) return String(s)
  return null
}

export function buildBody(opts: SearchOpts): Record<string, unknown> {
  const filterConfig: Record<string, unknown> = {}
  if (opts.query) filterConfig.keyword = opts.query.trim()
  if (opts.location) filterConfig.ds = [locationCode(opts.location)]
  const span = spanFor(opts.jobage)
  if (span) filterConfig.span = [span]
  return { filterConfig, pagination: { page: opts.page - 1, itemPerPage: PER_PAGE, sortBy: "startDate", sortDirection: -1 } }
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(7) + " " + "TITLE".padEnd(46) + " " + "GRADE".padEnd(6) + " " + "ENTITY".padEnd(30) + " " + "LOCATION".padEnd(12) + " DATE       DEADLINE"
  const rows = cards.map((c) => {
    const entity = (c.company || "—").replace(/^United Nations – /, "")
    return [
      c.id.padEnd(7),
      c.title.slice(0, 46).padEnd(46),
      (c.grade || "—").slice(0, 6).padEnd(6),
      entity.slice(0, 30).padEnd(30),
      (c.location || "—").slice(0, 12).padEnd(12),
      (c.date || "—").padEnd(10),
      c.deadline || "—",
    ].join(" ")
  })
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts, today: string = viennaToday()): Promise<number> {
  try {
    const data = await apiFetch(`${API}/jo/list/filteredV2/en`, buildBody(opts))
    if (!data) {
      writeError("search endpoint returned 404 (API moved?)", "NOT_FOUND")
      return 1
    }
    const page = parseSearchData(data)
    let cards = stripInvisible(page.cards)
    if (opts.location) {
      // Belt and braces: keep only the requested duty station even if the API ignored the filter.
      const want = locationCode(opts.location)
      cards = cards.filter((c) => !c.location || c.location.split(", ").some((s) => locationCode(s) === want))
    }
    if (opts.jobage !== undefined) {
      cards = cards.filter((c) => {
        const age = ageInDays(c.date, today)
        return age === null || age <= opts.jobage!
      })
    }
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)
    const hasMore = page.total !== null ? opts.page * PER_PAGE < page.total : null

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map((c) => `${c.title}${c.grade ? ` (${c.grade})` : ""}\n  ${c.company || "—"} · ${c.location || "—"} · posted ${c.date || "—"} · closes ${c.deadline || "—"}\n  id: ${c.id}\n  ${c.url}`)
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify({ meta: { count: cards.length, page: opts.page, total: page.total, hasMore }, results: cards }, null, 2) + "\n",
      )
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
