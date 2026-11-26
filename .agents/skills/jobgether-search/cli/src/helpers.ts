// Data source: Jobgether public job-search API for AI agents (remote jobs only).
//
// Search: GET https://jobgether.com/astroapi/ai/jobs.json?keyword=&locations=&sort=&page=&limit=
// (documented at /astroapi/ai/jobs/docs; `/api/v1/jobs` is the canonical alias but robots.txt
// `Disallow: /*?*` covers it with a query string, while `/astroapi/ai/jobs.json?*` is explicitly
// allowed: only that path is used). JSON: {jobs:[{id,title,company,url,location,remote,
// contractType,experience,salaryRange?,jobFunctions,postedAt}], pagination:{page,limit,hasMore}}.
// 25 per page at most, 10 pages at most, no total. Rate limit announced in the headers:
// 60 requests per 60 s ("ai-jobs" policy).
//
// No description and no per-offer endpoint in the API. The offer page /offer/<id>-<slug> answers
// 403 to this honest User-Agent, and the terms of use forbid extracting the platform's content by
// automated means (bots, scrapers, crawlers): the CLI never fetches it. `description` is built
// from the listing fields and says so.
//
// robots.txt (checked 2026-11-26): `User-agent: *`, Allow / and /astroapi/ai/jobs.json?*,
// Disallow /*?*, /offer/{*}, /proxy/*?*, /cdn-cgi/, /_server-islands/, /active-offers;
// Content-Signal: search=yes, ai-input=yes, ai-train=no.

export const BASE = "https://jobgether.com"
export const ENDPOINT = `${BASE}/astroapi/ai/jobs.json`
export const PAGE_SIZE = 25 // API cap
export const MAX_PAGES = 10 // API cap

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; jobgether-cli/1.0)"

export class ApiError extends Error {
  constructor(message: string, readonly code: string) {
    super(message)
  }
}

/** Short, single-line excerpt of an untrusted API message for an error report. */
function excerpt(text: unknown): string {
  return stripInvisible(String(text ?? "")).replace(/\s+/g, " ").slice(0, 200)
}

/** GET with exponential backoff (Retry-After honoured) on 429/5xx. 400 -> ApiError BAD_ARG; 404 -> null. */
export async function apiFetch(params: URLSearchParams): Promise<unknown | null> {
  const url = `${ENDPOINT}?${params.toString()}`
  const maxRetries = 6
  let delay = 1000
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": UA, Accept: "application/json" },
      redirect: "follow",
      signal: AbortSignal.timeout(30000),
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      const retryAfter = Number(response.headers.get("retry-after"))
      const wait = Number.isFinite(retryAfter) && retryAfter > 0 ? Math.min(retryAfter * 1000, 60000) : delay
      await new Promise((r) => setTimeout(r, wait + Math.floor(Math.random() * 1000)))
      delay = Math.min(delay * 2, 16000)
      continue
    }
    if (response.status === 404) return null
    if (response.status === 400) {
      let detail = "invalid parameter"
      try {
        const body = (await response.json()) as Record<string, unknown>
        detail = excerpt(body.detail ?? body.error ?? detail)
      } catch {
        /* keep the generic message */
      }
      throw new ApiError(`Jobgether rejected the request: ${detail}`, "BAD_ARG")
    }
    if (!response.ok) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    return await response.json()
  }
  throw new Error("Request failed after max retries")
}

/** Pause between page requests (rate limit 60/min). Overridable for tests (JOBGETHER_CLI_DELAY_MS=0). */
export function politeDelay(): Promise<void> {
  const ms = Number(process.env.JOBGETHER_CLI_DELAY_MS ?? 1100)
  return new Promise((r) => setTimeout(r, Number.isFinite(ms) && ms > 0 ? ms : 0))
}

export interface Job {
  id: string // 24-hex Jobgether id
  title: string
  company: string | null
  location: string | null // who may apply, e.g. "Europe, EMEA" or "Anywhere" (not an office)
  date: string | null // YYYY-MM-DD of postedAt (UTC)
  url: string // https://jobgether.com/offer/<id>-<slug> (a republished offer keeps the original's id here)
  remote: string | null // "Full Remote", …
  employmentType: string | null // "Full time", "Fixed term", "Freelance", "Part time", "Internships"
  seniority: string | null // "Senior (5-10 years)", …
  salary: string | null // "60000-80000 EUR" when given
  jobFunctions: string[]
  homeOffice: string | null // same as remote
  summary: null
  description: string // built from the listing fields (no full description in the API)
  applyUrl: null
  validThrough: null
  isActive: true
}

// ---------------------------------------------------------------- hygiene

/** Copied from linkedin-search: characters a reader never sees but a model does. */
const INVISIBLE_CHARS =
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F­؜᠎​-‏‪-‮⁠-⁯︀-️﻿\u{E0000}-\u{E007F}\u{E0100}-\u{E01EF}]/gu

/** Strip INVISIBLE_CHARS from every string in a result, recursively: the CLI's output boundary. */
export function stripInvisible<T>(value: T): T {
  if (typeof value === "string") return value.replace(INVISIBLE_CHARS, "") as T
  if (Array.isArray(value)) return value.map(stripInvisible) as T
  if (value !== null && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, stripInvisible(v)])) as T
  }
  return value
}

