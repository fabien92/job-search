import { MAX_PAGES, PAGE_SIZE, ageInDays, htmlFetch, listUrl, parseSearchPage, placePaths, politeDelay, stripInvisible, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  location?: string
  specialism?: string // Berufsfeld slug ("edv-it"): walk /jobs/s-<slug>/… instead of /jobs/…
  jobage?: number
  page?: number // undefined = every page (up to MAX_PAGES)
  limit?: number
  format: "json" | "table" | "plain"
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(9) + " " + "DATE".padEnd(10) + " " + "TITLE".padEnd(60) + " LOCATION"
  const rows = cards.map((c) => [c.id.padEnd(9), (c.date ?? "—").padEnd(10), c.title.slice(0, 60).padEnd(60), c.location || "—"].join(" "))
  return [header, "-".repeat(header.length + 25), ...rows].join("\n")
}

const tooOld = (c: JobCard, jobage: number | undefined) => jobage !== undefined && (ageInDays(c.date) ?? 0) > jobage

/**
 * Walk the requested page(s) of each listing. The list is not in date order, so --jobage never
 * stops the walk early. Returns null when the first page of the first listing is missing.
 */
async function fetchCards(paths: string[], opts: SearchOpts): Promise<{ cards: JobCard[]; total: number | null } | null> {
  const out: JobCard[] = []
  let total: number | null = 0
  let requests = 0
  for (const path of paths) {
    const first = opts.page ?? 1
    let listTotal: number | null = null
    for (let n = first; n < first + (opts.page === undefined ? MAX_PAGES : 1); n++) {
      if (requests++ > 0) await politeDelay()
      const res = await htmlFetch(listUrl(path, n))
      if (!res) {
        if (requests === 1) return null
        break
      }
      const parsed = parseSearchPage(res.html)
      if (listTotal === null) listTotal = parsed.total
      out.push(...parsed.cards)
      if (parsed.cards.length === 0) break
      if (listTotal !== null && n * PAGE_SIZE >= listTotal) break
    }
    total = total === null || listTotal === null ? null : total + listTotal
  }
  const seen = new Set<string>()
  return { cards: out.filter((c) => !seen.has(c.id) && seen.add(c.id)), total }
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  let paths: string[]
  try {
    paths = placePaths(opts.location, opts.specialism)
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
    let cards = stripInvisible(fetched.cards).filter((c) => !tooOld(c, opts.jobage))
    const total = opts.jobage !== undefined ? (opts.page === undefined ? cards.length : null) : fetched.total
    const page = opts.page ?? 1
    const hasMore = opts.page !== undefined && fetched.total !== null && paths.length === 1 ? page * PAGE_SIZE < fetched.total : false
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)
    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map((c) => `${c.title}\n  via Randstad · ${c.location || "—"} · ${c.date ?? "—"}\n  ${[c.employmentType, c.salary].filter(Boolean).join(" · ")}\n  id: ${c.id}\n  ${c.url}`)
          .join("\n\n") + "\n",
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
