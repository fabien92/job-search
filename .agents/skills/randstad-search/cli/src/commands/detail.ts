import { htmlFetch, jobUrl, parseJobDetail, stripInvisible, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

const HOST = /^www\.randstad\.at$/i

/** Accept "47720442" or a www.randstad.at posting URL (/jobs/<slug>_<city>_47720442/). */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  if (/^\d{6,10}$/.test(trimmed)) return trimmed
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!HOST.test(parsed.hostname) || parsed.username || parsed.password) return null
  const m = parsed.pathname.match(/^\/jobs\/[^/]+_(\d{6,10})\/?$/)
  return m ? m[1] : null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(`Could not parse a Randstad job id (e.g. 47720442) from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    const page = await htmlFetch(jobUrl(id))
    if (!page) {
      writeError("Job not found or no longer available", "NOT_FOUND")
      return 1
    }
    const job = stripInvisible(parseJobDetail(page.html, id, page.url))
    if (opts.format === "plain") {
      const lines = [
        job.title,
        `via Randstad · ${job.location || "—"}${job.specialism ? ` · ${job.specialism}` : ""}`,
        "",
        [job.employmentType, job.hours].filter(Boolean).join(" · "),
        job.date ? `Published: ${job.date}` : "",
        job.validThrough ? `Valid through: ${job.validThrough}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
        job.reference ? `Reference: ${job.reference}` : "",
        "",
        job.description || "(no description)",
        "",
        `URL: ${job.url}`,
      ].filter((l, i, a) => l !== "" || (i > 0 && a[i - 1] !== ""))
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
