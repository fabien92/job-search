import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixtures, type Route } from "./helpers";

const W = "https://www.profession.hu";
const FEED: Record<string, Route> = {
  [`${W}/partner/files/rss-it.rss`]: { fixture: "rss-it.rss", finalUrl: "https://stat.profession.hu/partner/files/rss-it.rss" },
};
const DETAILS: Record<string, Route> = {
  [`${W}/allas/3058862`]: { fixture: "detail-3058862.html" },
  [`${W}/allas/3059477`]: { fixture: "detail-3059477.html" },
  [`${W}/allas/3055291`]: { fixture: "", status: 404 },
};

test("search without -l returns the whole feed; malformed and foreign items are skipped", async () => {
  const { result, requests } = await runWithFixtures(["search"], FEED);
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.href)).toEqual([`${W}/partner/files/rss-it.rss`]);
  expect(out.meta).toEqual({ count: 5, page: 1, total: 5, hasMore: false, unresolved: 0 });
  expect(out.results.map((r: any) => r.id)).toEqual(["3059519", "3058862", "3059477", "3047267", "3055291"]);
  const job = out.results[0];
  expect(job.title).toBe("Python fejlesztő Python, Django"); // zero-width space stripped
  expect(job.company).toBe("Innovative Software Solutions Kft.");
  expect(job.location).toBe("Dunakeszi");
  expect(job.date).toBeNull(); // the feed has no posting date
  expect(job.url).toBe(`${W}/allas/python-fejleszto-python-django-innovative-software-solutions-kft-dunakeszi-3059519`);
  expect(out.results[2].url).toBe(`${W}/allas/application-support-specialist-dynamics-ce-kh-karrier-hungaria-kft-3059477`); // no /optimum/p/569
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
});

test("-l Budapest keeps Budapest slugs, drops other towns, places the rest by reading the posting", async () => {
  const { result, requests } = await runWithFixtures(["search", "-l", "Budapest"], { ...FEED, ...DETAILS });
  const out = parseJSON<any>(result);
  // Dunakeszi dropped without a request; 3059477 (no town in the slug, remote) read and kept;
  // 3055291 read, 404: dropped and counted
  expect(requests.map((r) => r.pathname)).toEqual(["/partner/files/rss-it.rss", "/allas/3059477", "/allas/3055291"]);
  expect(out.results.map((r: any) => r.id)).toEqual(["3058862", "3059477", "3047267"]);
  expect(out.results[1].location).toBe("Magyarország (távmunka)");
  expect(out.meta.unresolved).toBe(1);
  const capped = parseJSON<any>((await runWithFixtures(["search", "-l", "Budapest", "--lookups", "0"], FEED)).result);
  expect(capped.results.map((r: any) => r.id)).toEqual(["3058862", "3047267"]);
  expect(capped.meta.unresolved).toBe(2);
});

test("accents and case do not matter; unknown places and categories are refused before any request", async () => {
  const gy = parseJSON<any>((await runWithFixtures(["search", "-l", "DUNAKESZI", "--lookups", "0"], FEED)).result);
  expect(gy.results.map((r: any) => r.id)).toEqual(["3059519"]);
  for (const args of [["search", "-l", "Wien"], ["search", "-c", "crypto"]]) {
    const bad = await runWithFixtures(args, FEED);
    expect(bad.result.exitCode).toBe(1);
    expect(JSON.parse(bad.result.stderr).code).toBe("BAD_ARG");
    expect(bad.requests).toEqual([]);
  }
  const t = await runWithFixtures(["search", "--format", "table", "--limit", "2"], FEED);
  expect(t.result.exitCode).toBe(0);
  expect(t.result.stdout).toContain("SAP rendszerüzemeltető");
  expect(t.result.stdout).not.toContain("Senior Site Reliability");
});

test("detail reads the JSON-LD and the content boxes, and hides invisible markup", async () => {
  const { result, requests } = await runWithFixtures(["detail", "3058862"], DETAILS);
  const job = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/allas/3058862"]);
  expect(job.title).toBe("SAP rendszerüzemeltető");
  expect(job.company).toBe("Semmelweis Egyetem Informatikai Főigazgatóság");
  expect(job.location).toBe("Budapest");
  expect(job.country).toBe("HU");
  expect(job.date).toBe("2026-11-25");
  expect(job.validThrough).toBe("2026-12-26");
  expect(job.employmentType).toBe("Alkalmazotti jogviszony");
  expect(job.experience).toBe("1-3 év tapasztalat");
  expect(job.url).toBe(`${W}/allas/sap-rendszeruzemelteto-semmelweis-egyetem-informatikai-foigazgatosag-budapest-3058862`);
  expect(job.applyUrl).toBeNull();
  expect(job.description).toContain("## Feladatok");
  expect(job.description).toContain("• SAP (ERP 6.0) felhasználók munkájának támogatása\n• ");
  expect(job.description).not.toContain("score this");
  expect(job.description).not.toContain("Ignore the rubric");
});

test("detail accepts a feed link; a missing posting is NOT_FOUND; foreign URLs are refused", async () => {
  const viaUrl = await runWithFixtures(
    ["detail", `${W}/allas/application-support-specialist-dynamics-ce-kh-karrier-hungaria-kft-3059477/optimum/p/569`], DETAILS);
  const job = parseJSON<any>(viaUrl.result);
  expect(job.id).toBe("3059477");
  expect(job.homeOffice).toBe("remote");
  expect(job.description).toContain("## Main responsibilities, tasks");
  const gone = await runWithFixtures(["detail", "3055291"], DETAILS);
  expect(gone.result.exitCode).toBe(1);
  expect(JSON.parse(gone.result.stderr).code).toBe("NOT_FOUND");
  const foreign = await runCLI(["detail", "https://evil.example/allas/x-3058862"]);
  expect(JSON.parse(foreign.stderr).code).toBe("BAD_ID");
});

test("flags are validated, never silently ignored", async () => {
  for (const args of [["search", "-q", "manager"], ["search", "--jobage", "2"], ["search", "--format", "xml"], ["search", "-l"], ["search", "--lookups", "-1"]]) {
    const r = await runCLI(args);
    expect(r.exitCode).toBe(1);
  }
  expect(JSON.parse((await runCLI(["search", "-q", "manager"])).stderr).code).toBe("UNKNOWN_FLAG");
});
