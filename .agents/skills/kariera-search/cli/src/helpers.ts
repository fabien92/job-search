// Data source: Kariéra.sk (kariera.zoznam.sk, Zoznam s.r.o.), a Slovak job board. Public pages, no
// authentication.
//
// Search: the public listing of one category in one region, rendered server-side:
// GET https://kariera.zoznam.sk/pracovne-ponuky/<category>/<region>[?od=<offset>], 30 cards per
// page, newest first (the card date is the date the offer was published or last refreshed), the
// next pages at ?od=30, ?od=60 (<ul class="paginator">). Each card is a
// <div class="offer"> with h2.offer-title > a[href="pracovna-ponuka/<id>/<slug>"], .offer-employer,
// .offer-locality, ul.offer-info (salary) and span.date (DD.MM.YYYY). Sponsored carousel cards
// (<div class="offer highlight">, links through redirect.php) are not offers of the listing: skipped.
// The same offer often sits in several categories: merged on its id.
// Keyword search (?q=) is disallowed by robots.txt: never used; --query filters titles client-side.
//
// Detail: GET https://kariera.zoznam.sk/pracovna-ponuka/<id> (200 whatever the slug, canonical
// link to /pracovna-ponuka/<id>/<slug>). No JSON-LD: h1 (title), .offer-company (employer),
// ul.offer-detail-info (Miesto práce = place, Ponúkaný plat = salary, Druh pracovného pomeru =
// employment type), then the posting text up to ul.offer-detail-buttons, then div.offer-date
// (Pozícia / odvetvie, "Dátum zverejnenia: DD.MM.YYYY"). Offers taken over from the labour offices
// (Úrady práce, sluzbyzamestnanosti.gov.sk) also give "Dátum ukončenia ponuky: DD.MM.YYYY".
//
// robots.txt (checked 2026-11-26): disallows /sk/, /en/ and the English pages (/job-offers/,
// /job-offer/…), /rss/, /export/, /cv/, /*?q=*, /redirect.php and the ordering pages; the listings
// /pracovne-ponuky/<category>/<region> (also with ?od=) and the postings /pracovna-ponuka/ are
// allowed; no Crawl-delay. Terms (obchodne-podmienky): no clause on automated access; the
// database rights clauses cover the CV database (employers). One person's job search, low volume.

export const BASE = "https://kariera.zoznam.sk"
export const PAGE_SIZE = 30

/** Categories this CLI reads (listing slugs). The JobBot default: the two IT categories. */
export const CATEGORIES = [
  "informatika-sprava-systemov", "informatika-software", "telekomunikacie", "bankovnictvo",
  "ekonomika-financie-uctovnictvo", "vrcholovy-manazment", "manazment-kvality", "zakaznicka-podpora",
] as const
export const DEFAULT_CATEGORIES = ["informatika-sprava-systemov", "informatika-software"]

/** Places accepted by --location -> the region listing that holds them. */
export const REGIONS: Record<string, string> = {
  bratislava: "bratislavsky-kraj", "bratislavsky kraj": "bratislavsky-kraj",
  trnava: "trnavsky-kraj", "trnavsky kraj": "trnavsky-kraj",
  nitra: "nitriansky-kraj", "nitriansky kraj": "nitriansky-kraj",
  trencin: "trenciansky-kraj", "trenciansky kraj": "trenciansky-kraj",
  zilina: "zilinsky-kraj", "zilinsky kraj": "zilinsky-kraj",
  "banska bystrica": "banskobystricky-kraj", "banskobystricky kraj": "banskobystricky-kraj",
  presov: "presovsky-kraj", "presovsky kraj": "presovsky-kraj",
  kosice: "kosicky-kraj", "kosicky kraj": "kosicky-kraj",
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; kariera-cli/1.0)"

export interface Fetched {
  body: string
  url: string // final URL after redirects
}

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404 or 410. */
export async function httpFetch(url: string): Promise<Fetched | null> {
  const maxRetries = 6
  let delay = 1000
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": UA, "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8", Accept: "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8" },
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
    return { body: await response.text(), url: response.url || url }
  }
  throw new Error("Request failed after max retries")
}

