// Data source: jobs.derstandard.at (DER STANDARD Jobs, Austria) public pages. No authentication.
//
// Search: GET https://jobs.derstandard.at/suche/<location-slug>/<keywords> (HTML, Next.js).
// The page embeds its GraphQL result in an Apollo SSR transport script:
//   (window[Symbol.for("ApolloSSRDataTransport")] ??= []).push({"rehydrate":{"<id>":{"data":{"jobListings":{...}}}}})
// The object is JavaScript, not JSON (it contains bare `undefined`), so it is read with a
// string-aware scanner that maps `undefined` to `null` outside strings.
// 20 results per page, relevance order; "load more" is client-side GraphQL (not used), and
// `?page=` is ignored by the server: only page 1 is reachable through public HTML.
//
// Detail: GET https://jobs.derstandard.at/detail/<uuid> (HTML) with a schema.org JobPosting
// JSON-LD block (title, hiringOrganization, jobLocation, datePosted, validThrough,
// employmentType, baseSalary, description HTML).
//
// robots.txt (checked 2026-11-25): `User-agent: *` disallows only /wp-admin/,
// /jobsuche/c/job/ and /jobsuche/tracking/. AGB VI reserves commercial text-and-data mining.

export const BASE = "https://jobs.derstandard.at"

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; derstandard-cli/1.0)"

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404. */
async function fetchWithBackoff(url: string): Promise<Response | null> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": UA,
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
        Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
      },
      redirect: "follow",
      signal: AbortSignal.timeout(30000),
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((r) => setTimeout(r, delay + jitter))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 404) return null
    if (!response.ok) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    return response
  }
  throw new Error("Request failed after max retries")
}

/** Page HTML ("" on 404). */
export async function htmlFetch(url: string): Promise<string> {
  const r = await fetchWithBackoff(url)
  return r ? r.text() : ""
}

export interface JobCard {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null // YYYY-MM-DD, Vienna calendar date of the portal's displayDate
  url: string
  employmentType: string | null
  homeOffice: boolean | null
  salary: string | null
  summary: string | null
  tags: string[]
}

export interface JobDetail {
  id: string
  title: string
  company: string | null
  companyWebsite: string | null
  location: string | null
  date: string | null
  validThrough: string | null
  url: string
  applyUrl: string | null
  employmentType: string | null
  homeOffice: boolean | null
  salary: string | null
  description: string | null
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

// ---------------------------------------------------------------- parsing

/**
 * Read the JavaScript object literal starting at the first "{" after `start`, string-aware,
 * turning bare `undefined` (outside strings) into `null`, then JSON.parse it. null if not valid.
 */
export function extractJsObject(text: string, start: number): unknown | null {
  const i0 = text.indexOf("{", start)
  if (i0 === -1) return null
  let depth = 0
  let inStr = false
  let esc = false
  const out: string[] = []
  for (let i = i0; i < text.length; i++) {
    const c = text[i]
    if (inStr) {
      out.push(c)
      if (esc) esc = false
      else if (c === "\\") esc = true
      else if (c === '"') inStr = false
      continue
    }
    if (c === '"') {
      inStr = true
      out.push(c)
      continue
    }
    if (c === "u" && text.startsWith("undefined", i) && !/[\w$]/.test(text[i - 1] ?? "") && !/[\w$]/.test(text[i + 9] ?? "")) {
      out.push("null")
      i += 8
      continue
    }
    out.push(c)
    if (c === "{") depth++
    else if (c === "}") {
      depth--
      if (depth === 0) {
        try {
          return JSON.parse(out.join(""))
        } catch {
          return null
        }
      }
    }
  }
  return null
}

const APOLLO_MARKER = 'ApolloSSRDataTransport")] ??= []).push('

/** Every Apollo SSR rehydrate payload of a page, in order (malformed ones skipped). */
export function apolloPayloads(html: string): Record<string, any>[] {
  const out: Record<string, any>[] = []
  let at = html.indexOf(APOLLO_MARKER)
  while (at !== -1) {
    const obj = extractJsObject(html, at + APOLLO_MARKER.length)
    if (obj && typeof obj === "object") out.push(obj as Record<string, any>)
    at = html.indexOf(APOLLO_MARKER, at + APOLLO_MARKER.length)
  }
  return out
}

export function extractJobPostingLd(html: string): Record<string, unknown> | null {
  const re = /<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    try {
      const o = JSON.parse(m[1])
      const list = Array.isArray(o) ? o : [o]
      for (const item of list) {
        if (item && typeof item === "object" && item["@type"] === "JobPosting") return item
      }
    } catch {
      // one malformed block must not hide the others
    }
  }
  return null
}

type Obj = Record<string, any>
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null)

export interface SearchPage {
  total: number | null
  hasMore: boolean
  cards: JobCard[]
}

/** The first `jobListings` connection found in the page's Apollo payloads. */
export function findJobListings(html: string): Obj | null {
  for (const payload of apolloPayloads(html)) {
    for (const entry of Object.values((payload.rehydrate ?? {}) as Obj)) {
      const jl = (entry as Obj)?.data?.jobListings
      if (jl && typeof jl === "object" && Array.isArray(jl.edges)) return jl
    }
  }
  return null
}

const INTERVAL: Record<string, string> = { YEARLY: "jährlich", MONTHLY: "monatlich", HOURLY: "pro Stunde", WEEKLY: "wöchentlich", DAILY: "täglich" }

