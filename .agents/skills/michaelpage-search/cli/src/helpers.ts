// Data source: Michael Page Austria job board, www.michaelpage.at (Drupal, server-rendered HTML).
// Public pages, no authentication. Michael Page is a recruitment agency: the client employer is
// not named, so `company` is null and `recruiter` is "Michael Page".
//
// Search: GET https://www.michaelpage.at/jobs/information-technology/<place> (Vienna: wien-0,
// Austria: österreich), both published in /sitemap.xml?lang=de; the next page is ?page=<n-1>
// (Drupal, 0-indexed; 30 cards per page, "Weitere Jobs anzeigen" a[rel=next] while more exist).
// 43 IT openings in Vienna on 2026-11-26. No total and no date on the list. One
// <li class="views-row"> per opening: div.job-title h3 > a[href=/job-detail/<slug>/ref/<ref>],
// div.job-location, div.job-contract-type, div.job-salary, div.job-nature ("Home Office"),
// div.job_advert__job-summary-text (teaser). Keyword search lives under /search/: not used.
// The ref ("jn-112026-7140475") carries the month the opening was created, not its publication.
//
// Detail: GET https://www.michaelpage.at/job-detail/<slug>/ref/<ref> (the slug is required: a
// wrong slug answers 404, like a closed opening). A JSON-LD JobPosting carries title, datePosted,
// employmentType, baseSalary, jobLocation, jobLocationType (TELECOMMUTE) and the full description.
//
// robots.txt (checked 2026-11-26): disallows /search/, /*/search/, /job-apply/, the salary,
// contract, brand and item_per_pages query filters, and */jobs/*/*/*/ (three levels); the two-level
// listing, ?page= and /job-detail/ paths used here are allowed. No Crawl-delay for `*`. Terms
// (/allgemeine-geschäftsbedingungen, "Geistiges Eigentum"): view and store on your own disk for
// personal, non-commercial use; no reproduction or distribution; no clause on automated access.

export const BASE = "https://www.michaelpage.at"
export const PAGE_SIZE = 30
export const MAX_PAGES = 10 // safety cap: 2 pages for Vienna today

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; michaelpage-cli/1.0)"

export interface Fetched {
  html: string
  url: string // final URL after redirects
}

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404 or 410 (closed or unknown opening). */
export async function htmlFetch(url: string): Promise<Fetched | null> {
  const maxRetries = 6
  let delay = 1000
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": UA, "Accept-Language": "de-AT,de;q=0.9,en;q=0.8", Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8" },
      redirect: "follow",
      signal: AbortSignal.timeout(30000),
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      const jitter = Math.floor(Math.random() * 1000)
      await new Promise((r) => setTimeout(r, delay + jitter))
      delay = Math.min(delay * 2, 16000)
      continue
    }
    if (response.status === 404 || response.status === 410) return null
    if (!response.ok) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    return { html: await response.text(), url: response.url || url }
  }
  throw new Error("Request failed after max retries")
}

/** Pause between page requests (no Crawl-delay for `*`; keep it gentle). MICHAELPAGE_CLI_DELAY_MS=0 in tests. */
export function politeDelay(): Promise<void> {
  const ms = Number(process.env.MICHAELPAGE_CLI_DELAY_MS ?? 3000)
  return new Promise((r) => setTimeout(r, Number.isFinite(ms) && ms > 0 ? ms : 0))
}

export interface JobCard {
  id: string // Michael Page reference, e.g. "jn-112026-7140475"
  title: string
  company: null // the client is not named
  recruiter: "Michael Page"
  location: string | null
  date: null // not on the list: read `detail` (JSON-LD datePosted)
  url: string // the posting URL, slug included (detail needs it)
  employmentType: string | null // "Festanstellung", "Interim", …
  homeOffice: string | null // "Home Office" when the card says so
  salary: string | null // "63.000€ - 85.000€ p.a."
  summary: string | null
}

