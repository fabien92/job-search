// Data source: OSCE vacancies portal, vacancies.osce.org ("Social Sourcing" job board; applying
// goes through talent.osce.org). Public pages, no authentication.
//
// Search: GET https://vacancies.osce.org/jobs/search/ redirects to a fresh saved search
// /jobs/search/<jsid> (HTML, 10 openings per page); further pages are /jobs/search/<jsid>/page<n>.
// One <div id="job_list_<id>" class="job_list_row …"> per opening: title link /jobs/<slug>-<id>,
// span.location ("SEC - OSCE Secretariat, Vienna"), span.category, p.jlr_description (snippet).
// span.total_results gives the total. No dates, grade or contract type in the list.
// The whole board holds about 45 openings (2026-11-25), i.e. about 5 pages.
//
// Detail: GET https://vacancies.osce.org/jobs/<id> (the slug is optional; unknown id -> 404).
// h1.title, h4.primary_location, the description in div.job_description, then an
// "Additional Information" list of <label>Name: value</label> (Grade, Job Type, Issue Date,
// Closing Date…). That list sits in a display:none block, so only whitelisted labels are read,
// and each value must match a strict pattern; it never becomes free text.
//
// robots.txt (checked 2026-11-25): `User-agent: *` with an empty `Disallow:` (nothing blocked).

export const BASE = "https://vacancies.osce.org"
export const PAGE_SIZE = 10
export const MAX_PAGES = 10 // safety cap: ~5 pages today

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; osce-cli/1.0)"

export interface Fetched {
  html: string
  url: string // final URL after redirects
}

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404. */
export async function htmlFetch(url: string): Promise<Fetched | null> {
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
    if (response.status === 404) return null
    if (!response.ok) throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    return { html: await response.text(), url: response.url || url }
  }
  throw new Error("Request failed after max retries")
}

/** Pause between page requests (keep the load on the portal low). Overridable for tests. */
export function politeDelay(): Promise<void> {
  const ms = Number(process.env.OSCE_CLI_DELAY_MS ?? 1500)
  return new Promise((r) => setTimeout(r, Number.isFinite(ms) && ms > 0 ? ms : 0))
}

export interface JobCard {
  id: string
  title: string
  company: string
  location: string | null
  date: string | null // not in the list: filled by detail (Issue Date)
  deadline: string | null // not in the list: filled by detail (Closing Date)
  url: string
  grade: string | null // detail only, e.g. "P3", "S2", "G4"
  category: string | null
  jobType: string | null // detail only: Contracted | Seconded | Intern | Consultant
  employmentType: string | null // detail only, e.g. "Local Contracted"
  homeOffice: null
  salary: string | null // detail only
  summary: string | null
}

