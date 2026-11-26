import { MAX_PAGES, htmlFetch, listUrl, parseSearchPage, placePaths, politeDelay, stripInvisible, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  location?: string
  query?: string // client-side filter on the titles (keyword search is under /search/, disallowed)
  page?: number // undefined = every page (up to MAX_PAGES)
  limit?: number
  format: "json" | "table" | "plain"
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "REF".padEnd(18) + " " + "TITLE".padEnd(60) + " " + "LOCATION".padEnd(12) + " SALARY"
  const rows = cards.map((c) => [c.id.padEnd(18), c.title.slice(0, 60).padEnd(60), (c.location || "—").slice(0, 12).padEnd(12), c.salary || "—"].join(" "))
  return [header, "-".repeat(header.length + 20), ...rows].join("\n")
}

/** Walk the requested page(s) of each listing; null when the first page of the first listing is missing. */
async function fetchCards(paths: string[], opts: SearchOpts): Promise<{ cards: JobCard[]; hasMore: boolean } | null> {
  const out: JobCard[] = []
  let requests = 0
  let hasMore = false
  for (const path of paths) {
    const first = opts.page ?? 1
    for (let n = first; n < first + (opts.page === undefined ? MAX_PAGES : 1); n++) {
      if (requests++ > 0) await politeDelay()
      const res = await htmlFetch(listUrl(path, n))
      if (!res) {
        if (requests === 1) return null
        break
      }
      const parsed = parseSearchPage(res.html)
      out.push(...parsed.cards)
      if (opts.page !== undefined) hasMore = hasMore || parsed.hasNext
      if (parsed.cards.length === 0 || !parsed.hasNext) break
    }
  }
  const seen = new Set<string>()
  return { cards: out.filter((c) => !seen.has(c.id) && seen.add(c.id)), hasMore }
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  let paths: string[]
  try {
    paths = placePaths(opts.location)
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "BAD_ARG")
    return 1
  }
  try {
    const fetched = await fetchCards(paths, opts)
    if (!fetched) {
      writeError("listing page returned 404", "NOT_FOUND")
      return 1
    }
    let cards = stripInvisible(fetched.cards)
    if (opts.query) {
      const words = opts.query.toLowerCase().split(/\s+/).filter(Boolean)
      cards = cards.filter((c) => words.every((w) => c.title.toLowerCase().includes(w)))
    }
    const total = opts.page === undefined ? cards.length : null
    if (opts.limit !== undefined) cards = cards.slice(0, opts.limit)
    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map((c) => `${c.title}\n  via Michael Page · ${c.location || "—"}\n  ${[c.employmentType, c.salary, c.homeOffice].filter(Boolean).join(" · ")}\n  ref: ${c.id}\n  ${c.url}`)
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(JSON.stringify({ meta: { count: cards.length, page: opts.page ?? 1, total, hasMore: fetched.hasMore }, results: cards }, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
