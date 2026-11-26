import { httpFetch, jobUrl, parseHref, parseJobDetail, stripInvisible, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

/** Accept "1559635" or a kariera.zoznam.sk posting URL (/pracovna-ponuka/1559635[/<slug>]). */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  if (/^\d{5,9}$/.test(trimmed)) return trimmed
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!["kariera.zoznam.sk", "www.kariera.sk", "kariera.sk"].includes(parsed.hostname.toLowerCase()) || parsed.username || parsed.password) return null
  return parseHref(parsed.pathname)?.id ?? null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(`Could not parse a Kariéra.sk offer id (e.g. 1559635) from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    const page = await httpFetch(jobUrl(id))
    if (!page) {
      writeError("Job not found or no longer available", "NOT_FOUND")
      return 1
    }
    const job = stripInvisible(parseJobDetail(page.body, id))
    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company ?? "—"} · ${job.location || "—"}`,
        job.category ? `Category: ${job.category}` : "",
        "",
        job.employmentType ? `Employment: ${job.employmentType}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
        job.date ? `Published: ${job.date}` : "",
        job.validThrough ? `Valid through: ${job.validThrough}` : "",
        job.source ? `Source: ${job.source}` : "",
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
