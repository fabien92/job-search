// Data source: Profession.hu (profession.hu Kft.), the largest Hungarian job board. Public pages,
// no authentication.
//
// Search: the board's own RSS feeds, one per category, linked from the home page footer:
// GET https://www.profession.hu/partner/files/rss-<category>.rss answers 301 to
// https://stat.profession.hu/partner/files/rss-<category>.rss. 20 newest openings for the whole of
// Hungary; <pubDate> is the time the feed was generated (the same for every item), not the posting
// date. <link> is /allas/<slug>-<id>[/optimum]/p/569 (the /p/569 suffix is the feed's partner tag);
// <description> ends with "Hirdető cég: <company>". The city is the last Hungarian place name in
// the slug when there is one ("…-budapest-3058862"); some slugs carry none.
// Keyword search pages carry `?rss` / filters that robots.txt partly disallows: not used.
//
// Detail: GET https://www.profession.hu/allas/<id> (200, canonical link to the slug). One JSON-LD
// @graph with a JobPosting (title, hiringOrganization, jobLocation.address, datePosted,
// validThrough, employmentType, experienceRequirements, educationRequirements, workHours) and the
// posting text in <div id="box_…" class="box-container"> blocks (h2 title + itemprop content).
//
// robots.txt (checked 2026-11-26): disallows the account, application, employer and candidate
// areas, /en/, /impresszum, terms PDFs and `*?rss$`; /allas/ and /partner/files/ are allowed; no
// Crawl-delay. Terms of use (felhasznalasifeltetelek_20201008.pdf §V.3): content may be read,
// displayed, saved and printed for personal, non-commercial use only; §VIII.1.d: no program that
// endangers the service. No clause on automated access: one person's job search, low volume.

export const BASE = "https://www.profession.hu"
export const CATEGORIES = [
  "adminisztracio", "bank", "egeszsegugy", "ertekesites", "hr", "it", "jog", "marketing", "mernok",
  "oktatas", "szakmunka", "szamvitel", "ugyfelszolgalat", "vendeglatas",
] as const

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; profession-cli/1.0)"

export interface Fetched {
  body: string
  url: string // final URL after redirects
}

