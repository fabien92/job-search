// Data source: UNIDO careers site, careers.unido.org (SAP SuccessFactors Career Site Builder).
// Public pages, no authentication.
//
// Search: GET https://careers.unido.org/search/?q=<keywords>&locationsearch=<location> (HTML).
// One <tr class="data-row"> per opening: title link /job/<slug>/<id>/, location, category
// (colDepartment), grade (colFacility), application deadline (colShifttype, "30-Nov-2026").
// "Results 1 – 12 of 12" (span.paginationLabel) gives the total. No posting date in the list.
// The whole board holds about 20 openings (2026-11-25), so everything fits on one page.
//
// Detail: GET https://careers.unido.org/job/<any-slug>/<id>/ (HTML) with schema.org microdata:
// itemprop title, streetAddress, datePosted / validThrough ("Mon Nov 09 00:00:00 UTC 2026"),
// and the description in <span class="jobdescription">.
//
// robots.txt (checked 2026-11-25): `User-agent: *` disallows /applybutton/, /talentcommunity/,
// /preapply/, /services/, /emailsubscribe/ and a few account paths; /search/ and /job/ are allowed.

export const BASE = "https://careers.unido.org"

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; unido-cli/1.0)"

/** Fetch with exponential backoff on 429/5xx. Returns "" on a 404 or an error-page redirect. */
export async function htmlFetch(url: string): Promise<string> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9", Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8" },
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
    if (response.status === 404) return ""
    if (!response.ok) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    if (/\/errorpage\//.test(response.url)) return "" // unknown id: SuccessFactors redirects to its error page
    return response.text()
  }
  throw new Error("Request failed after max retries")
}

export interface JobCard {
  id: string
  title: string
  company: string
  location: string | null
  date: string | null // not in the list: filled by detail
  deadline: string | null // YYYY-MM-DD
  url: string
  grade: string | null // e.g. "P3", "G5", "NOB"
  category: string | null // e.g. "General Service", "Professional"
  employmentType: string | null // detail only, e.g. "Staff-Full-time"
  homeOffice: null
  salary: string | null // detail only, e.g. "104,934 USD net per year (indicative minimum)"
  summary: null
}

