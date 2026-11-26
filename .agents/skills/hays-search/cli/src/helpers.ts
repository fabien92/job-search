// Data source: Hays Austria job search, www.hays.at (Liferay portal, server-rendered HTML).
// Public pages, no authentication. Hays is a recruitment agency: the client employer is
// almost never named, so `company` is null and `recruiter` is "Hays".
//
// Search: GET https://www.hays.at/en/jobsearch/job-offers/c/Austria/<AT>/p/<n>?q=<q>
// (20 openings per page; no trailing slash, `/p/<n>/` answers 301). Austria holds about 70
// openings (2026-11-26), i.e. 4 pages. Without a keyword the list is newest first.
// One <div class="search__result border-radius-10"> per opening: a.search__result__link
// (/jobsuche/stellenangebote-jobs-detail-<slug>-<num>/<n>), h4.search__result__header__title,
// contract type and location in .search__result__job__attribute__{type,location} .info-text,
// teaser in .search__result__teaser, "Online since: Tue Nov 24 15:11:24 CET 2026".
// span#totalJobs "Show 72 results" gives the total.
//
// Detail: GET https://www.hays.at/jobsuche/stellenangebote-jobs-detail?prospectNr=<num>/<n>
// (slug not needed). An unknown or closed opening redirects to /jobsuche/stelle-nicht-verfuegbar.
// h1 headline, three .h-job-detail__meta-item (contract type, location, start date), JSON-LD
// JobPosting (datePosted, employmentType, industry), then sections .h-job-detail__listing
// (h3.h-job-detail__listing-title + .h-job-detail__listing-body): About the company,
// Responsibilities, Profile, Benefits, Salary information.
//
// robots.txt (checked 2026-11-26): disallows /web/, /tinyurl/, /c/portal/login, /login/,
// /*?doAsUserId= and asks `Crawl-delay: 10`. The paths used here are allowed; the CLI waits
// 10 s between its own requests. Terms of use: no clause on automated access.

export const BASE = "https://www.hays.at"
export const AUSTRIA = "8BB21453-D8A8-11D3-AFB2-00105AB00B48" // Hays country id (country facet)
export const PAGE_SIZE = 20
export const MAX_PAGES = 6 // safety cap: ~4 pages for Austria today

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; hays-cli/1.0)"

export interface Fetched {
  html: string
  url: string // final URL after redirects
}

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404 or the "job not available" page. */
export async function htmlFetch(url: string): Promise<Fetched | null> {
  const maxRetries = 6
  let delay = 1000
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9", Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8" },
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
    if (response.status === 404) return null
    if (!response.ok) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    const finalUrl = response.url || url
    if (/\/jobsuche\/stelle-nicht-verfuegbar/.test(finalUrl)) return null
    return { html: await response.text(), url: finalUrl }
  }
  throw new Error("Request failed after max retries")
}

/** Pause between requests: robots.txt asks Crawl-delay 10. Overridable for tests (HAYS_CLI_DELAY_MS=0). */
export function politeDelay(): Promise<void> {
  const ms = Number(process.env.HAYS_CLI_DELAY_MS ?? 10000)
  return new Promise((r) => setTimeout(r, Number.isFinite(ms) && ms > 0 ? ms : 0))
}

export interface JobCard {
  id: string // "<num>-<n>", e.g. "903672-1" (Hays reference number 903672/1)
  title: string
  company: null // the client is not named
  recruiter: "Hays"
  location: string | null
  date: string | null // YYYY-MM-DD, Vienna calendar day of "Online since"
  url: string
  employmentType: string | null // "Permanent employment with our customer", "Contracting", …
  homeOffice: null
  salary: null // detail only
  summary: string | null
}

