import { BASE, htmlFetch, parseJobDetail, stripInvisible, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

const HOST = /^vacancies\.osce\.org$/i

/** Accept a numeric job id or a vacancies.osce.org/jobs/<slug>-<id> URL; other hosts rejected. */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  if (/^\d{1,8}$/.test(trimmed)) return trimmed
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!HOST.test(parsed.hostname) || parsed.username || parsed.password) return null
  const m = parsed.pathname.match(/^\/jobs\/(?:[a-z0-9%-]+-)?(\d{1,8})\/?$/i)
  return m ? m[1] : null
}

export async function runDetail(opts: DetailOpts, now: Date = new Date()): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(`Could not parse a vacancies.osce.org job id from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    const page = await htmlFetch(`${BASE}/jobs/${id}`)
    if (!page) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const job = stripInvisible(parseJobDetail(page.html, id, now))
    if (opts.format === "plain") {
      const lines = [
        job.title,
        `OSCE · ${job.location || "—"}${job.issuedBy ? ` · issued by ${job.issuedBy}` : ""}`,
        "",
        [job.jobType, job.employmentType, job.grade ? `grade ${job.grade}` : null, job.jobLevel].filter(Boolean).join(" · "),
        job.date ? `Issued: ${job.date}` : "",
        job.deadline ? `Closing: ${job.deadline}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
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
