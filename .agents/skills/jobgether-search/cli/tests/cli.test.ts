import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixtures, type Route } from "./helpers";

const API = "/astroapi/ai/jobs.json";
const q = (params: Record<string, string>) => `${API}?${new URLSearchParams(params).toString()}`;
const PM = { keyword: "project manager", locations: "austria", sort: "date" };
const BOARD: Record<string, Route> = {
  [q({ ...PM, page: "1", limit: "25" })]: { fixture: "search-page1.json" },
  [q({ ...PM, page: "2", limit: "25" })]: { fixture: "search-page2.json" },
};

test("search walks the pages; --strict keeps Europe/EMEA/Austria and drops Anywhere-only offers", async () => {
  const { result, requests } = await runWithFixtures(["search", "-q", "project manager", "-l", "austria", "--strict"], BOARD);
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname + r.search)).toEqual(Object.keys(BOARD));
  expect(out.results.map((r: any) => r.id)).toEqual([
    "6b0648761870ab7f4cc39586", // Europe
    "6b0610371870ab7f4cc2a363", // EMEA
    "6b01c77f1870ab7f4cb0cecd", // EMEA, with salary
    "6b0092138acd9c1f9b34c5c5", // Europe
    "6afede078acd9c1f9b2bda3f", // Europe, republished (URL keeps the original's id)
    "6a3ed3732da8cde35c76c5b1", // "Austria, Delaware (USA)": the searched place is named
  ]);
  expect(out.meta).toEqual({ count: 6, page: 1, total: null, fetched: 12, filtered: 6, hasMore: false });
  const job = out.results[0];
  expect(job.title).toBe("Business Analyst & Project Manager"); // zero-width space stripped
  expect(job.company).toBe("Gegidze");
  expect(job.location).toBe("Europe");
  expect(job.date).toBe("2026-11-25");
  expect(job.url).toBe("https://jobgether.com/offer/6b0648761870ab7f4cc39586-business-analyst-project-manager");
  expect(job.employmentType).toBe("Full time");
  expect(job.applyUrl).toBeNull();
  expect(job.description).toStartWith("Jobgether listing (remote job board). The API gives no full job description");
  expect(job.description).toContain("Open to candidates in: Europe");
  expect(out.results[2].salary).toBe("28800-34560 USD");
  expect(out.results[2].description).toContain("Salary: 28800-34560 USD");
  expect(out.results[4].url).toContain("/offer/6a9b1c540875ca77c4ca6259-");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
});

test("without --strict every well-formed row is kept; the malformed row is skipped", async () => {
  const out = parseJSON<any>((await runWithFixtures(["search", "-q", "project manager", "-l", "austria"], BOARD)).result);
  expect(out.results).toHaveLength(12);
  expect(out.results.map((r: any) => r.title)).not.toContain("Malformed row");
  expect(out.results.some((r: any) => r.location === "Anywhere, United States")).toBe(true);
});

test("--jobage stops the date-sorted walk at the first page holding older offers", async () => {
  const { result, requests } = await runWithFixtures(["search", "-q", "project manager", "-l", "austria", "--jobage", "0"], BOARD);
  expect(parseJSON<any>(result).results).toEqual([]); // the fixtures are older than today
  expect(requests).toHaveLength(1);
});

test("--page, --limit, --sort relevance and table output", async () => {
  const p2 = await runWithFixtures(["search", "-q", "project manager", "-l", "austria", "--page", "2"], BOARD);
  expect(p2.requests).toHaveLength(1);
  expect(parseJSON<any>(p2.result).meta).toMatchObject({ page: 2, count: 3, hasMore: false });
  const lim = await runWithFixtures(["search", "-q", "project manager", "-l", "austria", "--limit", "2"], BOARD);
  expect(parseJSON<any>(lim.result).results).toHaveLength(2);
  const rel = await runWithFixtures(["search", "-q", "pm", "--sort", "relevance", "--page", "1"], {
    [q({ keyword: "pm", sort: "relevance", page: "1", limit: "25" })]: { fixture: "search-page2.json" },
  });
  expect(parseJSON<any>(rel.result).results).toHaveLength(3);
  const t = await runWithFixtures(["search", "-q", "project manager", "-l", "austria", "--strict", "--format", "table"], BOARD);
  expect(t.result.exitCode).toBe(0);
  expect(t.result.stdout).toContain("Gegidze");
});

