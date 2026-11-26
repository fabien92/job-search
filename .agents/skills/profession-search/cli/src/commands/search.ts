import { REMOTE_HU, feedUrl, fold, httpFetch, jobUrl, parseFeed, parseJobDetail, politeDelay, stripInvisible, wantedPlaces, writeError, type JobCard } from "../helpers.js"

export interface SearchOpts {
  location?: string
  category: string
  limit?: number
  lookups: number // at most this many postings read to place cards whose slug names no town
  format: "json" | "table" | "plain"
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const header = "ID".padEnd(8) + " " + "TITLE".padEnd(60) + " " + "COMPANY".padEnd(30) + " LOCATION"
  const rows = cards.map((c) => [c.id.padEnd(8), c.title.slice(0, 60).padEnd(60), (c.company ?? "—").slice(0, 30).padEnd(30), c.location || "—"].join(" "))
  return [header, "-".repeat(header.length + 15), ...rows].join("\n")
}

/** "Budapest" or "Budapest XIII. kerület" is in the wanted set. */
const inPlaces = (location: string | null, wanted: Set<string>) => {
  const f = location ? fold(location) : ""
  return [...wanted].some((w) => f === w || f.startsWith(w + " ") || f.startsWith(w + ","))
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  let wanted: Set<string> | null
  try {
    wanted = wantedPlaces(opts.location)
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "BAD_ARG")
    return 1
  }
  try {
    const feed = await httpFetch(feedUrl(opts.category), "application/rss+xml,application/xml;q=0.9,*/*;q=0.8")
    if (!feed) {
      writeError(`feed rss-${opts.category}.rss returned 404`, "NOT_FOUND")
      return 1
    }
    const all = parseFeed(feed.body)
    let cards: JobCard[] = all
    let unresolved = 0
    if (wanted) {
      // Cards whose slug names a town are kept or dropped on it; the others are placed by reading
      // their posting (a few per feed), and dropped when that fails or the cap is reached. A posting
      // without an address but flagged remote (TELECOMMUTE) is kept: remote within Hungary.
      const kept: JobCard[] = []
      let lookups = 0
      for (const card of all) {
        if (card.location) {
          if (inPlaces(card.location, wanted)) kept.push(card)
          continue
        }
        if (lookups >= opts.lookups) {
          unresolved++
          continue
        }
        lookups++
        await politeDelay()
        let location: string | null = null
        try {
          const page = await httpFetch(jobUrl(card.id))
          location = page ? parseJobDetail(page.body, card.id).location : null
        } catch {
          location = null
        }
        if (!location) unresolved++
        // No address but flagged TELECOMMUTE: open to someone living in any wanted Hungarian town
        else if (location === REMOTE_HU || inPlaces(location, wanted)) kept.push({ ...card, location })
      }
      cards = kept
    }
    cards = stripInvisible(cards)
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)
    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards.map((c) => `${c.title}\n  ${c.company ?? "—"} · ${c.location || "—"}\n  id: ${c.id}\n  ${c.url}`).join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify({ meta: { count: cards.length, page: 1, total: all.length, hasMore: false, unresolved }, results: cards }, null, 2) + "\n",
      )
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
