// Data source: UN Careers (careers.un.org), the public job board of the UN Secretariat
// (Inspira): UN offices, departments, UNODC/UNOV, regional commissions, missions. No authentication.
//
// The site is an Angular app that reads a public JSON API:
//   Search: POST https://careers.un.org/api/public/opening/jo/list/filteredV2/en
//           body {filterConfig:{keyword?, ds?:[<location code>], span?:[<"1"|"7"|"30">]},
//                 pagination:{page:<0-based>, itemPerPage:<n>, sortBy:"startDate", sortDirection:-1}}
//           -> {status:1, data:{list:[...], count:<total>}}
//   Detail: GET  https://careers.un.org/api/public/opening/joV2/<jobId>/en -> {status:1, data:{...}}
// Never call PUT /api/public/opening/jo/<id>/<lang>: the site uses it to count a page view.
//
// robots.txt (checked 2026-11-25): none (the path serves the app shell), nothing disallowed.

export const SITE = "https://careers.un.org"
export const API = `${SITE}/api/public/opening`

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; un-careers-cli/1.0)"

/** JSON request with exponential backoff on 429/5xx. Returns null on a 404. */
export async function apiFetch(url: string, body?: unknown): Promise<any | null> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "User-Agent": UA,
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
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
    const json = await response.json().catch(() => null)
    if (!json || typeof json !== "object") throw new Error("API returned non-JSON")
    if (json.status !== 1) throw new Error(`API error: ${String(json.message ?? "unknown").slice(0, 200)}`)
    return json.data ?? null
  }
  throw new Error("Request failed after max retries")
}

export interface JobCard {
  id: string
  title: string
  company: string | null // "United Nations – <department / office>"
  location: string | null // duty station(s), e.g. "Vienna"
  date: string | null // YYYY-MM-DD (Vienna calendar date of the posting start)
  deadline: string | null // YYYY-MM-DD (Vienna calendar date of the closing time)
  url: string
  grade: string | null // e.g. "P-3", "G-6", "CON"
  category: string | null // e.g. "Professional and Higher Categories"
  contract: string | null // recruitment type, e.g. "Temporary Job Opening"
  jobFamily: string | null
  employmentType: null
  homeOffice: null
  salary: null
  summary: null
}

export interface JobDetail extends Omit<JobCard, "summary"> {
  description: string | null
  applyUrl: string | null
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

// ---------------------------------------------------------------- UN Careers parsing

type Obj = Record<string, any>
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null)

/** "NEW YORK" -> "New York", "ADDIS ABABA" -> "Addis Ababa"; mixed-case input is kept. */
export function titleCase(s: string): string {
  return s === s.toUpperCase() ? s.toLowerCase().replace(/(^|[\s\-/(])(\p{L})/gu, (_, p, c) => p + c.toUpperCase()) : s
}

/** Display names in English or German -> the portal's location code ("Job Locations" filter). */
const LOCATION_ALIASES: Record<string, string> = {
  wien: "VIENNA", vienna: "VIENNA", vienne: "VIENNA",
  bratislava: "BRATISLAVA", pressburg: "BRATISLAVA",
  budapest: "BUDAPEST",
  genf: "GENEVA", geneva: "GENEVA", "new york": "NEW YORK", bonn: "BONN", nairobi: "NAIROBI",
}

/** A location to the portal's code: alias table first, else the name upper-cased without accents. */
export function locationCode(location: string): string {
  const key = location.trim().toLowerCase().replace(/\s+/g, " ")
  return LOCATION_ALIASES[key] ?? key.normalize("NFKD").replace(/[̀-ͯ]/g, "").toUpperCase()
}

/** UN grade labels: "P3" -> "P-3", "G6" -> "G-6", "D1" -> "D-1"; others unchanged. */
export function grade(v: unknown): string | null {
  const s = str(v)
  if (!s) return null
  const m = s.match(/^(P|G|D|NO|FS|ASG|USG)\s*-?\s*(\d)$/i)
  return m ? `${m[1].toUpperCase()}-${m[2]}` : s
}

function stations(o: Obj): string[] {
  const list = Array.isArray(o.dutyStation) ? o.dutyStation : []
  return list.map((d: Obj) => str(d?.description)).filter((d: string | null): d is string => !!d).map(titleCase)
}

export function jobUrl(id: string): string {
  return `${SITE}/jobSearchDescription/${id}?language=en`
}

function card(o: Obj): JobCard | null {
  const id = o.jobId
  if (!(typeof id === "number" || (typeof id === "string" && /^\d+$/.test(id)))) return null
  const title = clean(str(o.postingTitle) ?? str(o.jobTitle))
  if (!title) return null
  const dept = clean(str(o.dept?.name))
  const where = stations(o)
  return {
    id: String(id),
    title,
    company: dept ? `United Nations – ${dept}` : "United Nations",
    location: where.length ? where.join(", ") : null,
    date: viennaDate(str(o.startDate)),
    deadline: viennaDate(str(o.endDate)),
    url: jobUrl(String(id)),
    grade: grade(o.jl?.name ?? o.jobLevel),
    category: clean(str(o.jc?.name)),
    contract: clean(str(o.recrttype?.name)),
    jobFamily: clean(str(o.jf?.Name ?? o.jf?.name)),
    employmentType: null,
    homeOffice: null,
    salary: null,
    summary: null,
  }
}

export interface SearchPage {
  cards: JobCard[]
  total: number | null
}

/** The `data` of a filteredV2 response; one malformed item never breaks the others. */
export function parseSearchData(data: unknown): SearchPage {
  const d = (data ?? {}) as Obj
  if (!Array.isArray(d.list)) throw new Error("search response has no data.list (API changed?)")
  const cards: JobCard[] = []
  for (const item of d.list) {
    try {
      const c = item && typeof item === "object" ? card(item) : null
      if (c) cards.push(c)
    } catch {
      continue
    }
  }
  return { cards, total: typeof d.count === "number" ? d.count : null }
}

const APPLY_HOST = /^inspira\.un\.org$/i

/** The `data` of a joV2 response. */
export function parseJobDetail(data: unknown, now: Date = new Date()): JobDetail {
  const o = (data ?? {}) as Obj
  const c = card(o)
  if (!c) throw new Error("detail response has no jobId/title (API changed?)")
  const { summary: _summary, ...rest } = c
  let applyUrl: string | null = null
  const raw = str(o.inspiraURL)
  if (raw) {
    try {
      const u = new URL(raw)
      if (u.protocol === "https:" && APPLY_HOST.test(u.hostname) && !u.username && !u.password) applyUrl = u.href
    } catch {}
  }
  const end = str(o.endDate)
  const endMs = end ? Date.parse(end) : NaN
  return {
    ...rest,
    description: cleanBlock(str(o.jobDescription)),
    applyUrl,
    validThrough: c.deadline,
    isActive: Number.isNaN(endMs) ? true : endMs >= now.getTime(),
  }
}
