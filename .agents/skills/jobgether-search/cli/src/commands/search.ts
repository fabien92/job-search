import { MAX_PAGES, PAGE_SIZE, ApiError, ageInDays, apiFetch, isEuropeEligible, parsePage, politeDelay, writeError, type Job } from "../helpers.js"

export interface SearchOpts {
  query?: string
  locations: string[] // API location slugs
  jobage?: number
  page?: number // undefined = walk pages (up to MAX_PAGES)
  limit?: number
  sort: "date" | "relevance"
  strict: boolean
  format: "json" | "table" | "plain"
}

export function buildParams(opts: SearchOpts, page: number): URLSearchParams {
  const p = new URLSearchParams()
  if (opts.query) p.set("keyword", opts.query)
  if (opts.locations.length) p.set("locations", opts.locations.join(","))
  p.set("sort", opts.sort)
  p.set("page", String(page))
  p.set("limit", String(PAGE_SIZE))
  return p
}

const tooOld = (j: Job, jobage: number | undefined) => jobage !== undefined && (ageInDays(j.date) ?? 0) > jobage

/**
 * Walk the requested page(s). With --sort date (default) the list is strictly newest first, so
 * --jobage stops the walk at the first page that reaches older offers.
 */
async function fetchJobs(opts: SearchOpts): Promise<{ jobs: Job[]; hasMore: boolean } | null> {
  const first = opts.page ?? 1
  const last = opts.page ?? MAX_PAGES
  const out: Job[] = []
  let hasMore = false
  for (let n = first; n <= last; n++) {
    if (n > first) await politeDelay()
    const body = await apiFetch(buildParams(opts, n))
    if (body === null) return n === first ? null : { jobs: out, hasMore: false }
    const page = parsePage(body)
    out.push(...page.jobs)
    hasMore = page.hasMore
    if (!page.hasMore || page.jobs.length === 0) break
    if (opts.sort === "date" && opts.jobage !== undefined && page.jobs.some((j) => tooOld(j, opts.jobage))) break
  }
  const seen = new Set<string>()
  return { jobs: out.filter((j) => !seen.has(j.id) && seen.add(j.id)), hasMore }
}

function renderTable(jobs: Job[]): string {
  if (jobs.length === 0) return "No results."
  const header = "ID".padEnd(24) + " " + "DATE".padEnd(10) + " " + "TITLE".padEnd(50) + " " + "COMPANY".padEnd(24) + " OPEN TO"
  const rows = jobs.map((j) =>
    [j.id, (j.date ?? "—").padEnd(10), j.title.slice(0, 50).padEnd(50), (j.company ?? "—").slice(0, 24).padEnd(24), (j.location ?? "—").slice(0, 50)].join(" "),
  )
  return [header, "-".repeat(header.length + 30), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const fetched = await fetchJobs(opts)
    if (!fetched) {
      writeError("search endpoint returned 404", "NOT_FOUND")
      return 1
    }
    const fetchedCount = fetched.jobs.length
    let jobs = fetched.jobs.filter((j) => !tooOld(j, opts.jobage) && (!opts.strict || isEuropeEligible(j, opts.locations)))
    const dropped = fetchedCount - jobs.length
    if (opts.limit !== undefined) jobs = jobs.slice(0, opts.limit)
    if (opts.format === "table") {
      process.stdout.write(renderTable(jobs) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        jobs
          .map((j) => `${j.title}\n  ${j.company ?? "—"} · ${j.remote ?? "remote"} · open to: ${j.location ?? "—"} · ${j.date ?? "—"}\n  ${[j.employmentType, j.seniority, j.salary].filter(Boolean).join(" · ")}\n  id: ${j.id}\n  ${j.url}`)
          .join("\n\n") + "\n",
      )
    } else {
      const meta = { count: jobs.length, page: opts.page ?? 1, total: null, fetched: fetchedCount, filtered: dropped, hasMore: fetched.hasMore }
      process.stdout.write(JSON.stringify({ meta, results: jobs }, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    if (e instanceof ApiError) {
      writeError(e.message, e.code)
      return 1
    }
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
