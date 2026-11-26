// Data source: Randstad Austria job search, www.randstad.at (Drupal, server-rendered HTML).
// Public pages, no authentication. Randstad is a staffing agency (Zeitarbeit, Personalvermittlung):
// the client employer is almost never named, so `company` is null and `recruiter` is "Randstad".
//
// Search: GET https://www.randstad.at/jobs/<state>/<city>/ (Vienna: /jobs/wien/wien/; /jobs/wien/
// answers 301 there), page n > 1 at …/page-<n>/; the whole of Austria at /jobs/ (…/jobs/page-<n>/).
// 30 openings per page, not in date order. Vienna holds 39 openings, Austria 522 (2026-11-26).
// One Berufsfeld: /jobs/s-<slug>/<state>/<city>/ (IT in Vienna: /jobs/s-edv-it/wien/wien/, 2 openings
// on 2026-11-26; an empty listing answers 200 with no cards and no heading).
// h1.sortbar__count "39 Jobs gefunden in Wien, Wien" gives the total. One
// <li class="cards__item …" data-rs-card="true"> per opening: a.cards__link
// (/jobs/<slug>_<city>_<id>/), ul.cards__meta (place, contract type and salary, each tagged by the
// aria-label of its icon), div.cards__description (teaser), "veröffentlicht am 8. Oktober 2026".
// Keyword search goes through ?search= and /qt-…/ paths, which robots.txt disallows: not used.
//
// Detail: GET https://www.randstad.at/jobs/job_wien_<id>/ answers 301 to the canonical
// /jobs/<slug>_<city>_<id>/ whatever the slug and city; a closed opening answers 410.
// h1.content-block__title, li.behat-{calendar,expirationDate,location,salary,jobType,hours,
// specialism,referenceNumber}, description in the first div.body-copy > div.content. No JSON-LD.
//
// robots.txt (checked 2026-11-26): `Allow: /`, disallows the search parameters and filters
// (/*search=, /*/qt-, /*/km-, /*/postcode-, /*/sa-, /*/sd-, /*/sh-, /*/sm-, /*/?id=*, /*/mpage-),
// /*/apply/, /*/bewerben/, /node/; no Crawl-delay. The listing, page-<n> and detail paths used
// here are allowed (the sitemaps list them). Terms of use (/nutzungsbestimmungen/ §5): visitors
// must be genuine job seekers; no clause on automated access.

export const BASE = "https://www.randstad.at"
export const PAGE_SIZE = 30
export const MAX_PAGES = 25 // safety cap: ~18 pages for the whole of Austria today

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; randstad-cli/1.0)"

export interface Fetched {
  html: string
  url: string // final URL after redirects
}

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404 or 410 (closed opening). */
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

/** Pause between page requests (no Crawl-delay in robots.txt; keep it gentle). RANDSTAD_CLI_DELAY_MS=0 in tests. */
export function politeDelay(): Promise<void> {
  const ms = Number(process.env.RANDSTAD_CLI_DELAY_MS ?? 2000)
  return new Promise((r) => setTimeout(r, Number.isFinite(ms) && ms > 0 ? ms : 0))
}

export interface JobCard {
  id: string // Randstad job id, e.g. "47720442"
  title: string
  company: null // the client is not named
  recruiter: "Randstad"
  location: string | null
  date: string | null // YYYY-MM-DD, "veröffentlicht am"
  url: string
  employmentType: string | null // "Festanstellung", "Zeitarbeit", …
  homeOffice: null
  salary: string | null
  summary: string | null
}

