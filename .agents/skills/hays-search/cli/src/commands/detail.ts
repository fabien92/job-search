import { htmlFetch, jobUrl, parseJobDetail, splitRef, stripInvisible, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

const HOST = /^www\.hays\.at$/i

/**
 * Accept "903672-1", "903672/1", or a www.hays.at posting URL
 * (/jobsuche/stellenangebote-jobs-detail-<slug>-903672/1 or …-detail?prospectNr=903672/1).
 */
export function normalizeId(input: string): { num: string; n: string } | null {
  const trimmed = input.trim()
  const direct = splitRef(trimmed)
  if (direct) return direct
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!HOST.test(parsed.hostname) || parsed.username || parsed.password) return null
  const slug = parsed.pathname.match(/^\/jobsuche\/stellenangebote-jobs-detail-[^/]*?-(\d{4,8})\/(\d{1,3})\/?$/)
  if (slug) return { num: slug[1], n: slug[2] }
  if (parsed.pathname === "/jobsuche/stellenangebote-jobs-detail") return splitRef(parsed.searchParams.get("prospectNr") ?? "")
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const ref = normalizeId(opts.id)
  if (!ref) {
    writeError(`Could not parse a Hays reference number (e.g. 903672-1) from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    const page = await htmlFetch(jobUrl(ref.num, ref.n))
    if (!page) {
      writeError("Job not found or no longer available", "NOT_FOUND")
      return 1
    }
    const job = stripInvisible(parseJobDetail(page.html, ref))
    if (opts.format === "plain") {
      const lines = [
        job.title,
        `via Hays · ${job.location || "—"}${job.industry ? ` · client industry: ${job.industry}` : ""}`,
        "",
        job.employmentType ?? "",
        job.date ? `Online since: ${job.date}` : "",
        job.startDate ? `Start: ${job.startDate}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
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
