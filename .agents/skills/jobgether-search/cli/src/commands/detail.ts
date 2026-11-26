import { ApiError, ID_RE, apiFetch, parsePage, politeDelay, writeError, type Job } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

const HOST = /^(www\.)?jobgether\.com$/i
const PAGES_PER_TRY = 3

/**
 * Accept https://jobgether.com/offer/<id>-<slug> (www. optional, scheme optional) and return the id
 * and the slug's words. A bare id is recognised but has no slug: the API cannot look it up.
 */
export function normalizeId(input: string): { id: string; words: string[] } | null {
  const trimmed = input.trim()
  if (ID_RE.test(trimmed)) return { id: trimmed, words: [] }
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!HOST.test(parsed.hostname) || parsed.username || parsed.password) return null
  const m = parsed.pathname.match(/^\/offer\/([0-9a-f]{24})(?:-([a-z0-9-]*))?\/?$/i)
  if (!m) return null
  const words = (m[2] ?? "").toLowerCase().split("-").filter((w) => w.length > 0)
  return { id: m[1].toLowerCase(), words }
}

/**
 * The API has no per-offer endpoint: search again with the slug's words (relevance order, a few
 * pages) and pick the row with this id (row id, or the id in its URL for a republished offer),
 * then with the first three words if that found nothing.
 */
async function findById(id: string, words: string[]): Promise<Job | null> {
  const tries = [words.join(" "), words.slice(0, 3).join(" ")].filter((k, i, a) => k && a.indexOf(k) === i)
  let requests = 0
  for (const keyword of tries) {
    for (let page = 1; page <= PAGES_PER_TRY; page++) {
      if (requests++ > 0) await politeDelay()
      const body = await apiFetch(new URLSearchParams({ keyword, sort: "relevance", page: String(page), limit: "25" }))
      if (body === null) return null
      const parsed = parsePage(body)
      const hit = parsed.jobs.find((j) => j.id === id || j.url.includes(`/offer/${id}`))
      if (hit) return hit
      if (!parsed.hasMore) break
    }
  }
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const ref = normalizeId(opts.id)
  if (!ref) {
    writeError(`Could not parse a Jobgether offer URL (https://jobgether.com/offer/<id>-<slug>) from "${opts.id}"`, "BAD_ID")
    return 1
  }
  if (ref.words.length === 0) {
    writeError("The Jobgether API has no per-offer lookup: pass the offer URL (https://jobgether.com/offer/<id>-<slug>), not the bare id", "NEEDS_URL")
    return 1
  }
  try {
    const job = await findById(ref.id, ref.words)
    if (!job) {
      writeError("Offer not found through the API (closed, or its title no longer matches the URL)", "NOT_FOUND")
      return 1
    }
    if (opts.format === "plain") {
      process.stdout.write(`${job.title}\n${job.company ?? "—"}\n\n${job.description}\n`)
    } else {
      process.stdout.write(JSON.stringify(job, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    if (e instanceof ApiError) {
      writeError(e.message, e.code)
      return 1
    }
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}
