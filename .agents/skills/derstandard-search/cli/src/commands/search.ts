import {
  BASE,
  ageInDays,
  htmlFetch,
  parseSearchPage,
  stripInvisible,
  viennaToday,
  writeError,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  jobage?: number // client-side: the portal has no public age parameter
  page: number // only 1: the server ignores ?page= and "load more" is client-side
  limit?: number
  format: "json" | "table" | "plain"
}

/** "Wien" -> "wien", "Niederösterreich" -> "niederoesterreich", "St. Pölten" -> "st-poelten". */
export function locationSlug(location: string | undefined): string {
  if (!location) return "oesterreich"
  const slug = location
    .trim()
    .toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
  return slug || "oesterreich"
}

export function buildUrl(opts: SearchOpts): string {
  const term = opts.query ? encodeURIComponent(opts.query.trim()) : "alle"
  return `${BASE}/suche/${locationSlug(opts.location)}/${term}`
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(9) + " " + "TITLE".padEnd(44) + " " + "COMPANY".padEnd(26) + " " + "LOCATION".padEnd(16) + " DATE"
  const rows = cards.map((c) => {
    const title = (c.title || "").slice(0, 44).padEnd(44)
    const company = (c.company || "—").slice(0, 26).padEnd(26)
    const loc = (c.location || "—").slice(0, 16).padEnd(16)
    return `${c.id.slice(0, 8).padEnd(9)} ${title} ${company} ${loc} ${c.date || "—"}`
  })
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts, today: string = viennaToday()): Promise<number> {
  try {
    const html = await htmlFetch(buildUrl(opts))
    if (!html) {
      writeError("search page returned 404 (unknown location slug?)", "NOT_FOUND")
      return 1
    }
    const page = parseSearchPage(html)
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