/** "ab 83.000 € jährlich" from the portal's minimum salary and interval; null when absent. */
export function formatSalary(amount: unknown, interval: unknown): string | null {
  if (typeof amount !== "number" || !Number.isFinite(amount) || amount <= 0) return null
  const n = new Intl.NumberFormat("de-AT", { maximumFractionDigits: 0 }).format(amount).replace(/\s/g, ".")
  const per = typeof interval === "string" ? INTERVAL[interval] : undefined
  return `ab ${n} €${per ? " " + per : ""}`
}

const EMPLOYMENT: Record<string, string> = {
  FULL_TIME: "Vollzeit", PART_TIME: "Teilzeit", CONTRACTOR: "Freier Dienstvertrag / Werkvertrag", TEMPORARY: "Befristet",
  INTERN: "Praktikum", VOLUNTEER: "Ehrenamt", PER_DIEM: "Tageweise", OTHER: "Sonstige",
  "Full-time": "Vollzeit", "Part-time": "Teilzeit",
}

function employment(v: unknown): string | null {
  const list = Array.isArray(v) ? v : typeof v === "string" ? [v] : []
  const names = list.map((x) => (typeof x === "string" ? EMPLOYMENT[x] ?? clean(x) : null)).filter((x): x is string => !!x)
  return names.length ? [...new Set(names)].join(", ") : null
}

const HOME_OFFICE = /^(home[- ]?office|remote|homeoffice)$/i

/**
 * Parse a search-results page. Each edge is parsed independently so one malformed item
 * cannot break the rest. Throws when the page carries no jobListings at all (markup changed).
 */
export function parseSearchPage(html: string): SearchPage {
  const jl = findJobListings(html)
  if (!jl) throw new Error("search page has no jobListings payload (markup or endpoint changed?)")
  const cards: JobCard[] = []
  for (const edge of jl.edges as unknown[]) {
    try {
      const n: Obj | undefined = (edge as Obj)?.node
      if (!n) continue
      const id = str(n.id)
      const title = clean(n.title)
      if (!id || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) || !title) continue
      const raw: string[] = Array.isArray(n.jobLocationsRaw) ? n.jobLocationsRaw.map((x: unknown) => clean(x as string)).filter((x: string | null): x is string => !!x) : []
      const places = raw.filter((x) => !HOME_OFFICE.test(x))
      const benefits: unknown[] = Array.isArray(n.benefits) ? n.benefits : []
      const home = benefits.includes("home_office") || raw.some((x) => HOME_OFFICE.test(x))
      cards.push({
        id: id.toLowerCase(),
        title,
        company: clean(n.hiringOrganization?.name) ?? clean(n.brandOrganization?.name),
        location: places.length ? [...new Set(places)].join(", ") : null,
        date: viennaDate(str(n.displayDate)),
        url: `${BASE}/detail/${id.toLowerCase()}`,
        employmentType: employment(n.employmentTypes),
        homeOffice: home ? true : null,
        salary: formatSalary(n.baseSalary, n.salaryInterval),
        summary: clean(n.jobSummary),
        tags: Array.isArray(n.tags) ? n.tags.map((t: unknown) => clean(t as string)).filter((t: string | null): t is string => !!t).slice(0, 12) : [],
      })
    } catch {
      continue
    }
  }
  const total = typeof jl.totalEntries === "number" ? jl.totalEntries : null
  return { total, hasMore: jl.pageInfo?.hasNextPage === true, cards }
}

function ldLocation(ld: Obj | null): string | null {
  const locs = ld?.jobLocation
  const list = Array.isArray(locs) ? locs : locs ? [locs] : []
  const names = list
    .map((l: Obj) => clean(l?.address?.addressLocality))
    .filter((x: string | null): x is string => !!x && !HOME_OFFICE.test(x))
  return names.length ? [...new Set(names)].join(", ") : null
}

function ldSalary(ld: Obj | null): string | null {
  const v = ld?.baseSalary?.value
  const amount = typeof v?.value === "number" ? v.value : typeof v?.minValue === "number" ? v.minValue : null
  const unit = str(v?.unitText)
  const map: Record<string, string> = { YEAR: "YEARLY", MONTH: "MONTHLY", HOUR: "HOURLY", WEEK: "WEEKLY", DAY: "DAILY" }
  return formatSalary(amount, unit ? map[unit.toUpperCase()] : undefined)
}

/** Parse a detail page from its JSON-LD JobPosting. */
export function parseJobDetail(html: string, id: string, today: string = viennaToday()): JobDetail {
  const ld = extractJobPostingLd(html) as Obj | null
  if (!ld) throw new Error("detail page has no JobPosting JSON-LD (markup changed?)")
  const benefits = str(ld.jobBenefits) ?? ""
  const validThrough = viennaDate(str(ld.validThrough))
  return {
    id,
    title: clean(ld.title as string) ?? "(untitled)",
    company: clean(ld.hiringOrganization?.name),
    companyWebsite: null, // the page carries the employer's site only as free text
    location: ldLocation(ld),
    date: viennaDate(str(ld.datePosted)),
    validThrough,
    url: `${BASE}/detail/${id}`,
    applyUrl: null, // no structured apply URL: the "Jetzt bewerben" button is client-side
    employmentType: employment(ld.employmentType),
    homeOffice: /home\s*-?\s*office|remote/i.test(benefits) ? true : null,
    salary: ldSalary(ld),
    description: cleanBlock(str(ld.description)),
    isActive: !(validThrough && validThrough < today),
  }
}