export interface JobDetail extends JobCard {
  issuedBy: string | null
  requisitionId: string | null
  jobLevel: string | null
  employeeStatus: string | null
  schedule: string | null
  description: string | null
  applyUrl: null // applying goes through the posting page ("Apply for Job" -> talent.osce.org)
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

// ---------------------------------------------------------------- OSCE parsing

const MONTHS: Record<string, string> = {
  jan: "01", feb: "02", mar: "03", apr: "04", may: "05", jun: "06", jul: "07", aug: "08", sep: "09", oct: "10", nov: "11", dec: "12",
}

/** "Dec 11, 2026" -> "2026-12-11"; null if unparseable. */
export function labelDate(s: string | null): string | null {
  const m = (s ?? "").trim().match(/^([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4})$/)
  const mm = m ? MONTHS[m[1].toLowerCase()] : undefined
  return m && mm ? `${m[3]}-${mm}-${m[2].padStart(2, "0")}` : null
}

export function jobUrl(id: string, slug?: string): string {
  return slug ? `${BASE}/jobs/${slug}-${id}` : `${BASE}/jobs/${id}`
}

export interface SearchPage {
  cards: JobCard[]
  total: number | null
  currentPage: number | null
}

/** Split into job_list_row chunks and parse each on its own. */
export function parseSearchPage(html: string): SearchPage {
  const cards: JobCard[] = []
  const seen = new Set<string>()
  const chunks = html.split(/<div id="job_list_(?=\d)/).slice(1)
  for (const raw of chunks) {
    try {
      const chunk = visibleHtml(raw.split(/<!-- jlr_content -->/)[0])
      const a = chunk.match(/<a href="https:\/\/vacancies\.osce\.org\/jobs\/([a-z0-9%-]+?)-(\d{1,8})" class="job_link[^"]*">([\s\S]*?)<\/a>/i)
      if (!a) continue
      const [, slug, id, rawTitle] = a
      const title = clean(rawTitle)
      if (!title || seen.has(id)) continue
      seen.add(id)
      const loc = chunk.match(/<span class="location">([\s\S]*?)<\/span>/)
      const cat = chunk.match(/<span class="category">([\s\S]*?)<\/span>/)
      const snip = chunk.match(/<p class="jlr_description">([\s\S]*?)<\/p>/)
      cards.push({
        id,
        title,
        company: "OSCE",
        location: loc ? clean(loc[1]) : null,
        date: null,
        deadline: null,
        url: jobUrl(id, slug),
        grade: null,
        category: cat ? clean(cat[1]) : null,
        jobType: null,
        employmentType: null,
        homeOffice: null,
        salary: null,
        summary: snip ? clean(snip[1]) : null,
      })
    } catch {
      continue
    }
  }
  const total = html.match(/<span class="total_results">\s*([\d.,]+)\s*<\/span>/)
  const cur = html.match(/id="jPaginateCurrPage"[^>]*>\s*(\d+)\s*</)
  return { cards, total: total ? Number(total[1].replace(/[.,]/g, "")) : null, currentPage: cur ? Number(cur[1]) : null }
}

/** Saved-search id from the URL the search redirect landed on (/jobs/search/<jsid>[/page<n>]). */
export function searchId(url: string): string | null {
  const m = url.match(/^https:\/\/vacancies\.osce\.org\/jobs\/search\/(\d{1,12})(?:\/page\d+)?\/?$/)
  return m ? m[1] : null
}

/**
 * The "Additional Information" labels. The block is display:none on the page, so each value
 * is accepted only if it matches its pattern: anything else (free text, instructions) is dropped.
 */
const LABELS: Record<string, { key: keyof Meta; re: RegExp }> = {
  "Issued by": { key: "issuedBy", re: /^[A-Za-z][A-Za-z ,.()'’&\/-]{1,90}$/ },
  "Requisition ID": { key: "requisitionId", re: /^[A-Z]{2,5}\d{3,8}$/ },
  "Contract Type": { key: "contractType", re: /^(?:Local|International) (?:Contracted|Secondment)$|^[A-Z][A-Za-z ]{2,40}$/ },
  "Grade": { key: "grade", re: /^(?:[A-Z]{1,3}\d{0,2}[A-Z]?|N\/A|Not applicable)$/ },
  "Job Level": { key: "jobLevel", re: /^[A-Z][A-Za-z /-]{2,40}$/ },
  "Job Type": { key: "jobType", re: /^(?:Contracted|Seconded|Intern|Consultant)$/ },
  "Location": { key: "location", re: /^[A-Z]{2,4} - [^<>{}]{3,100}$/ },
  "Issue Date": { key: "issueDate", re: /^[A-Za-z]{3}[a-z]*\.? \d{1,2}, \d{4}$/ },
  "Closing Date": { key: "closingDate", re: /^[A-Za-z]{3}[a-z]*\.? \d{1,2}, \d{4}$/ },
  "Employee Status": { key: "employeeStatus", re: /^[A-Z][A-Za-z -]{2,30}$/ },
  "Schedule": { key: "schedule", re: /^(?:Full|Part)-time$/ },
}

interface Meta {
  issuedBy?: string
  requisitionId?: string
  contractType?: string
  grade?: string
  jobLevel?: string
  jobType?: string
  location?: string
  issueDate?: string
  closingDate?: string
  employeeStatus?: string
  schedule?: string
}

export function parseMeta(html: string): Meta {
  const meta: Meta = {}
  for (const m of html.matchAll(/<li>\s*<label id="[A-Za-z0-9]{1,20}">([^<]{1,200})<\/label>\s*<\/li>/g)) {
    const text = decodeHtmlEntities(m[1]).replace(/\s+/g, " ").trim()
    const sep = text.indexOf(": ")
    if (sep === -1) continue
    const rule = LABELS[text.slice(0, sep)]
    const value = text.slice(sep + 2).trim()
    if (rule && rule.re.test(value) && meta[rule.key] === undefined) meta[rule.key] = value
  }
  return meta
}

/** Inner HTML of div.job_description, up to the hidden "Additional Information" block. */
export function descriptionHtml(html: string): string | null {
  const start = html.indexOf('<div class="job_description">')
  if (start === -1) return null
  const from = start + '<div class="job_description">'.length
  const ends = [html.indexOf("<!-- TEC-19749", from), html.indexOf('<div id="jJobInsideInfo"', from)].filter((i) => i !== -1)
  return html.slice(from, ends.length ? Math.min(...ends) : undefined)
}

const SECONDED_NOTE = "secondment: requires nomination by the candidate's own participating State"

/** "Monthly remuneration … is around EUR 4,160 (12 times a year)" -> "around EUR 4,160 per month (…)". */
export function salaryFrom(text: string | null): string | null {
  const m = (text ?? "").match(/[Mm]onthly remuneration[^.\n]{0,120}?\b((?:around |approximately )?(?:EUR|USD|€)\s?[\d.,]+|[\d.,]+\s?(?:EUR|USD))/)
  return m ? `${m[1].trim()} per month (as stated in the posting)` : null
}

export function parseJobDetail(html: string, id: string, now: Date = new Date()): JobDetail {
  const t = html.match(/<h1 class="title">([\s\S]*?)<\/h1>/)
  const title = t ? clean(t[1]) : null
  if (!title) throw new Error("detail page has no h1.title (markup changed?)")
  const meta = parseMeta(html)
  const loc = html.match(/<h4 class="primary_location">([\s\S]*?)<\/h4>/)
  const text = cleanBlock(descriptionHtml(html))
  const canonical = html.match(/<link rel="canonical" href="https:\/\/vacancies\.osce\.org\/jobs\/([a-z0-9%-]+?)-(\d{1,8})"/i)
  const closing = labelDate(meta.closingDate ?? null)
  let employmentType = meta.contractType ?? null
  if (meta.jobType === "Seconded") employmentType = `${employmentType ?? "Secondment"} (${SECONDED_NOTE})`
  return {
    id,
    title,
    company: "OSCE",
    // h4 carries a search icon glyph (span.loc_icon) before the duty station
    location: (loc ? clean(loc[1].replace(/<span class="loc_icon[^"]*">[\s\S]*?<\/span>/, "")) : null) ?? meta.location ?? null,
    date: labelDate(meta.issueDate ?? null),
    deadline: closing,
    url: canonical && canonical[2] === id ? jobUrl(id, canonical[1]) : jobUrl(id),
    grade: meta.grade ?? null,
    category: null,
    jobType: meta.jobType ?? null,
    employmentType,
    homeOffice: null,
    salary: salaryFrom(text),
    summary: null,
    issuedBy: meta.issuedBy ?? null,
    requisitionId: meta.requisitionId ?? null,
    jobLevel: meta.jobLevel ?? null,
    employeeStatus: meta.employeeStatus ?? null,
    schedule: meta.schedule ?? null,
    description: text,
    applyUrl: null,
    validThrough: closing,
    // Closing dates are inclusive: still open on that Vienna calendar day.
    isActive: closing ? closing >= viennaToday(now) : true,
  }
}