export interface JobDetail extends Omit<JobCard, "salary"> {
  salary: string | null
  industry: string | null
  startDate: string | null
  description: string | null
  applyUrl: null // applying goes through Hays on the posting page
  validThrough: null // the JSON-LD validThrough is a placeholder two years ahead: not used
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

// ---------------------------------------------------------------- Hays parsing

const MONTHS: Record<string, string> = {
  jan: "01", feb: "02", mar: "03", apr: "04", may: "05", jun: "06", jul: "07", aug: "08", sep: "09", oct: "10", nov: "11", dec: "12",
}

/**
 * "25.11.26" (sent with Accept-Language) or "Tue Nov 24 15:11:24 CET 2026" (without) ->
 * "2026-11-24"; the site prints Vienna local dates. null if unparseable.
 */
export function onlineSince(s: string | null): string | null {
  const short = (s ?? "").trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$/)
  if (short) {
    const [, d, mo, y] = short
    if (Number(mo) < 1 || Number(mo) > 12 || Number(d) < 1 || Number(d) > 31) return null
    return `${y.length === 2 ? "20" + y : y}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}`
  }
  const m = (s ?? "").trim().match(/^[A-Z][a-z]{2} ([A-Z][a-z]{2}) (\d{1,2}) \d{2}:\d{2}:\d{2} [A-Z]{3,4} (\d{4})$/)
  const mm = m ? MONTHS[m[1].toLowerCase()] : undefined
  return m && mm ? `${m[3]}-${mm}-${m[2].padStart(2, "0")}` : null
}

/** "903672/1" | "903672-1" -> {num, n}; null otherwise. */
export function splitRef(ref: string): { num: string; n: string } | null {
  const m = ref.trim().match(/^(\d{4,8})[/-](\d{1,3})$/)
  return m ? { num: m[1], n: m[2] } : null
}

export function jobUrl(num: string, n: string): string {
  return `${BASE}/jobsuche/stellenangebote-jobs-detail?prospectNr=${num}/${n}`
}

export function searchUrl(page: number, query: string | undefined): string {
  return `${BASE}/en/jobsearch/job-offers/c/Austria/${AUSTRIA}/p/${page}?q=${encodeURIComponent(query ?? "")}`
}

function infoText(chunk: string, kind: string): string | null {
  const m = chunk.match(new RegExp(`search__result__job__attribute__${kind}[^"]*"[^>]*>[\\s\\S]*?<div class="info-text">([\\s\\S]*?)</div>`))
  return m ? clean(m[1]) : null
}

export interface SearchPage {
  cards: JobCard[]
  total: number | null
}

/** Split into search__result chunks and parse each on its own. */
export function parseSearchPage(html: string): SearchPage {
  const cards: JobCard[] = []
  const seen = new Set<string>()
  const chunks = html.split(/<div class="search__result border-radius-10">/).slice(1)
  for (const raw of chunks) {
    try {
      const chunk = visibleHtml(raw)
      const a = chunk.match(/<a class="search__result__link"[^>]*href="https:\/\/www\.hays\.at\/jobsuche\/stellenangebote-jobs-detail-[^"]*?-(\d{4,8})\/(\d{1,3})"/)
      if (!a) continue
      const [, num, n] = a
      const id = `${num}-${n}`
      const t = chunk.match(/<h4 class="search__result__header__title">([\s\S]*?)<\/h4>/)
      const title = t ? clean(t[1]) : null
      if (!title || seen.has(id)) continue
      seen.add(id)
      const teaser = chunk.match(/<div class="search__result__teaser">([\s\S]*?)<\/div>\s*<\/div>/)
      const since = chunk.match(/Online since:\s*([^<]+?)\s*</)
      const summary = teaser ? clean(teaser[1]) : null
      cards.push({
        id,
        title,
        company: null,
        recruiter: "Hays",
        location: infoText(chunk, "location"),
        date: onlineSince(since ? since[1] : null),
        url: jobUrl(num, n),
        employmentType: infoText(chunk, "type"),
        homeOffice: null,
        salary: null,
        summary: summary && summary.length > 600 ? summary.slice(0, 600) + "…" : summary,
      })
    } catch {
      continue
    }
  }
  const total = html.match(/<span id ?="totalJobs"\s*>\s*Show ([\d.,]+) results?\s*</)
  return { cards, total: total ? Number(total[1].replace(/[.,]/g, "")) : cards.length === 0 ? 0 : null }
}

