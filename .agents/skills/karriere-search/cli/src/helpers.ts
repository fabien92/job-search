// Data source: karriere.at public pages. No authentication required.
//
// Search: GET https://www.karriere.at/jobs?keywords=..&locations=..&sort=date&page=N
// with `X-Requested-With: XMLHttpRequest` returns the page's view model as JSON
// ({ data: { jobsSearchList, jobsSearchform, ... } }) - the same object the
// HTML page embeds as `window.VUE_INITIAL_STATE`. Without that header the
// server ignores `page` and always renders page 1 as HTML.
//
// Detail: GET https://www.karriere.at/jobs/<id> (HTML). It carries a schema.org
// JobPosting JSON-LD block (exact datePosted, employmentType, salary,
// hiringOrganization.sameAs) and the VUE_INITIAL_STATE view model (description
// HTML, apply URL at the employer, home-office flag, salary text).
//
// robots.txt (checked 2026-11-23): `User-agent: *` with an empty Disallow.

export const BASE = "https://www.karriere.at"
export const SEARCH_URL = `${BASE}/jobs`

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; karriere-cli/1.0)"

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404. */
async function fetchWithBackoff(url: string, headers: Record<string, string>): Promise<Response | null> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": UA, "Accept-Language": "de-AT,de;q=0.9,en;q=0.8", ...headers },
      redirect: "follow",
      signal: AbortSignal.timeout(20000),
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

/** Search view model as JSON (null on 404). */
export async function jsonFetch(url: string): Promise<unknown | null> {
  const r = await fetchWithBackoff(url, { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" })
  if (!r) return null
  const text = await r.text()
  try {
    return JSON.parse(text)
  } catch {
    throw new Error("karriere.at returned a non-JSON search response (markup or endpoint changed?)")
  }
}

/** Detail page HTML ("" on 404). */
export async function htmlFetch(url: string): Promise<string> {
  const r = await fetchWithBackoff(url, { Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8" })
  return r ? r.text() : ""
}

export interface JobCard {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null // YYYY-MM-DD (derived from the portal's relative date)
  dateText: string | null // portal's own wording, e.g. "vor 3 Tagen veröffentlicht"
  url: string
  employmentType: string | null
  homeOffice: boolean | null
  salary: string | null
  summary: string | null
  pushed: boolean // sponsored placement: may fall outside the query or the age window
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
  jobLevel: string | null
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
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Vienna", year: "numeric", month: "2-digit", day: "2-digit" }).format(now)
}

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - days)
  return d.toISOString().slice(0, 10)
}

/**
 * The search list only carries a relative German date: "Heute veröffentlicht",
 * "Gestern veröffentlicht", "vor 3 Tagen veröffentlicht", or "13.11.2026".
 * Anything else maps to null - never guessed.
 */
export function parseRelativeDate(text: string | null | undefined, today: string = viennaToday()): string | null {
  if (typeof text !== "string") return null
  const t = text.trim().toLowerCase()
  if (t.startsWith("heute")) return today
  if (t.startsWith("gestern")) return shiftDays(today, 1)
  const rel = t.match(/^vor\s+(\d{1,3})\s+tag(?:en)?\b/)
  if (rel) return shiftDays(today, parseInt(rel[1], 10))
  const abs = t.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})\b/)
  if (abs) {
    const [, d, m, y] = abs
    const iso = `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`
    return Number.isNaN(Date.parse(`${iso}T00:00:00Z`)) ? null : iso
  }
  return null
}

export function ageInDays(iso: string | null, today: string = viennaToday()): number | null {
  if (!iso) return null
  const a = Date.parse(`${iso}T00:00:00Z`)
  const b = Date.parse(`${today}T00:00:00Z`)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.round((b - a) / 86400000)
}

// ---------------------------------------------------------------- parsing

/** Parse the first balanced JSON object starting at `start` (string-aware brace matching). */
export function extractJsonObject(text: string, start: number): unknown | null {
  const i0 = text.indexOf("{", start)
  if (i0 === -1) return null
  let depth = 0
  let inStr = false
  let esc = false
  for (let i = i0; i < text.length; i++) {
    const c = text[i]
    if (inStr) {
      if (esc) esc = false
      else if (c === "\\") esc = true
      else if (c === '"') inStr = false
      continue
    }
    if (c === '"') inStr = true
    else if (c === "{") depth++
    else if (c === "}") {
      depth--
      if (depth === 0) {
        try {
          return JSON.parse(text.slice(i0, i + 1))
        } catch {
          return null
        }
      }
    }
  }
  return null
}

const STATE_MARKER = "window.VUE_INITIAL_STATE"

export function extractInitialState(html: string): Record<string, unknown> | null {
  const at = html.indexOf(STATE_MARKER)
  if (at === -1) return null
  const obj = extractJsonObject(html, at + STATE_MARKER.length)
  return obj && typeof obj === "object" ? (obj as Record<string, unknown>) : null
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
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null)

