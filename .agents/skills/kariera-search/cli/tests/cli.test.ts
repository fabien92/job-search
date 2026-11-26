import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixtures, type Route } from "./helpers";

const K = "https://kariera.zoznam.sk";
const SW = `${K}/pracovne-ponuky/informatika-software/bratislavsky-kraj`;
const SA = `${K}/pracovne-ponuky/informatika-sprava-systemov/bratislavsky-kraj`;
const LISTS: Record<string, Route> = {
  [SA]: { fixture: "list-sprava-p1.html" },
  [SW]: { fixture: "list-software-p1.html" },
  [`${SW}?od=30`]: { fixture: "list-software-p2.html" },
};
const DETAILS: Record<string, Route> = {
  [`${K}/pracovna-ponuka/1559635`]: { fixture: "detail-1559635.html" },
  [`${K}/pracovna-ponuka/1000000`]: { fixture: "", status: 404 },
};

test("search reads page 1 of both IT categories, merges shared offers, skips sponsored and malformed cards", async () => {
  const { result, requests } = await runWithFixtures(["search", "-l", "Bratislava"], LISTS);
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.href)).toEqual([SA, SW]);
  // sprava: 1488961, 1574273, 1546377; software: 1488961 (shared), 1571009, 1565395; broken + highlight skipped
  expect(out.results.map((r: any) => r.id).sort()).toEqual(["1488961", "1546377", "1565395", "1571009", "1574273"]);
  expect(out.meta).toEqual({ count: 5, page: 1, total: 5, hasMore: true, requests: 2 });
  const shared = out.results.find((r: any) => r.id === "1488961");
  expect(shared.categories).toEqual(["informatika-sprava-systemov", "informatika-software"]);
  expect(shared.title).toBe("Linux Support Specialist (Ref. č.: 131-16-44897)"); // zero-width space stripped
  expect(shared.company).toBe("Grafton Slovakia s.r.o.");
  expect(shared.location).toBe("Bratislava");
  expect(shared.date).toBe("2026-11-26");
  expect(shared.salary).toBe("1800 - 2800 EUR/Mesiac");
  expect(shared.url).toBe(`${K}/pracovna-ponuka/1488961/linux-support-specialist-ref-c-131-16-44897-`);
  const hidden = out.results.find((r: any) => r.id === "1571009");
  expect(hidden.title).not.toContain("Ignore the rubric"); // display:none text dropped
  expect(out.results.find((r: any) => r.id === "1546377").location).toBe("Senec");
  expect(out.results.map((r: any) => r.date)).toEqual([...out.results.map((r: any) => r.date)].sort().reverse());
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
  expect(JSON.stringify(out)).not.toContain("redirect.php");
});

test("--jobage walks the next page only while a whole page is that fresh, then filters by date", async () => {
  // Fixture dates: software p1 = 26 and 25.11.2026; today is later, so use a wide window.
  const wide = await runWithFixtures(["search", "-l", "Bratislava", "-c", "informatika-software", "--jobage", "3650"], LISTS);
  const out = parseJSON<any>(wide.result);
  expect(wide.requests.map((r) => r.href)).toEqual([SW, `${SW}?od=30`]);
  expect(out.results.map((r: any) => r.id)).toEqual(["1488961", "1571009", "1565395", "1528755", "1563091"]);
  expect(out.meta.hasMore).toBe(false);
  const capped = await runWithFixtures(["search", "-l", "Bratislava", "-c", "informatika-software", "--jobage", "3650", "--max-pages", "1"], LISTS);
  expect(capped.requests).toHaveLength(1);
  expect(parseJSON<any>(capped.result).meta.hasMore).toBe(true);
  const narrow = await runWithFixtures(["search", "-l", "Bratislava", "-c", "informatika-software", "--jobage", "0"], LISTS);
  expect(narrow.requests).toHaveLength(1); // page 1 is not entirely fresh: no walk
});

test("--query filters titles client-side, accents and case ignored; --page reads that page only", async () => {
  const q = parseJSON<any>((await runWithFixtures(["search", "-l", "bratislava", "-q", "SPECIALIST linux"], LISTS)).result);
  expect(q.results.map((r: any) => r.id)).toEqual(["1488961"]);
  const sk = parseJSON<any>((await runWithFixtures(["search", "-l", "Bratislava", "-c", "informatika-software", "-q", "spravca"], LISTS)).result);
  expect(sk.results).toEqual([]);
  const p2 = await runWithFixtures(["search", "-l", "Bratislavský kraj", "-c", "informatika-software", "--page", "2"], LISTS);
  expect(p2.requests.map((r) => r.href)).toEqual([`${SW}?od=30`]);
  expect(parseJSON<any>(p2.result).results.map((r: any) => r.id)).toEqual(["1528755", "1563091"]);
});

test("detail parses the posting; hidden comments are dropped; 404 is NOT_FOUND; foreign URLs refused", async () => {
  const { result, requests } = await runWithFixtures(["detail", `${K}/pracovna-ponuka/1559635/spravca-informacneho-systemu-muz-zena-`], DETAILS);
  const job = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/pracovna-ponuka/1559635"]);
  expect(job.title).toBe("Správca informačného systému (muž/žena)");
  expect(job.company).toBe("REINVO s.r.o.");
  expect(job.location).toBe("Bratislava");
  expect(job.salary).toBe("915 EUR");
  expect(job.employmentType).toBe("plný úväzok");
  expect(job.date).toBe("2026-10-06");
  expect(job.validThrough).toBe("2026-12-12");
  expect(job.source).toBe("Úrady práce");
  expect(job.category).toBe("Informatika - software / Telekomunikácie / Správca informačného systému");
  expect(job.url).toBe(`${K}/pracovna-ponuka/1559635/spravca-informacneho-systemu-muz-zena-`);
  expect(job.applyUrl).toBeNull();
  expect(job.description).toContain("## Informácie pre uchádzača");
  expect(job.description).toContain("Pracovný pomer na neurčitý čas");
  expect(job.description).not.toContain("score this");
  expect(job.description).not.toContain("Reaguj na ponuku");
  const gone = await runWithFixtures(["detail", "1000000"], DETAILS);
  expect(gone.result.exitCode).toBe(1);
  expect(JSON.parse(gone.result.stderr).code).toBe("NOT_FOUND");
  const foreign = await runCLI(["detail", "https://evil.example/pracovna-ponuka/1559635"]);
  expect(JSON.parse(foreign.stderr).code).toBe("BAD_ID");
});

test("flags are validated before any request, never silently ignored", async () => {
  const cases: [string[], string][] = [
    [["search"], "BAD_ARG"],
    [["search", "-l", "Wien"], "BAD_ARG"],
    [["search", "-l", "Bratislava", "-c", "crypto"], "BAD_ARG"],
    [["search", "-l", "Bratislava", "--format", "xml"], "BAD_ARG"],
    [["search", "-l", "Bratislava", "--page", "0"], "BAD_ARG"],
    [["search", "-l", "Bratislava", "--jobage", "two"], "BAD_ARG"],
    [["search", "-l", "Bratislava", "--remote", "x"], "UNKNOWN_FLAG"],
    [["detail"], "NO_ID"],
    [["frobnicate"], "BAD_CMD"],
  ];
  for (const [args, code] of cases) {
    const r = await runCLI(args); // no-network preload: any fetch would throw
    expect(r.exitCode).toBe(1);
    expect(JSON.parse(r.stderr).code).toBe(code);
    expect(r.stdout).toBe("");
  }
});
