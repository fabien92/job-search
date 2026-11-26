import { API, apiFetch, parseJobDetail, stripInvisible, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

const HOST = /^careers\.un\.org$/i

/**
 * Accept a numeric job opening id or a careers.un.org/jobSearchDescription/<id> URL. URLs on
 * any other host (or with userinfo) are rejected; host and path are read through URL parsing.
 */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  if (/^\d{1,9}$/.test(trimmed)) return trimmed
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!HOST.test(parsed.hostname) || parsed.username || parsed.password) return null
  const m = parsed.pathname.match(/^\/jobSearchDescription\/(\d{1,9})\/?$/)
  return m ? m[1] : null
}

export async function runDetail(opts: DetailOpts, now: Date = new Date()): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(`Could not parse a careers.un.org job opening id from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    // GET only: PUT on /jo/<id>/<lang> would count a page view on the portal.
    const data = await apiFetch(`${API}/joV2/${id}/en`)
    if (!data) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const job = stripInvisible(parseJobDetail(data, now))
    if (opts.format === "plain") {
      const lines = [
        job.title + (job.grade ? ` (${job.grade})` : ""),
        `${job.company || "—"} · ${job.location || "—"}`,
        "",
        job.date ? `Posted: ${job.date}` : "",
        job.deadline ? `Deadline: ${job.deadline}` : "",
        job.category ? `Category: ${job.category}` : "",
        job.contract ? `Recruitment: ${job.contract}` : "",
        `Status: ${job.isActive ? "ACTIVE" : "CLOSED / EXPIRED"}`,
        "",
        job.description || "(no description)",
        "",
        `URL: ${job.url}`,
        job.applyUrl ? `Apply: ${job.applyUrl}` : "",
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