const INDUSTRY = /^[\p{L}][\p{L} &,.\/()-]{1,60}$/u

interface LdPosting {
  datePosted?: string
  employmentType?: string[]
  industry?: string
}

/** The JobPosting JSON-LD: only short, pattern-checked fields are read (never its text blobs). */
export function parseLd(html: string): { date: string | null; employment: string[]; industry: string | null } {
  for (const m of html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) {
    let data: LdPosting & { "@type"?: string }
    try {
      data = JSON.parse(m[1])
    } catch {
      continue
    }
    if (!data || data["@type"] !== "JobPosting") continue
    const employment = Array.isArray(data.employmentType) ? data.employmentType.filter((e) => /^[A-Z_]{3,20}$/.test(String(e))) : []
    const industry = typeof data.industry === "string" && INDUSTRY.test(data.industry.trim()) ? data.industry.trim() : null
    return { date: viennaDate(data.datePosted ?? null), employment, industry }
  }
  return { date: null, employment: [], industry: null }
}

/** The posting's sections, in page order: [{title, text}]. */
export function parseSections(html: string): { title: string; text: string }[] {
  const out: { title: string; text: string }[] = []
  const parts = html.split(/<div class="h-job-detail__listing-header hays__job__detail__listing__header">/).slice(1)
  for (const part of parts) {
    const t = part.match(/<h3 class="h-job-detail__listing-title"[^>]*>([\s\S]*?)<\/h3>/)
    const body = part.match(/<div class="h-job-detail__listing-body\s+h-text">([\s\S]*?)<\/div>\s*<\/div>/)
    const title = t ? clean(t[1]) : null
    const text = body ? (cleanBlock(body[1])?.replace(/\n{2,}(?=• )/g, "\n") ?? null) : null
    if (title && text) out.push({ title, text })
  }
  return out
}

export function parseJobDetail(html: string, ref: { num: string; n: string }): JobDetail {
  const h1 = html.match(/<h1 class="h-arrow-header-content-template__headline[^"]*">([\s\S]*?)<\/h1>/)
  const title = h1 ? clean(h1[1]) : null
  if (!title) throw new Error("detail page has no h1 headline (markup changed?)")
  const meta = [...html.matchAll(/<div class="info-text h-job-detail__meta-item h-job-detail__location">([\s\S]*?)<\/div>/g)]
    .map((m) => clean(visibleHtml(m[1])))
    .filter((v): v is string => !!v)
  const start = meta.find((v) => /^Start date:/i.test(v)) ?? null
  const rest = meta.filter((v) => v !== start)
  const ld = parseLd(html)
  const sections = parseSections(html)
  const salary = sections.find((s) => /^(Salary information|Gehaltsinformation|Gehalt)/i.test(s.title))
  const intro = `Posted by Hays (recruitment agency) for a client${ld.industry ? ` in: ${ld.industry}` : ""}; the employer is not named.`
  return {
    id: `${ref.num}-${ref.n}`,
    title,
    company: null,
    recruiter: "Hays",
    location: rest[1] ?? null,
    date: ld.date,
    url: jobUrl(ref.num, ref.n),
    employmentType: [rest[0], ld.employment.length ? `(${ld.employment.join(", ")})` : null].filter(Boolean).join(" ") || null,
    homeOffice: null,
    salary: salary ? salary.text.replace(/^•\s*/, "").replace(/\s+/g, " ").slice(0, 300) : null,
    summary: null,
    industry: ld.industry,
    startDate: start ? start.replace(/^Start date:\s*/i, "") || null : null,
    description: [intro, ...sections.map((s) => `${s.title}\n${s.text}`)].join("\n\n"),
    applyUrl: null,
    validThrough: null,
    isActive: true, // closed openings redirect to "Jobangebot nicht verfügbar" (NOT_FOUND)
  }
}