/** Fetch with exponential backoff on 429/5xx. Returns null on a 404 or 410. */
export async function httpFetch(url: string, accept = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"): Promise<Fetched | null> {
  const maxRetries = 6
  let delay = 1000
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": UA, "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8", Accept: accept },
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

/** Pause between requests (no Crawl-delay in robots.txt; keep it gentle). PROFESSION_CLI_DELAY_MS=0 in tests. */
export function politeDelay(): Promise<void> {
  const ms = Number(process.env.PROFESSION_CLI_DELAY_MS ?? 2000)
  return new Promise((r) => setTimeout(r, Number.isFinite(ms) && ms > 0 ? ms : 0))
}

export interface JobCard {
  id: string // Profession.hu job id, e.g. "3058862"
  title: string
  company: string | null
  location: string | null // city from the slug, or from the posting when the slug names none
  date: string | null // the feed has no posting date: filled by `detail`
  url: string // https://www.profession.hu/allas/<slug>-<id>
  employmentType: null
  homeOffice: null
  salary: null
  summary: null
}

export interface JobDetail extends Omit<JobCard, "employmentType" | "homeOffice" | "salary" | "summary"> {
  employmentType: string | null // "Alkalmazotti jogviszony" (employee), …
  homeOffice: string | null
  salary: string | null
  summary: null
  country: string | null
  experience: string | null
  education: string | null
  hours: string | null
  category: string | null
  description: string | null
  applyUrl: null // applying goes through Profession.hu (/jelentkezes/, disallowed by robots.txt)
  validThrough: string | null // YYYY-MM-DD
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

// ---------------------------------------------------------------- Profession.hu parsing

/** Lower case, accents removed: "Győr" -> "gyor", "Székesfehérvár" -> "szekesfehervar". */
export function fold(s: string): string {
  return s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim()
}

/** Hungarian places as they appear in slugs -> display name. Larger towns and the Budapest area. */
export const PLACES: Record<string, string> = {
  budapest: "Budapest", debrecen: "Debrecen", szeged: "Szeged", miskolc: "Miskolc", pecs: "Pécs",
  gyor: "Győr", nyiregyhaza: "Nyíregyháza", kecskemet: "Kecskemét", szekesfehervar: "Székesfehérvár",
  szombathely: "Szombathely", szolnok: "Szolnok", erd: "Érd", tatabanya: "Tatabánya", kaposvar: "Kaposvár",
  sopron: "Sopron", veszprem: "Veszprém", bekescsaba: "Békéscsaba", zalaegerszeg: "Zalaegerszeg",
  eger: "Eger", nagykanizsa: "Nagykanizsa", dunaujvaros: "Dunaújváros", hodmezovasarhely: "Hódmezővásárhely",
  dunakeszi: "Dunakeszi", cegled: "Cegléd", baja: "Baja", salgotarjan: "Salgótarján", szentendre: "Szentendre",
  godollo: "Gödöllő", vac: "Vác", budaors: "Budaörs", esztergom: "Esztergom", paks: "Paks", gyal: "Gyál",
  szigetszentmiklos: "Szigetszentmiklós", vecses: "Vecsés", torokbalint: "Törökbálint", biatorbagy: "Biatorbágy",
  gyongyos: "Gyöngyös", komarom: "Komárom", mosonmagyarovar: "Mosonmagyaróvár", ajka: "Ajka",
  oroshaza: "Orosháza", kiskunfelegyhaza: "Kiskunfélegyháza", papa: "Pápa", jaszbereny: "Jászberény",
  szekszard: "Szekszárd", hatvan: "Hatvan", kazincbarcika: "Kazincbarcika", ozd: "Ózd", tata: "Tata",
  fot: "Fót", gyomro: "Gyömrő", pomaz: "Pomáz", dunaharaszti: "Dunaharaszti", szigethalom: "Szigethalom",
}

/** The place a slug names (the last one, after the company name), or null. */
export function slugPlace(slug: string): string | null {
  const tokens = slug.toLowerCase().split("-")
  for (let i = tokens.length - 1; i >= 0; i--) if (PLACES[tokens[i]]) return PLACES[tokens[i]]
  return null
}

/** "Budapest,Győr" -> folded place keys; throws on a place this CLI does not know. */
export function wantedPlaces(location: string | undefined): Set<string> | null {
  const wanted = (location ?? "").split(",").map(fold).filter(Boolean)
  if (wanted.length === 0) return null
  for (const w of wanted) {
    if (!PLACES[w]) throw new Error(`unknown place "${w}" (Hungarian towns only, e.g. Budapest; omit -l for the whole of Hungary)`)
  }
  return new Set(wanted)
}

export function feedUrl(category: string): string {
  return `${BASE}/partner/files/rss-${category}.rss`
}

export function jobUrl(id: string): string {
  return `${BASE}/allas/${id}` // 200 whatever the slug
}

const LINK = /^https:\/\/www\.profession\.hu\/allas\/([a-z0-9-]+?-)?(\d{6,8})(?:\/[a-z]+)?(?:\/p\/\d+)?\/?$/

/** Feed link -> {id, slug, canonical URL}; null for anything that is not a www.profession.hu posting. */
export function parseLink(link: string): { id: string; slug: string; url: string } | null {
  const m = link.trim().match(LINK)
  if (!m) return null
  const slug = (m[1] ?? "") + m[2]
  return { id: m[2], slug, url: `${BASE}/allas/${slug}` }
}

function tag(item: string, name: string): string | null {
  const m = item.match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`))
  if (!m) return null
  const cdata = m[1].match(/^\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*$/)
  return cdata ? cdata[1] : decodeHtmlEntities(m[1])
}

/** One <item> per opening; malformed items are skipped. */
export function parseFeed(xml: string): JobCard[] {
  const cards: JobCard[] = []
  const seen = new Set<string>()
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    try {
      const link = parseLink(tag(m[1], "link") ?? "")
      const title = clean(tag(m[1], "title"))
      if (!link || !title || seen.has(link.id)) continue
      seen.add(link.id)
      const company = clean(tag(m[1], "description")?.match(/Hirdető cég:\s*([\s\S]+)$/)?.[1])
      cards.push({
        id: link.id,
        title,
        company,
        location: slugPlace(link.slug),
        date: null,
        url: link.url,
        employmentType: null,
        homeOffice: null,
        salary: null,
        summary: null,
      })
    } catch {
      continue
    }
  }
  return cards
}

/** The JobPosting node of the page's JSON-LD (plain object or @graph). */
export function jobPosting(html: string): Record<string, any> | null {
  for (const m of html.matchAll(/<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)) {
    let data: any
    try {
      data = JSON.parse(m[1])
    } catch {
      continue
    }
    const nodes = Array.isArray(data) ? data : Array.isArray(data?.["@graph"]) ? data["@graph"] : [data]
    const node = nodes.find((n: any) => n && n["@type"] === "JobPosting")
    if (node) return node
  }
  return null
}

/** End of the element opened at `start` (balanced <div>s), or the end of the text. */
function divEnd(html: string, start: number): number {
  const re = /<(\/?)div\b[^>]*>/gi
  re.lastIndex = start
  let depth = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    depth += m[1] ? -1 : 1
    if (depth === 0) return re.lastIndex
  }
  return html.length
}

/** The posting text: every box-container block, its h2 title then its content. */
export function postingText(html: string): string | null {
  const page = visibleHtml(html)
  const parts: string[] = []
  for (const m of page.matchAll(/<div id="box_[^"]*" class="box-container">/g)) {
    const box = page.slice(m.index!, divEnd(page, m.index!))
    const title = clean(box.match(/<h2[^>]*>([\s\S]*?)<\/h2>/)?.[1])
    const body = cleanBlock(box.replace(/<h2[^>]*>[\s\S]*?<\/h2>/, ""))?.replace(/\n{2,}(?=• )/g, "\n")
    if (body) parts.push([title ? `## ${title.replace(/:$/, "")}` : "", body].filter(Boolean).join("\n"))
  }
  return parts.length ? parts.join("\n\n") : null
}

const isoDay = (v: unknown) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v) ? v.slice(0, 10) : null)
const text = (v: unknown) => (typeof v === "string" ? clean(v) : null)

