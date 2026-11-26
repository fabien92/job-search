import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixture } from "./helpers";

const SEARCH = "search-vienna.html";
const DETAIL = "detail-1376269755.html";

test("search returns the fixture's openings with the documented request", async () => {
  const { result, requests } = await runWithFixture(["search", "-l", "Wien"], SEARCH, "/search/", "text/html");
  const out = parseJSON<any>(result);
  expect(out.meta).toEqual({ count: 3, page: 1, total: 12, hasMore: true });
  const job = out.results[0];
  expect(job.id).toBe("1376269755");
  expect(job.title).toBe("Administrative Innovation Assistant");
  expect(job.company).toBe("UNIDO");
  expect(job.location).toBe("Vienna, Austria");
  expect(job.grade).toBe("G5");
  expect(job.category).toBe("General Service");
  expect(job.deadline).toBe("2026-11-30");
  expect(job.date).toBeNull();
  expect(job.url).toBe("https://careers.unido.org/job/Vienna-Administrative-Innovation-Assistant/1376269755/");
  expect(out.results[1].title).not.toContain("​");
  expect(JSON.stringify(out)).not.toContain("Ignore previous instructions");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
  expect(requests).toHaveLength(1);
  expect(requests[0].searchParams.get("locationsearch")).toBe("Vienna");
  expect(requests[0].searchParams.get("q")).toBe("");
});

test("a location the site does not know returns nothing, not the whole board", async () => {
  const { result } = await runWithFixture(["search", "-l", "Budapest"], SEARCH, "/search/", "text/html");
  const out = parseJSON<any>(result);
  expect(out.results).toEqual([]);
  expect(out.meta.total).toBe(0);
});

test("search --limit and table output", async () => {
  const limited = await runWithFixture(["search", "-l", "Vienna", "--limit", "1"], SEARCH, "/search/", "text/html");
  expect(parseJSON<any>(limited.result).results).toHaveLength(1);
  const { result } = await runWithFixture(["search", "-q", "assistant", "-l", "Vienna", "--format", "table"], SEARCH, "/search/", "text/html");
  expect(result.exitCode).toBe(0);
  expect(result.stdout).toContain("Administrative Innovation Assistant");
});

test("detail reads microdata and hides invisible markup", async () => {
  const { result, requests } = await runWithFixture(["detail", "1376269755"], DETAIL, "/job/job/1376269755/", "text/html");
  const job = parseJSON<any>(result);
  expect(job.title).toBe("Administrative Innovation Assistant");
  expect(job.location).toBe("Vienna, Austria");
  expect(job.date).toBe("2026-11-09");
  expect(job.deadline).toBe("2026-11-30");
  expect(job.grade).toBe("G5");
  expect(job.category).toBe("General Service/Admin. Support");
  expect(job.employmentType).toBe("Staff-Full-time");
  expect(job.salary).toBe("59,439.00 EUR net per year (indicative minimum)");
  expect(job.url).toBe("https://careers.unido.org/job/Vienna-Administrative-Innovation-Assistant/1376269755/");
  expect(job.description).toContain("Requisition ID: 8186");
  expect(job.description).not.toContain("Ignore previous instructions");
  expect(job.description).not.toContain("AI agent");
  expect(job.description).not.toContain("<");
  expect(requests.map((r) => r.pathname)).toEqual(["/job/job/1376269755/"]);
  const plain = await runWithFixture(["detail", "https://careers.unido.org/job/x/1376269755/", "--format", "plain"], DETAIL, "/job/job/1376269755/", "text/html");
  expect(plain.result.stdout).toContain("Posted: 2026-11-09");
});

test("argument errors are JSON on stderr with exit 1, and nothing is fetched", async () => {
  for (const [args, code] of [
    [["search"], "NO_QUERY"],
    [["search", "-l", "Vienna", "--jobage", "3"], "UNKNOWN_FLAG"],
    [["search", "-l", "Vienna", "--page", "2"], "PAGE_UNSUPPORTED"],
    [["detail"], "NO_ID"],
    [["detail", "https://careers.unido.org.evil.example/job/x/1376269755/"], "BAD_ID"],
    [["frobnicate"], "BAD_CMD"],
  ] as const) {
    const r = await runCLI([...args]);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  }
});