export interface JobDetail extends Omit<JobCard, "summary"> {
  description: string | null
  applyUrl: null // applying goes through the posting page ("Apply now")
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

// ---------------------------------------------------------------- UNIDO parsing

const MONTHS: Record<string, string> = {
  jan: "01", feb: "02", mar: "03", apr: "04", may: "05", jun: "06", jul: "07", aug: "08", sep: "09", oct: "10", nov: "11", dec: "12",
}

/** "30-Nov-2026" -> "2026-11-30"; null if unparseable. */
export function listDate(s: string | null): string | null {
  const m = (s ?? "").trim().match(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/)
  const mm = m ? MONTHS[m[2].toLowerCase()] : undefined
  return m && mm ? `${m[3]}-${mm}-${m[1].padStart(2, "0")}` : null
}

/** "Mon Nov 30 23:00:00 UTC 2026" -> Date (UTC); null if unparseable. */
export function microdataInstant(s: string | null): Date | null {
  const m = (s ?? "").trim().match(/^[A-Za-z]{3} ([A-Za-z]{3}) (\d{1,2}) (\d{2}:\d{2}:\d{2}) UTC (\d{4})$/)
  const mm = m ? MONTHS[m[1].toLowerCase()] : undefined
  if (!m || !mm) return null
  const d = new Date(`${m[4]}-${mm}-${m[2].padStart(2, "0")}T${m[3]}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

export function jobUrl(id: string, slug = "job"): string {
  return `${BASE}/job/${slug}/${id}/`
}

const cellText = (chunk: string, cls: string): string | null => {
  const m = chunk.match(new RegExp(`<span class="${cls}"[^>]*>([\\s\\S]*?)</span>`))
  return m ? clean(m[1]) : null
}

export interface SearchPage {
  cards: JobCard[]
  total: number | null
}

/** Split into <tr class="data-row"> chunks and parse each on its own. */
export function parseSearchPage(html: string): SearchPage {
  const cards: JobCard[] = []
  const seen = new Set<string>()
  const chunks = html.split(/<tr class="data-row"/).slice(1)
  for (const raw of chunks) {
    try {
      const chunk = visibleHtml("<tr" + raw.split(/<\/tr>/)[0])
      const a = chunk.match(/<a\s[^>]*href="\/job\/([^"/]+)\/(\d+)\/"[^>]*>([\s\S]*?)<\/a>/)
      if (!a) continue
      const [, slug, id, rawTitle] = a
      const title = clean(rawTitle)
      if (!title || seen.has(id)) continue
      seen.add(id)
      const loc = chunk.match(/<td class="colLocation[^"]*"[^>]*>([\s\S]*?)<\/td>/)
      cards.push({
        id,
        title,
        company: "UNIDO",
        location: loc ? clean(loc[1]) : cellText(chunk, "jobLocation"),
        date: null,
        deadline: listDate(cellText(chunk, "jobShifttype")),
        url: jobUrl(id, slug),
        grade: cellText(chunk, "jobFacility"),
        category: cellText(chunk, "jobDepartment"),
        employmentType: null,
        homeOffice: null,
        salary: null,
        summary: null,
      })
    } catch {
      continue
    }
  }
  const label = html.match(/class="paginationLabel"[^>]*>([\s\S]*?)<\/span>/)
  const of = label ? (clean(label[1]) ?? "").match(/of\s+([\d.,]+)/) : null
  return { cards, total: of ? Number(of[1].replace(/[.,]/g, "")) : null }
}

/** Inner HTML of the first <span class="jobdescription">, balanced on nested spans. */
export function descriptionHtml(html: string): string | null {
  const start = html.indexOf('<span class="jobdescription">')
  if (start === -1) return null
  const from = start + '<span class="jobdescription">'.length
  const re = /<(\/?)span\b[^>]*>/gi
  re.lastIndex = from
  let depth = 1
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    depth += m[1] ? -1 : 1
    if (depth === 0) return html.slice(from, m.index)
  }
  return html.slice(from)
}

const prop = (html: string, name: string): string | null => {
  const m = html.match(new RegExp(`<meta itemprop="${name}" content="([^"]*)"`))
  return m ? decodeHtmlEntities(m[1]).trim() || null : null
}

export function parseJobDetail(html: string, id: string, now: Date = new Date()): JobDetail {
  const t = html.match(/<span[^>]*itemprop="title"[^>]*>([\s\S]*?)<\/span>/)
  const title = t ? clean(t[1]) : null
  if (!title) throw new Error("detail page has no itemprop=title (markup changed?)")
  const posted = microdataInstant(prop(html, "datePosted"))
  const until = microdataInstant(prop(html, "validThrough"))
  const desc = descriptionHtml(html)
  const text = cleanBlock(desc)
  const grade = text?.match(/Grade:\s*([A-Z]{1,3}-?\d?[A-Z]?)\b/)
  const pay = text?.match(/Indicative Minimum Net Annual Salary:\s*([\d.,]+\s*[A-Z]{3})/)
  const employment = text?.match(/Employment Type:\s*([^\n]+?)\s*(?:\n|$)/)
  const category = text?.match(/Category:\s*([^\n]+?)\s*(?:\n|$)/)
  const canonical = html.match(/<link rel="canonical" href="https:\/\/careers\.unido\.org\/job\/([^"/]+)\/\d+\/"/)
  return {
    id,
    title,
    company: "UNIDO",
    location: prop(html, "streetAddress"),
    date: posted ? posted.toISOString().slice(0, 10) : null,
    deadline: until ? until.toISOString().slice(0, 10) : null,
    url: jobUrl(id, canonical ? canonical[1] : "job"),
    grade: grade ? grade[1] : null,
    category: category ? category[1] : null,
    employmentType: employment ? employment[1] : null,
    homeOffice: null,
    salary: pay ? `${pay[1]} net per year (indicative minimum)` : null,
    description: text,
    applyUrl: null,
    validThrough: until ? until.toISOString().slice(0, 10) : null,
    isActive: until ? until.getTime() >= now.getTime() : true,
  }
}