export interface SearchPage {
  total: number | null
  hasMore: boolean
  cards: JobCard[]
}

/**
 * Parse the search view model. Accepts the XHR envelope ({ data: {...} }) or the
 * bare state object. Each item is parsed independently so one malformed item
 * cannot break the rest.
 */
export function parseSearchPayload(payload: unknown, today: string = viennaToday()): SearchPage {
  const root = (payload as Obj)?.data ?? payload
  const list: Obj = (root as Obj)?.jobsSearchList
  if (!list || typeof list !== "object") throw new Error("search response has no jobsSearchList (markup or endpoint changed?)")
  const rawTotal = list.jobsListHeader?.count
  const totalNum = typeof rawTotal === "number" ? rawTotal : typeof rawTotal === "string" ? Number(rawTotal.replace(/\D/g, "")) : NaN
  const items: unknown[] = Array.isArray(list.activeItems?.items) ? list.activeItems.items : []
  const cards: JobCard[] = []
  for (const item of items) {
    try {
      const j: Obj | undefined = (item as Obj)?.jobsItem
      if (!j) continue // disruptors, ads
      const id = str(String(j.id ?? ""))
      const title = clean(j.title)
      if (!id || !/^\d{5,}$/.test(id) || !title) continue
      const locations = Array.isArray(j.locations)
        ? j.locations.map((l: Obj) => clean(l?.name)).filter(Boolean).join(", ")
        : null
      const dateText = clean(j.date)
      cards.push({
        id,
        title,
        company: j.company?.isChiffre ? null : clean(j.company?.name),
        location: locations || null,
        date: parseRelativeDate(dateText, today),
        dateText,
        url: `${BASE}/jobs/${id}`,
        employmentType: clean(j.employmentTypes),
        homeOffice: bool(j.isHomeOffice),
        salary: clean(j.salary),
        summary: clean(j.summary),
        pushed: j.pushedJob === true,
      })
    } catch {
      continue
    }
  }
  return {
    total: Number.isFinite(totalNum) ? totalNum : null,
    hasMore: list.loadMoreJobsButton?.active === true,
    cards,
  }
}

function ldLocation(ld: Obj | null): string | null {
  const locs = ld?.jobLocation
  const list = Array.isArray(locs) ? locs : locs ? [locs] : []
  const names = list
    .map((l: Obj) => clean(l?.address?.addressLocality))
    .filter((x: string | null): x is string => !!x)
  return names.length ? [...new Set(names)].join(", ") : null
}

function isoDate(v: unknown): string | null {
  const s = str(v)
  const m = s?.match(/^(\d{4}-\d{2}-\d{2})/)
  return m ? m[1] : null
}

/** Parse a detail page from its JSON-LD and view model; either may be missing. */
export function parseJobDetail(html: string, id: string): JobDetail {
  const ld = extractJobPostingLd(html) as Obj | null
  const state = extractInitialState(html) as Obj | null
  const c: Obj = state?.jobDetailContent ?? {}
  const key: Obj = c.keyfactBox?.job ?? {}
  const header: Obj = c.jobHeader ?? {}
  const detail: Obj = c.jobDetail ?? {}

  const descHtml = str(c.jobContent?.text) ?? str(ld?.description)
  const employmentLd = Array.isArray(ld?.employmentType) ? ld!.employmentType.join(", ") : str(ld?.employmentType)
  const apply = str(c.applyAction?.applyButton?.applyUrl)
  let applyUrl: string | null = null
  if (apply) {
    try {
      const u = new URL(apply, BASE)
      if (u.protocol === "https:" || u.protocol === "http:") applyUrl = u.toString()
    } catch {
      applyUrl = null
    }
  }
  const website = str(ld?.hiringOrganization?.sameAs)

  return {
    id,
    title: clean(header.job?.title) ?? clean(ld?.title as string) ?? "(untitled)",
    company: (key.isChiffre ? null : clean(header.company?.name)) ?? clean(ld?.hiringOrganization?.name),
    companyWebsite: website && /^https?:\/\//i.test(website) ? website : null,
    location: clean(key.locations) ?? ldLocation(ld),
    date: isoDate(ld?.datePosted),
    validThrough: isoDate(ld?.validThrough),
    url: `${BASE}/jobs/${id}`,
    applyUrl,
    employmentType: clean(key.employmentTypes) ?? employmentLd,
    jobLevel: clean(key.jobLevel),
    homeOffice: bool(key.isHomeOffice) ?? bool(detail.isHomeoffice),
    salary: clean(key.salaryRange),
    description: cleanBlock(descHtml),
    isActive: !(detail.isInactive === true || header.job?.isInactive === true),
  }
}