test("detail searches the slug's words and returns the row with that id (also a republished one)", async () => {
  const routes: Record<string, Route> = {
    [q({ keyword: "business analyst project manager", sort: "relevance", page: "1", limit: "25" })]: { fixture: "search-page1.json" },
    [q({ keyword: "resilient watersheds project manager europe m f d", sort: "relevance", page: "1", limit: "25" })]: { fixture: "search-page1.json" },
  };
  const { result, requests } = await runWithFixtures(["detail", "https://jobgether.com/offer/6b0648761870ab7f4cc39586-business-analyst-project-manager"], routes);
  expect(requests).toHaveLength(1);
  const job = parseJSON<any>(result);
  expect(job.id).toBe("6b0648761870ab7f4cc39586");
  expect(job.description).toContain("Contract: Full time");
  const re = await runWithFixtures(["detail", "www.jobgether.com/offer/6a9b1c540875ca77c4ca6259-resilient-watersheds-project-manager-europe-m-f-d", "--format", "plain"], routes);
  expect(re.result.exitCode).toBe(0);
  expect(re.result.stdout).toStartWith("Resilient Watersheds Project Manager, Europe (m/f/d)\nThe Nature Conservancy");
});

test("detail falls back to the first three words, then NOT_FOUND", async () => {
  const empty = { fixture: "search-page2.json" };
  const { result, requests } = await runWithFixtures(["detail", "https://jobgether.com/offer/0123456789abcdef01234567-senior-it-delivery-manager"], {
    [q({ keyword: "senior it delivery manager", sort: "relevance", page: "1", limit: "25" })]: empty,
    [q({ keyword: "senior it delivery", sort: "relevance", page: "1", limit: "25" })]: empty,
  });
  expect(requests).toHaveLength(2);
  expect(result.exitCode).toBe(1);
  expect(JSON.parse(result.stderr).code).toBe("NOT_FOUND");
});

test("an API 400 (unknown location slug) is reported as BAD_ARG on stderr", async () => {
  const { result } = await runWithFixtures(["search", "-l", "narnia", "--page", "1"], {
    [q({ locations: "narnia", sort: "date", page: "1", limit: "25" })]: { fixture: "error-400.json", status: 400 },
  });
  expect(result.exitCode).toBe(1);
  expect(result.stdout).toBe("");
  const err = JSON.parse(result.stderr);
  expect(err.code).toBe("BAD_ARG");
  expect(err.error).toContain("Invalid value for 'locations'");
});

test("argument errors are JSON on stderr with exit 1, and nothing is fetched", async () => {
  for (const [args, code] of [
    [["search", "--remote", "x"], "UNKNOWN_FLAG"],
    [["search", "--hybrid"], "UNKNOWN_FLAG"],
    [["search", "--page", "0"], "BAD_ARG"],
    [["search", "--page", "11"], "BAD_ARG"],
    [["search", "--jobage", "two"], "BAD_ARG"],
    [["search", "--sort", "salary"], "BAD_ARG"],
    [["search", "-l", "vienna;rm"], "BAD_ARG"],
    [["search", "-q"], "BAD_ARG"],
    [["detail"], "NO_ID"],
    [["detail", "6b0648761870ab7f4cc39586"], "NEEDS_URL"],
    [["detail", "https://jobgether.com.evil.example/offer/6b0648761870ab7f4cc39586-x"], "BAD_ID"],
    [["detail", "https://jobgether.com/search-offers?keyword=x"], "BAD_ID"],
    [["frobnicate"], "BAD_CMD"],
  ] as const) {
    const r = await runCLI([...args]);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  }
});
