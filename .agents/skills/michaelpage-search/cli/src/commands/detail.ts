import { htmlFetch, isRef, parseJobDetail, postingUrl, stripInvisible, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const target = postingUrl(opts.id)
  if (!target) {
    const hint = isRef(opts.id) ? " (a bare ref is not enough: the page needs its slug; pass the url from search)" : ""
    writeError(`Could not parse a www.michaelpage.at posting URL (/job-detail/<slug>/ref/<ref>) from "${opts.id}"${hint}`, "BAD_ID")
    return 1
  }
  try {
    const page = await htmlFetch(target.url)
    if (!page) {
      writeError("Job not found or no longer available", "NOT_FOUND")
      return 1
    }
    const job = stripInvisible(parseJobDetail(page.html, target.url, target.ref))
    if (opts.format === "plain") {
      const lines = [
        job.title,
        `via Michael Page · ${job.location || "—"}${job.industry ? ` · ${job.industry}` : ""}`,
        "",
        [job.employmentType, job.homeOffice].filter(Boolean).join(" · "),
        job.date ? `Published: ${job.date}` : "",
        job.validThrough ? `Valid through: ${job.validThrough}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
        `Reference: ${job.id}`,
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