export interface JobDetail extends Omit<JobCard, "date" | "homeOffice"> {
  date: string | null // JSON-LD datePosted, YYYY-MM-DD (may be a refresh: later than the ref month)
  homeOffice: string | null // "Remote (TELECOMMUTE)" from jobLocationType
  industry: string | null
  description: string | null
  applyUrl: null // applying goes through Michael Page (/job-apply/, disallowed, never touched)
  validThrough: string | null
  isActive: boolean
}

// ---------------------------------------------------------------- hygiene

function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

const NAMED: Record<string, string> = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ",
  auml: "ä", ouml: "ö", uuml: "ü", Auml: "Ä", Ouml: "Ö", Uuml: "Ü", szlig: "ß",
  eacute: "é", egrave: "è", agrave: "à", ccedil: "ç", euro: "€", ndash: "–", mdash: "—",
  bdquo: "„", ldquo: "“", rdquo: "”", lsquo: "‘", rsquo: "’", sbquo: "‚", hellip: "…",
  bull: "•", middot: "·", copy: "©", reg: "®", trade: "™", laquo: "«", raquo: "»",
  shy: "­", zwj: "‍", zwnj: "‌",
}

export function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    .replace(/&([a-zA-Z]+);/g, (m, name) => NAMED[name] ?? m)
}

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

const ATTRS = String.raw`(?:[^>"']|"[^"]*"|'[^']*')*`
const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"])

