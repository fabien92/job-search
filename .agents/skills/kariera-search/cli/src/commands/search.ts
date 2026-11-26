import { ageInDays, fold, httpFetch, listUrl, parseListing, politeDelay, stripInvisible, viennaToday, wantedRegions, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  location: string
  categories: string[]
  query?: string
  jobage?: number // days; walks the next pages while the cards stay this fresh
  page: number // 1-indexed; with --jobage, the first page of the walk
  maxPages: number // pages per category and region at most (with --jobage)
  limit?: number
  format: "json" | "table" | "plain"
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(8) + " " + "DATE".padEnd(10) + " " + "TITLE".padEnd(55) + " " + "COMPANY".padEnd(28) + " LOCATION"
  const rows = cards.map((c) =>
    [c.id.padEnd(8), (c.date ?? "—").padEnd(10), c.title.slice(0, 55).padEnd(55), (c.company ?? "—").slice(0, 28).padEnd(28), c.location || "—"].join(" "),
  )
  return [header, "-".repeat(header.length + 15), ...rows].join("\n")
}

/** Every word of the query (accents and case ignored) appears in the title. */
function matchesQuery(title: string, query: string | undefined): boolean {
  if (!query) return true
  const t = fold(title)
  return fold(query).replace(/["'“”„]/g, " ").split(/\s+/).filter(Boolean).every((w) => t.includes(w))
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  let regions: string[]
  try {
    regions = wantedRegions(opts.location)
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "BAD_ARG")
    return 1
  }
  const today = viennaToday()
  const byId = new Map<string, JobCard>()
  let requests = 0
  let hasMore = false
  try {
    for (const region of regions) {
      for (const category of opts.categories) {
        for (let page = opts.page, walked = 0; ; page++, walked++) {
          if (requests > 0) await politeDelay()
          requests++
          const res = await httpFetch(listUrl(category, region, page))
          if (!res) break // unknown listing or past the last page
          const { cards, hasNext } = parseListing(res.body, category)
          for (const card of cards) {
            const seen = byId.get(card.id)
            if (seen) {
              if (!seen.categories.includes(category)) seen.categories.push(category)
            } else byId.set(card.id, card)
          }
          // Newest first: stop at the first page whose oldest card is past --jobage.
          const oldest = cards.map((c) => ageInDays(c.date, today)).filter((a): a is number => a !== null)
          const stillFresh = opts.jobage !== undefined && oldest.length > 0 && Math.max(...oldest) <= opts.jobage
          if (!hasNext) break
          if (!stillFresh || walked + 1 >= opts.maxPages) {
            hasMore = true
            break
          }
        }
      }
    }
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
  let cards = [...byId.values()]
  const total = cards.length
  if (opts.jobage !== undefined) cards = cards.filter((c) => { const a = ageInDays(c.date, today); return a === null || a <= opts.jobage! })
  cards = cards.filter((c) => matchesQuery(c.title, opts.query))
  cards.sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""))
  cards = stripInvisible(cards)
  if (opts.limit !== undefined) cards = cards.slice(0, opts.limit)
  if (opts.format === "table") {
    process.stdout.write(renderTable(cards) + "\n")
  } else if (opts.format === "plain") {
    process.stdout.write(
      cards.map((c) => `${c.title}\n  ${c.company ?? "—"} · ${c.location || "—"} · ${c.date ?? "—"}${c.salary ? ` · ${c.salary}` : ""}\n  id: ${c.id}\n  ${c.url}`).join("\n\n") + "\n",
    )
  } else {
    process.stdout.write(JSON.stringify({ meta: { count: cards.length, page: opts.page, total, hasMore, requests }, results: cards }, null, 2) + "\n")
  }
  return 0
}
