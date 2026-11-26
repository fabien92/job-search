import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixture } from "./helpers";

const SEARCH = "search-information-technology.json";
const SEARCH_PATH = "/api/public/opening/jo/list/filteredV2/en";
const DETAIL = "detail-288365.json";
const DETAIL_PATH = "/api/public/opening/joV2/288365/en";

test("search posts the documented body and returns the fixture's jobs", async () => {
  const { result, requests } = await runWithFixture(["search", "-q", "information technology"], SEARCH, "POST", SEARCH_PATH);
  const out = parseJSON<any>(result);
  expect(out.meta).toEqual({ count: 3, page: 1, total: 14, hasMore: false });
  const job = out.results[0];
  expect(job.id).toBe("289094");
  expect(job.title).toBe("INFORMATION SYSTEMS ASSISTANT, G5"); // invisible chars stripped
  expect(job.company).toBe("United Nations – United Nations Interim Security Force for Abyei- created under GA resolution 1990 (2011)");
  expect(job.location).toBe("Vienna");
  expect(job.date).toBe("2026-11-25");
  expect(job.deadline).toBe("2026-12-02");
  expect(job.grade).toBe("G-5");
  expect(job.url).toBe("https://careers.un.org/jobSearchDescription/289094?language=en");
  expect(out.results[2].location).toBe("Bangkok");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
  expect(requests).toHaveLength(1);
  expect(requests[0].method).toBe("POST");
  expect(requests[0].userAgent).toBe("Mozilla/5.0 (compatible; un-careers-cli/1.0)");
  expect(requests[0].body).toEqual({
    filterConfig: { keyword: "information technology" },
    pagination: { page: 0, itemPerPage: 100, sortBy: "startDate", sortDirection: -1 },
  });
});

test("search --location sends the duty-station code and keeps only that station", async () => {
  const { result, requests } = await runWithFixture(["search", "-l", "Wien", "--jobage", "400", "--page", "2"], SEARCH, "POST", SEARCH_PATH);
  const out = parseJSON<any>(result);
  expect(out.results.map((r: any) => r.id)).toEqual(["289094"]);
  expect(out.meta.page).toBe(2);
  expect(requests[0].body.filterConfig).toEqual({ ds: ["VIENNA"] }); // > 30 days: no portal span
  expect(requests[0].body.pagination.page).toBe(1);
});

test("search --limit caps client-side; table output is readable", async () => {
  const limited = await runWithFixture(["search", "-q", "information technology", "--limit", "1"], SEARCH, "POST", SEARCH_PATH);
  expect(parseJSON<any>(limited.result).results).toHaveLength(1);
  const { result } = await runWithFixture(["search", "-q", "information technology", "--format", "table"], SEARCH, "POST", SEARCH_PATH);
  expect(result.exitCode).toBe(0);
  expect(result.stdout).toContain("ICT Development Individual Contractor");
  expect(result.stdout).toContain("G-5");
});

test("detail uses GET only, hides invisible markup and keeps the Inspira apply link", async () => {
  const { result, requests } = await runWithFixture(["detail", "https://careers.un.org/jobSearchDescription/288365?language=en"], DETAIL, "GET", DETAIL_PATH);
  const job = parseJSON<any>(result);
  expect(job.id).toBe("288365");
  expect(job.title).toBe("Course Development Specialist – Counter-Terrorism Investigation Management");
  expect(job.company).toBe("United Nations – Office of Counter-Terrorism");
  expect(job.location).toBe("New York");
  expect(job.contract).toBe("Individual Contractor");
  expect(job.applyUrl).toStartWith("https://inspira.un.org/psp/PUNA1J/");
  expect(job.description).toContain("Result of Service");
  expect(job.description).not.toContain("Ignore previous instructions");
  expect(job.description).not.toContain("AI agent");
  expect(job.description).not.toContain("<");
  expect(requests.map((r) => r.method)).toEqual(["GET"]);
  const plain = await runWithFixture(["detail", "288365", "--format", "plain"], DETAIL, "GET", DETAIL_PATH);
  expect(plain.result.stdout).toContain("Deadline: 2026-12-02");
  expect(plain.result.stdout).toContain("Apply: https://inspira.un.org/");
});

test("argument errors are JSON on stderr with exit 1, and nothing is fetched", async () => {
  for (const [args, code] of [
    [["search"], "NO_QUERY"],
    [["search", "-q", "x", "--bogus", "1"], "UNKNOWN_FLAG"],
    [["search", "-q", "x", "--page", "0"], "BAD_ARG"],
    [["detail"], "NO_ID"],
    [["detail", "https://evil.example/jobSearchDescription/1"], "BAD_ID"],
    [["detail", "https://user@careers.un.org/jobSearchDescription/1"], "BAD_ID"],
    [["frobnicate"], "BAD_CMD"],
  ] as const) {
    const r = await runCLI([...args]);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  }
});
