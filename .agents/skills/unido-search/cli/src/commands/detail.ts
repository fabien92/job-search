import { BASE, htmlFetch, parseJobDetail, stripInvisible, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

const HOST = /^careers\.unido\.org$/i

/** Accept a numeric requisition id or a careers.unido.org/job/<slug>/<id>/ URL; other hosts rejected. */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  if (/^\d{4,12}$/.test(trimmed)) return trimmed
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!HOST.test(parsed.hostname) || parsed.username || parsed.password) return null
  const m = parsed.pathname.match(/^\/job\/[^/]+\/(\d{4,12})\/?$/)
  return m ? m[1] : null
}

export async function runDetail(opts: DetailOpts, now: Date = new Date()): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(`Could not parse a careers.unido.org job id from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    // Any slug resolves; /job/<id>/ without one redirects to an error page.
    const html = await htmlFetch(`${BASE}/job/job/${id}/`)
    if (!html) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const job = stripInvisible(parseJobDetail(html, id, now))
    if (opts.format === "plain") {
      const lines = [
        job.title + (job.grade ? ` (${job.grade})` : ""),
        `UNIDO · ${job.location || "—"}`,
        "",
        job.date ? `Posted: ${job.date}` : "",
        job.deadline ? `Deadline: ${job.deadline}` : "",
        `Status: ${job.isActive ? "ACTIVE" : "CLOSED / EXPIRED"}`,
        "",
        job.description || "(no description)",
        "",
        `URL: ${job.url}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(job, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}