/** Pause between requests (no Crawl-delay in robots.txt; keep it gentle). KARIERA_CLI_DELAY_MS=0 in tests. */
export function politeDelay(): Promise<void> {
  const ms = Number(process.env.KARIERA_CLI_DELAY_MS ?? 2000)
  return new Promise((r) => setTimeout(r, Number.isFinite(ms) && ms > 0 ? ms : 0))
}

export interface JobCard {
  id: string // Kariéra.sk offer id, e.g. "1559635"
  title: string
  company: string | null
  location: string | null // "Bratislava", "Senec", "Bratislavský kraj"…
  date: string | null // YYYY-MM-DD, the card date (published or refreshed)
  url: string // https://kariera.zoznam.sk/pracovna-ponuka/<id>/<slug>
  employmentType: null
  homeOffice: null
  salary: string | null // "1800 - 2800 EUR/Mesiac" as shown
  summary: null
  categories: string[] // listing slugs the card was found in
}

export interface JobDetail {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null // "Dátum zverejnenia" (first publication)
  url: string
  employmentType: string | null // "plný úväzok" (full time), "skrátený úväzok", "živnosť"…
  homeOffice: null
  salary: string | null
  summary: null
  category: string | null // "Informatika - software / Telekomunikácie / …"
  description: string | null
  source: string | null // "Úrady práce" when taken over from the labour offices
  applyUrl: null // applying goes through Kariéra.sk (reaguj-na-ponuku): never touched
  validThrough: string | null // "Dátum ukončenia ponuky" when given, YYYY-MM-DD
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

// ---------------------------------------------------------------- Kariéra.sk parsing

/** Lower case, accents removed: "Bratislavský kraj" -> "bratislavsky kraj". */
export function fold(s: string): string {
  return s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim()
}

/** "Bratislava,Trnava" -> region listing slugs (deduplicated); throws on a place this CLI does not know. */
export function wantedRegions(location: string | undefined): string[] {
  const wanted = (location ?? "").split(",").map(fold).filter(Boolean)
  if (wanted.length === 0) throw new Error("--location is required (a Slovak region town, e.g. Bratislava)")
  const out: string[] = []
  for (const w of wanted) {
    const region = REGIONS[w]
    if (!region) throw new Error(`unknown place "${w}" (Slovak regions only: ${[...new Set(Object.values(REGIONS))].join(", ")})`)
    if (!out.includes(region)) out.push(region)
  }
  return out
}

export function listUrl(category: string, region: string, page = 1): string {
  return `${BASE}/pracovne-ponuky/${category}/${region}${page > 1 ? `?od=${(page - 1) * PAGE_SIZE}` : ""}`
}

export function jobUrl(id: string): string {
  return `${BASE}/pracovna-ponuka/${id}` // 200 whatever the slug
}

/** "26.11.2026" -> "2026-11-26"; null otherwise. */
export function skDate(s: string | null | undefined): string | null {
  const m = (s ?? "").match(/(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})/)
  if (!m) return null
  const [d, mo, y] = [Number(m[1]), Number(m[2]), Number(m[3])]
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null
  return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`
}

const HREF = /^(?:https:\/\/kariera\.zoznam\.sk)?\/?pracovna-ponuka\/(\d{5,9})(?:\/([a-z0-9-]*))?\/?$/

/** Card or canonical href -> {id, url}; null for anything else (sponsored redirect.php links included). */
export function parseHref(href: string): { id: string; url: string } | null {
  const m = decodeHtmlEntities(href.trim()).match(HREF)
  if (!m) return null
  return { id: m[1], url: `${BASE}/pracovna-ponuka/${m[1]}${m[2] ? `/${m[2]}` : ""}` }
}

/** One card per <div class="offer">, parsed independently: a malformed card is skipped. */
export function parseListing(html: string, category: string): { cards: JobCard[]; hasNext: boolean } {
  const page = visibleHtml(html)
  const cards: JobCard[] = []
  const chunks = page.split(/(?=<div class="offer(?:\s[^"]*)?">)/).slice(1)
  for (const chunk of chunks) {
    try {
      if (!/^<div class="offer">/.test(chunk)) continue // highlight (sponsored) and other variants
      const a = chunk.match(/<h2 class="offer-title">\s*<a href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/)
      const link = a ? parseHref(a[1]) : null
      const title = a ? clean(a[2]) : null
      if (!link || !title) continue
      cards.push({
        id: link.id,
        title,
        company: clean(chunk.match(/<div class="offer-employer">([\s\S]*?)<\/div>/)?.[1]),
        location: clean(chunk.match(/<div class="offer-locality">([\s\S]*?)<\/div>/)?.[1]),
        date: skDate(chunk.match(/<span class="date">([^<]*)<\/span>/)?.[1]),
        url: link.url,
        employmentType: null,
        homeOffice: null,
        salary: clean(chunk.match(/<ul class="offer-info">([\s\S]*?)<\/ul>/)?.[1]),
        summary: null,
        categories: [category],
      })
    } catch {
      continue
    }
  }
  const pager = page.match(/<ul class="paginator">([\s\S]*?)<\/ul>/)?.[1] ?? ""
  const current = pager.match(/<li class="current">\s*<a[^>]*>(\d+)</)?.[1]
  const pages = [...pager.matchAll(/<a[^>]*>(\d+)<\/a>/g)].map((m) => Number(m[1]))
  const hasNext = current !== undefined && pages.some((p) => p > Number(current))
  return { cards, hasNext }
}

/** The value block of one ul.offer-detail-info item, found by its label ("Miesto práce"). */
function infoItem(info: string, label: string): string | null {
  for (const li of info.split(/<li\b[^>]*>/).slice(1)) {
    const lab = clean(li.match(/<div class="offer-label">([\s\S]*?)<\/div>/)?.[1])
    if (!lab || !fold(lab).startsWith(fold(label))) continue
    const links = [...li.matchAll(/<a [^>]*class="category_link"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => clean(m[1])).filter(Boolean)
    if (links.length) return links.join(", ")
    return clean(li.match(/<div class="offer-info[^"]*">([\s\S]*?)<\/div>/)?.[1])
  }
  return null
}

export function parseJobDetail(html: string, id: string, today: string = viennaToday()): JobDetail {
  const page = visibleHtml(html)
  const start = page.indexOf('<div class="offer-detail-content">')
  if (start < 0) throw new Error("detail page has no offer-detail-content block (markup changed?)")
  const content = page.slice(start)
  const title = clean(content.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)?.[1])
  if (!title) throw new Error("detail page has no title")
  const company = clean(content.match(/<div class="offer-company">([\s\S]*?)<\/div>/)?.[1])
  const infoStart = content.indexOf('<ul class="offer-detail-info">')
  const infoEnd = infoStart >= 0 ? content.indexOf("</ul>", infoStart) : -1
  const info = infoStart >= 0 && infoEnd > infoStart ? content.slice(infoStart, infoEnd) : ""
  const buttons = content.search(/<ul class="offer-detail-buttons">|<div class="offer-date">/)
  const textHtml = infoEnd > 0 ? content.slice(infoEnd + 5, buttons > infoEnd ? buttons : undefined) : ""
  const description =
    cleanBlock(textHtml.replace(/<h[23][^>]*>([\s\S]*?)<\/h[23]>/g, (_, t) => `<p>## ${clean(t)?.replace(/:$/, "") ?? ""}</p>`))
      ?.replace(/^## $/gm, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim() || null
  const dateBlock = content.match(/<div class="offer-date">([\s\S]*?)<\/div>/)?.[1] ?? ""
  const dateText = clean(dateBlock) ?? ""
  const category = [...dateBlock.matchAll(/<a [^>]*class="category_link"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => clean(m[1])).filter(Boolean).join(" / ") || null
  const canonical = html.match(/<link rel="canonical" href="([^"]+)"/)?.[1]
  const link = canonical ? parseHref(canonical) : null
  const validThrough = skDate(clean(textHtml)?.match(/Dátum ukončenia ponuky:\s*([\d.\s]+)/)?.[1])
  return {
    id,
    title,
    company,
    location: infoItem(info, "Miesto práce"),
    date: skDate(dateText.match(/Dátum zverejnenia:\s*([\d.\s]+)/)?.[1]),
    url: link && link.id === id ? link.url : jobUrl(id),
    employmentType: infoItem(info, "Druh pracovného pomeru"),
    homeOffice: null,
    salary: infoItem(info, "Ponúkaný plat"),
    summary: null,
    category,
    description,
    source: /sluzbyzamestnanosti\.gov\.sk/.test(textHtml) ? "Úrady práce" : null,
    applyUrl: null,
    validThrough,
    isActive: validThrough === null || validThrough >= today,
  }
}