export interface JobDetail extends JobCard {
  hours: string | null
  specialism: string | null
  reference: string | null
  description: string | null
  applyUrl: null // applying goes through Randstad on the posting page
  validThrough: string | null // "gültig bis"
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

// ---------------------------------------------------------------- Randstad parsing

const MONTHS: Record<string, string> = {
  januar: "01", jänner: "01", jaenner: "01", februar: "02", feber: "02", märz: "03", maerz: "03", april: "04",
  mai: "05", juni: "06", juli: "07", august: "08", september: "09", oktober: "10", november: "11", dezember: "12",
}

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/**
 * Absolute: "veröffentlicht am 8. Oktober 2026" / "gültig bis 4. Jänner 2027" -> "2026-10-08".
 * Relative (recent postings, the site's own strings): "heute gepostet", "vor 1 Tag veröffentlicht",
 * "vor 3 Tagen veröffentlicht", "nur noch heute gültig", "noch 5 Tage gültig" -> counted from
 * today in Vienna. null otherwise.
 */
export function germanDate(s: string | null | undefined, today: string = viennaToday()): string | null {
  const text = (s ?? "").trim()
  const m = text.match(/(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\s+(\d{4})\s*$/)
  if (m) {
    const mm = MONTHS[m[2].toLowerCase()]
    const d = Number(m[1])
    if (!mm || d < 1 || d > 31) return null
    return `${m[3]}-${mm}-${m[1].padStart(2, "0")}`
  }
  if (/^(heute gepostet|nur noch heute gültig)$/i.test(text)) return today
  const ago = text.match(/^vor (\d{1,3}) Tag(?:en)? veröffentlicht$/i)
  if (ago) return shiftDays(today, -Number(ago[1]))
  const left = text.match(/^noch (\d{1,3}) Tage? gültig$/i)
  if (left) return shiftDays(today, Number(left[1]))
  return null
}

/** Spellings of one place -> its Randstad listing path. */
export const PLACES: { names: string[]; path: string }[] = [
  { names: ["wien", "vienna", "vienne"], path: "/jobs/wien/wien/" },
  { names: ["graz"], path: "/jobs/steiermark/graz/" },
  { names: ["linz"], path: "/jobs/oberosterreich/linz/" },
  { names: ["salzburg"], path: "/jobs/salzburg/salzburg/" },
]

/**
 * Berufsfelder with a public listing (/sitemaps/jobs/sitemap-joblistings-<slug>.xml, 2026-11-26):
 * /jobs/s-<slug>/ for Austria, /jobs/s-<slug>/<state>/<city>/ for a city.
 */
export const SPECIALISMS = [
  "assistenz-sekretariat-verwaltung", "call-center", "edv-it", "einkauf-beschaffung", "facharbeit-gewerbe-produktion",
  "financial-services", "hilfskraefte", "lager-logistik-transport", "pharma-biotech-chemie",
  "rechnungswesen-controlling-buchhaltung", "sachbearbeitung", "sonstige-berufe", "technik-ingenieurwesen",
  "verkauf-kundenbetreuung",
]

/**
 * "Wien,Vienna,Graz" -> the distinct listing paths, inside one Berufsfeld when `specialism` is set
 * ("edv-it": /jobs/s-edv-it/wien/wien/); throws on a place or Berufsfeld without a known listing.
 */
export function placePaths(location: string | undefined, specialism?: string): string[] {
  const field = specialism?.trim().toLowerCase()
  if (field !== undefined && !SPECIALISMS.includes(field)) {
    throw new Error(`unknown specialism "${specialism}" (known: ${SPECIALISMS.join(", ")})`)
  }
  const inField = (path: string) => (field ? path.replace(/^\/jobs\//, `/jobs/s-${field}/`) : path)
  const wanted = (location ?? "").split(",").map((l) => l.trim().toLowerCase()).filter(Boolean)
  if (wanted.length === 0) return [inField("/jobs/")]
  const paths: string[] = []
  for (const w of wanted) {
    const place = PLACES.find((p) => p.names.includes(w))
    if (!place) throw new Error(`unknown place "${w}" (known: ${PLACES.map((p) => p.names[0]).join(", ")}; omit -l for the whole of Austria)`)
    if (!paths.includes(inField(place.path))) paths.push(inField(place.path))
  }
  return paths
}

export function listUrl(path: string, page: number): string {
  return `${BASE}${path}${page > 1 ? `page-${page}/` : ""}`
}

export function jobUrl(id: string): string {
  return `${BASE}/jobs/job_wien_${id}/` // 301 to the canonical slug, whatever the city
}

export interface SearchPage {
  cards: JobCard[]
  total: number | null
}

/** One cards__meta-item: its icon's aria-label says what it is. */
function metaItems(chunk: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of chunk.matchAll(/<li class="cards__meta-item[^"]*">([\s\S]*?)<\/li>/g)) {
    const label = m[1].match(/aria-label="([^"]*)"/)?.[1] ?? ""
    const text = clean(m[1])
    if (!text) continue
    if (/^Ort/i.test(label)) out.location = text
    else if (/^Art der Tätigkeit/i.test(label)) out.type = text
    else if (/^Gehalt/i.test(label)) out.salary = text
  }
  return out
}

/** Split into cards__item chunks and parse each on its own. */
export function parseSearchPage(html: string): SearchPage {
  const cards: JobCard[] = []
  const seen = new Set<string>()
  const chunks = html.split(/<li class="cards__item[^"]*" data-rs-card="true">/).slice(1)
  for (const raw of chunks) {
    try {
      const chunk = visibleHtml(raw)
      const a = chunk.match(/<a href="(\/jobs\/[^"/?#]+_(\d{6,10})\/)"[^>]*class="cards__link">([\s\S]*?)<\/a>/)
      if (!a) continue
      const [, path, id, rawTitle] = a
      const title = clean(rawTitle)
      if (!title || seen.has(id)) continue
      seen.add(id)
      const meta = metaItems(chunk)
      const teaser = chunk.match(/<div class="cards__description">([\s\S]*?)<\/div>/)
      const since = chunk.match(/<span class="cards__date[^"]*">([^<]+)</)
      const summary = teaser ? clean(teaser[1]) : null
      cards.push({
        id,
        title,
        company: null,
        recruiter: "Randstad",
        location: meta.location ?? null,
        date: germanDate(since ? clean(since[1]) : null),
        url: BASE + path,
        employmentType: meta.type ?? null,
        homeOffice: null,
        salary: meta.salary ?? null,
        summary: summary && summary.length > 600 ? summary.slice(0, 600) + "…" : summary,
      })
    } catch {
      continue
    }
  }
  // "39 Jobs gefunden in Wien, Wien"; inside a Berufsfeld "2 EDV &amp; IT Jobs in Wien, Wien für Sie gefunden"
  const total = html.match(/<h1 class="sortbar__count">\s*([\d.]+) [^<]*?\bJobs?\b[^<]*?gefunden/)
  return { cards, total: total ? Number(total[1].replace(/\./g, "")) : cards.length === 0 ? 0 : null }
}

function behat(html: string, name: string): string | null {
  const m = html.match(new RegExp(`<li class="[^"]*\\bbehat-${name}\\b[^"]*">([\\s\\S]*?)</li>`))
  return m ? clean(m[1]) : null
}

export function parseJobDetail(html: string, id: string, finalUrl: string): JobDetail {
  const page = visibleHtml(html)
  const h1 = page.match(/<h1 class="content-block__title">([\s\S]*?)<\/h1>/)
  const title = h1 ? clean(h1[1])?.replace(/\.$/, "") || null : null
  if (!title) throw new Error("detail page has no h1 headline (markup changed?)")
  const body = page.match(/<div class="body-copy[^"]*"><div class="content"[^>]*>([\s\S]*?)<span class="read-more-dots">/)
  const specialism = behat(page, "specialism")
  const reference = behat(page, "referenceNumber")
  const intro = "Posted by Randstad (staffing agency) for a client; the employer is not named."
  const canonical = finalUrl.match(/^https:\/\/www\.randstad\.at\/jobs\/[^/?#]+_\d{6,10}\/$/) ? finalUrl : jobUrl(id)
  return {
    id,
    title,
    company: null,
    recruiter: "Randstad",
    location: behat(page, "location"),
    date: germanDate(behat(page, "calendar")),
    url: canonical,
    employmentType: behat(page, "jobType"),
    homeOffice: null,
    salary: behat(page, "salary"),
    summary: null,
    hours: behat(page, "hours"),
    specialism: specialism ? specialism.replace(/^Berufsfeld\s*/, "") || null : null,
    reference: reference ? reference.replace(/^Referenznummer:\s*/, "") || null : null,
    description: [intro, cleanBlock(body ? body[1] : null)?.replace(/\n{2,}(?=• )/g, "\n") ?? "(no description)"].join("\n\n"),
    applyUrl: null,
    validThrough: germanDate(behat(page, "expirationDate")),
    isActive: true, // closed openings answer 410 (NOT_FOUND)
  }
}
