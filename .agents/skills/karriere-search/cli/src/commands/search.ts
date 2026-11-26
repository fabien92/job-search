import {
  SEARCH_URL,
  ageInDays,
  jsonFetch,
  parseSearchPayload,
  stripInvisible,
  viennaToday,
  writeError,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  jobage?: number // client-side: the portal has no age parameter
  sort: "date" | "relevance"
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

export function buildUrl(opts: SearchOpts): string {
  const params = new URLSearchParams()
  if (opts.query) params.set("keywords", opts.query)
  if (opts.location) params.set("locations", opts.location)
  if (opts.sort === "date") params.set("sort", "date")
  if (opts.page > 1) params.set("page", String(opts.page))
  const qs = params.toString()
  return qs ? `${SEARCH_URL}?${qs}` : SEARCH_URL
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(9) + " " + "TITLE".padEnd(42) + " " + "COMPANY".padEnd(26) + " " + "LOCATION".padEnd(18) + " DATE"
  const rows = cards.map((c) => {
    const title = (c.title || "").slice(0, 42).padEnd(42)
    const company = (c.company || "—").slice(0, 26).padEnd(26)
    const loc = (c.location || "—").slice(0, 18).padEnd(18)
    return `${c.id.padEnd(9)} ${title} ${company} ${loc} ${c.date || "—"}${c.pushed ? " (pushed)" : ""}`
  })
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts, today: string = viennaToday()): Promise<number> {
  try {
    const payload = await jsonFetch(buildUrl(opts))
    if (payload === null) {
      writeError("search endpoint returned 404", "NOT_FOUND")
      return 1
    }
    const page = parseSearchPayload(payload, today)
    let cards = stripInvisible(page.cards)
    if (opts.jobage !== undefined) {
      // Unknown dates are kept: dropping them would hide postings on a markup change.
      cards = cards.filter((c) => {
        const age = ageInDays(c.date, today)
        return age === null || age <= opts.jobage!
      })
    }
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map((c) => `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}`)
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify(
          { meta: { count: cards.length, page: opts.page, total: page.total, hasMore: page.hasMore }, results: cards },
          null,
          2,
        ) + "\n",
      )
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