function salaryText(base: any): string | null {
  const value = base?.value
  if (!value) return null
  const unit = value.unitText ? ` / ${value.unitText}` : ""
  const cur = base.currency ? ` ${base.currency}` : ""
  if (value.minValue && value.maxValue) return `${value.minValue}–${value.maxValue}${cur}${unit}`
  if (value.value) return `${value.value}${cur}${unit}`
  return null
}

/** Location of a posting that gives no address but is flagged TELECOMMUTE (remote or hybrid, office not given). */
export const REMOTE_HU = "Magyarország (távmunka)"

export function parseJobDetail(html: string, id: string, today: string = viennaToday()): JobDetail {
  const node = jobPosting(html)
  if (!node) throw new Error("detail page has no JobPosting JSON-LD (markup changed?)")
  const title = text(node.title) ?? text(node.name)
  if (!title) throw new Error("JobPosting has no title")
  const place = Array.isArray(node.jobLocation) ? node.jobLocation[0] : node.jobLocation
  const address = place?.address ?? {}
  const canonical = html.match(/<link rel="canonical" href="([^"]+)"/)?.[1]
  const link = canonical ? parseLink(canonical) : null
  const validThrough = isoDay(node.validThrough)
  return {
    id,
    title,
    company: text(node.hiringOrganization?.name),
    location: text(address.addressLocality) ?? (node.jobLocationType === "TELECOMMUTE" ? REMOTE_HU : null),
    date: isoDay(node.datePosted),
    url: link && link.id === id ? link.url : jobUrl(id),
    employmentType: text(node.employmentType),
    homeOffice: node.jobLocationType === "TELECOMMUTE" ? "remote" : null,
    salary: salaryText(node.baseSalary),
    summary: null,
    country: text(address.addressCountry),
    experience: text(node.experienceRequirements),
    education: text(node.educationRequirements),
    hours: text(node.workHours),
    category: text(node.occupationalCategory),
    description: postingText(html) ?? cleanBlock(typeof node.description === "string" ? node.description : null),
    applyUrl: null,
    validThrough,
    isActive: validThrough === null || validThrough >= today,
  }
}