function isHiddenTag(attrs: string): boolean {
  for (const m of attrs.matchAll(/([^\s"'=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g)) {
    const name = m[1].toLowerCase()
    const value = m[2] ?? m[3] ?? m[4] ?? ""
    if (name === "hidden") return true
    if (name === "style" && /(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all)\b/i.test(value)) {
      return true
    }
  }
  return false
}

/** Copied from linkedin-search: drop comments, script/style/template and hidden elements before tag stripping. */
export function visibleHtml(html: string): string {
  const src = html
    .replace(/<!--[\s\S]*?(?:-->|$)/g, "")
    .replace(/<(script|style|template)\b[^>]*>[\s\S]*?(?:<\/\1\s*>|$)/gi, "")
  const open = new RegExp(`<([a-zA-Z][a-zA-Z0-9-]*)(\\s${ATTRS})?>`, "g")
  const kept: string[] = []
  let from = 0
  let m: RegExpExecArray | null
  while ((m = open.exec(src)) !== null) {
    if (!m[2] || !isHiddenTag(m[2])) continue
    const tag = m[1].toLowerCase()
    let end = open.lastIndex
    if (!VOID_TAGS.has(tag)) {
      const same = new RegExp(`<(/?)([a-zA-Z][a-zA-Z0-9-]*)${ATTRS}>`, "g")
      same.lastIndex = end
      end = src.length
      let depth = 1
      let s: RegExpExecArray | null
      while ((s = same.exec(src)) !== null) {
        if (s[2].toLowerCase() !== tag) continue
        if (s[1]) depth--
        else depth++
        if (depth === 0) {
          end = same.lastIndex
          break
        }
      }
    }
    kept.push(src.slice(from, m.index))
    from = end
    open.lastIndex = end
  }
  kept.push(src.slice(from))
  return kept.join("")
}

function stripTags(html: string): string {
  return visibleHtml(html).replace(new RegExp(`<${ATTRS}>`, "g"), " ").replace(/\s+/g, " ").trim()
}

/** Inline text: hidden markup dropped, tags stripped, entities decoded. */
export function clean(html: string | null | undefined): string | null {
  if (typeof html !== "string") return null
  const out = decodeHtmlEntities(stripTags(html)).replace(/\s+/g, " ").trim()
  return out || null
}

/** Block text: like clean() but keeps paragraph, list and line breaks. */
export function cleanBlock(html: string | null | undefined): string | null {
  if (typeof html !== "string") return null
  const withBreaks = visibleHtml(html)
    .replace(/\s+/g, " ")
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\s*li\b[^>]*>/gi, "\n• ")
    .replace(/<\/(p|li|ul|ol|div|h\d|tr|section)>/gi, "\n")
  const text = withBreaks
    .split("\n")
    .map((line) => {
      const c = clean(line)
      return c === "•" ? "" : (c ?? "")
    })
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  return text || null
}

// ---------------------------------------------------------------- dates

/** Today's calendar date in Vienna, YYYY-MM-DD. */
export function viennaToday(now: Date = new Date()): string {
  return viennaDate(now)!
}

/** Vienna calendar date of an ISO timestamp ("2026-11-24T23:30:00Z" -> "2026-11-25"); null if unparseable. */
export function viennaDate(value: Date | string | null | undefined): string | null {
  const d = value instanceof Date ? value : typeof value === "string" ? new Date(value) : null
  if (!d || Number.isNaN(d.getTime())) return null
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Vienna", year: "numeric", month: "2-digit", day: "2-digit" }).format(d)
}

export function ageInDays(iso: string | null, today: string = viennaToday()): number | null {
  if (!iso) return null
  const a = Date.parse(`${iso}T00:00:00Z`)
  const b = Date.parse(`${today}T00:00:00Z`)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.round((b - a) / 86400000)
}

// ---------------------------------------------------------------- Michael Page parsing

/** Spellings of one place -> its IT listing path (both in the sitemap). */
export const PLACES: { names: string[]; path: string }[] = [
  { names: ["wien", "vienna", "vienne"], path: "/jobs/information-technology/wien-0" },
  { names: ["österreich", "oesterreich", "austria", "autriche"], path: "/jobs/information-technology/%C3%B6sterreich" },
]

/** "Wien,Vienna" -> the distinct listing paths; throws on a place without a known listing. */
export function placePaths(location: string | undefined): string[] {
  const wanted = (location ?? "wien").split(",").map((l) => l.trim().toLowerCase()).filter(Boolean)
  const paths: string[] = []
  for (const w of wanted.length ? wanted : ["wien"]) {
    const place = PLACES.find((p) => p.names.includes(w))
    if (!place) throw new Error(`unknown place "${w}" (known: ${PLACES.map((p) => p.names[0]).join(", ")})`)
    if (!paths.includes(place.path)) paths.push(place.path)
  }
  return paths
}

/** Page n (1-indexed) of a listing: Drupal counts from 0, page 1 has no parameter. */
export function listUrl(path: string, page: number): string {
  return `${BASE}${path}${page > 1 ? `?page=${page - 1}` : ""}`
}

const REF = /^jn-\d{6}-\d{5,9}$/

/** A www.michaelpage.at posting URL (slug included) -> its canonical URL and ref; null otherwise. */
export function postingUrl(input: string): { url: string; ref: string } | null {
  const trimmed = input.trim()
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (!hasScheme && !/^www\.michaelpage\.at\//i.test(trimmed)) return null
  let parsed: URL
  try {
    parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
  } catch {
    return null
  }
  if (!/^www\.michaelpage\.at$/i.test(parsed.hostname) || parsed.username || parsed.password) return null
  const m = parsed.pathname.match(/^\/job-detail\/([^/]+)\/ref\/(jn-\d{6}-\d{5,9})\/?$/i)
  if (!m) return null
  return { url: `${BASE}/job-detail/${m[1]}/ref/${m[2].toLowerCase()}`, ref: m[2].toLowerCase() }
}

export function isRef(text: string): boolean {
  return REF.test(text.trim().toLowerCase())
}

export interface SearchPage {
  cards: JobCard[]
  hasNext: boolean
}

function field(chunk: string, cls: string): string | null {
  const m = chunk.match(new RegExp(`<div class="${cls}[^"]*">([\\s\\S]*?)</div>`))
  return m ? clean(m[1]) : null
}

/** Split into views-row chunks and parse each on its own. */
export function parseSearchPage(html: string): SearchPage {
  const cards: JobCard[] = []
  const seen = new Set<string>()
  for (const raw of html.split(/<li class="views-row">/).slice(1)) {
    try {
      const chunk = visibleHtml(raw)
      const a = chunk.match(/<div class="job-title[^"]*"[^>]*>\s*<h3>\s*<a href="(\/job-detail\/[^"/?#]+\/ref\/(jn-\d{6}-\d{5,9}))"[^>]*>([\s\S]*?)<\/a>/i)
      if (!a) continue
      const [, path, rawRef, rawTitle] = a
      const id = rawRef.toLowerCase()
      const title = clean(rawTitle)
      if (!title || seen.has(id)) continue
      seen.add(id)
      const summary = field(chunk, "job_advert__job-summary-text")
      cards.push({
        id,
        title,
        company: null,
        recruiter: "Michael Page",
        location: field(chunk, "job-location"),
        date: null,
        url: BASE + path,
        employmentType: field(chunk, "job-contract-type"),
        homeOffice: field(chunk, "job-nature"),
        salary: field(chunk, "job-salary"),
        summary: summary && summary.length > 600 ? summary.slice(0, 600) + "…" : summary,
      })
    } catch {
      continue
    }
  }
  return { cards, hasNext: /<a\b[^>]*\brel="next"/.test(html) }
}

/** The JobPosting object of the page's JSON-LD (raw control characters tolerated); null if none. */
function jobPosting(html: string): Record<string, any> | null {
  for (const m of html.matchAll(/<script type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)) {
    let data: any
    try {
      data = JSON.parse(m[1].replace(/[\u0000-\u001f]/g, " "))
    } catch {
      continue
    }
    const items = Array.isArray(data) ? data : Array.isArray(data?.["@graph"]) ? data["@graph"] : [data]
    const job = items.find((i: any) => i && i["@type"] === "JobPosting")
    if (job) return job
  }
  return null
}

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null)

function salaryText(base: any): string | null {
  const v = base?.value
  const min = Number(v?.minValue)
  const max = Number(v?.maxValue)
  const cur = str(base?.currency) === "EUR" ? "€" : (str(base?.currency) ?? "")
  const unit = str(v?.unitText) === "YEAR" ? " p.a." : str(v?.unitText) ? ` / ${str(v?.unitText)!.toLowerCase()}` : ""
  const fmt = (n: number) => n.toLocaleString("de-AT") + cur
  if (Number.isFinite(min) && min > 0 && Number.isFinite(max) && max > 0) return `${fmt(min)} - ${fmt(max)}${unit}`
  if (Number.isFinite(min) && min > 0) return `ab ${fmt(min)}${unit}`
  return null
}

export function parseJobDetail(html: string, url: string, ref: string): JobDetail {
  const job = jobPosting(html)
  if (!job) throw new Error("detail page has no JSON-LD JobPosting (markup changed?)")
  const title = clean(str(job.title) ?? "")
  if (!title) throw new Error("JobPosting has no title (markup changed?)")
  const addr = job.jobLocation?.address ?? (Array.isArray(job.jobLocation) ? job.jobLocation[0]?.address : null)
  const place = [str(addr?.addressLocality), str(addr?.addressRegion)].filter(Boolean).join(", ") || null
  const posted = str(job.datePosted)?.slice(0, 10) ?? null
  const until = str(job.validThrough)?.slice(0, 10) ?? null
  const intro = "Posted by Michael Page (recruitment agency) for a client; the employer is not named."
  const types = Array.isArray(job.employmentType) ? job.employmentType.join(", ") : str(job.employmentType)
  return {
    id: ref,
    title,
    company: null,
    recruiter: "Michael Page",
    location: place,
    date: posted && /^\d{4}-\d{2}-\d{2}$/.test(posted) ? posted : null,
    url,
    employmentType: types,
    homeOffice: str(job.jobLocationType) === "TELECOMMUTE" ? "Remote (TELECOMMUTE)" : null,
    salary: salaryText(job.baseSalary),
    summary: null,
    industry: str(job.industry),
    description: [intro, cleanBlock(str(job.description))?.replace(/\n{2,}(?=• )/g, "\n") ?? "(no description)"].join("\n\n"),
    applyUrl: null,
    validThrough: until && /^\d{4}-\d{2}-\d{2}$/.test(until) ? until : null,
    isActive: until ? until >= viennaToday() : true,
  }
}