/** API strings are plain text; tags or a stray newline are flattened so a field stays one line. */
function text(value: unknown, max = 300): string | null {
  if (typeof value !== "string") return null
  const t = value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, max)
  return t || null
}

export const ID_RE = /^[0-9a-f]{24}$/

/**
 * Only https://jobgether.com or www.jobgether.com /offer/<id>-… URLs. The URL's id usually equals
 * the row's, but a republished offer keeps the URL of the original (other id): both are accepted.
 */
function offerUrl(raw: unknown): string | null {
  if (typeof raw !== "string") return null
  let u: URL
  try {
    u = new URL(raw)
  } catch {
    return null
  }
  if (u.protocol !== "https:" || !/^(www\.)?jobgether\.com$/i.test(u.hostname) || u.username || u.password) return null
  const m = u.pathname.match(/^\/offer\/([0-9a-f]{24})(?:-[^/]*)?$/)
  if (!m) return null
  return `${BASE}${u.pathname}`
}

export function describe(j: Omit<Job, "description">): string {
  const lines = [
    "Jobgether listing (remote job board). The API gives no full job description: the fields below are all that is known.",
    `Remote: ${j.remote ?? "unknown"}`,
    `Open to candidates in: ${j.location ?? "unknown"}`,
    `Contract: ${j.employmentType ?? "unknown"}`,
    `Experience: ${j.seniority ?? "unknown"}`,
  ]
  if (j.jobFunctions.length) lines.push(`Job functions: ${j.jobFunctions.join(", ")}`)
  if (j.salary) lines.push(`Salary: ${j.salary}`)
  if (j.date) lines.push(`Posted: ${j.date}`)
  lines.push(`Full posting (browser only): ${j.url}`)
  return lines.join("\n")
}

/** One API row -> Job, or null if id/title/url are missing or malformed (one bad row never breaks the rest). */
export function toJob(raw: unknown): Job | null {
  if (!raw || typeof raw !== "object") return null
  const r = raw as Record<string, unknown>
  const id = typeof r.id === "string" && ID_RE.test(r.id) ? r.id : null
  const title = text(r.title, 200)
  if (!id || !title) return null
  const url = offerUrl(r.url)
  if (!url) return null
  const posted = typeof r.postedAt === "string" && /^\d{4}-\d{2}-\d{2}/.test(r.postedAt) ? r.postedAt.slice(0, 10) : null
  const functions = Array.isArray(r.jobFunctions) ? r.jobFunctions.map((f) => text(f, 80)).filter((f): f is string => !!f).slice(0, 10) : []
  const remote = text(r.remote, 40)
  const base = {
    id,
    title,
    company: text(r.company, 120),
    location: text(r.location, 400),
    date: posted,
    url,
    remote,
    employmentType: text(r.contractType, 40),
    seniority: text(r.experience, 60),
    salary: text(r.salaryRange, 60),
    jobFunctions: functions,
    homeOffice: remote,
    summary: null,
    applyUrl: null,
    validThrough: null,
    isActive: true as const,
  }
  return stripInvisible({ ...base, description: describe(base) })
}

export interface Page {
  jobs: Job[]
  hasMore: boolean
}

export function parsePage(body: unknown): Page {
  const b = (body ?? {}) as Record<string, unknown>
  const rows = Array.isArray(b.jobs) ? b.jobs : []
  const pagination = (b.pagination ?? {}) as Record<string, unknown>
  return { jobs: rows.map(toJob).filter((j): j is Job => j !== null), hasMore: pagination.hasMore === true }
}

// ---------------------------------------------------------------- strict filter

/** Words in the eligibility field that mean "a candidate living in Europe may apply". */
const EUROPE_TERMS = ["europe", "european union", "emea", "dach", "cet"]

/** Place names implied by a location slug (the field prints "Austria", never "vienna"). */
const SLUG_NAMES: Record<string, string[]> = {
  vienna: ["vienna", "austria"],
  austria: ["austria"],
  bratislava: ["bratislava", "slovakia"],
  slovakia: ["slovakia"],
  budapest: ["budapest", "hungary"],
  hungary: ["hungary"],
}

function words(where: string): string {
  return ` ${where.toLowerCase().replace(/[^a-zÀ-ɏ]+/g, " ")} `
}

/**
 * --strict: keep a job only if its eligibility field names Europe (Europe, European Union, EMEA,
 * DACH, CET) or one of the searched places. "Anywhere" alone, or "Anywhere, United States", is
 * dropped: those are mostly US employers, and without a description nothing says Europe is accepted.
 */
export function isEuropeEligible(job: Job, slugs: string[]): boolean {
  const where = words(job.location ?? "")
  const names = [...EUROPE_TERMS, ...slugs.flatMap((s) => SLUG_NAMES[s] ?? [s.replace(/-/g, " ")])]
  return names.some((n) => where.includes(` ${n} `))
}

export function ageInDays(date: string | null): number | null {
  if (!date) return null
  const t = Date.parse(`${date}T00:00:00Z`)
  if (Number.isNaN(t)) return null
  const today = Date.parse(new Date().toISOString().slice(0, 10) + "T00:00:00Z")
  return Math.floor((today - t) / 86400000)
}
