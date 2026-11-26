import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixture } from "./helpers";

test("search returns the fixture's jobs through the real CLI, with the documented request", async () => {
  const { result, requests } = await runWithFixture(
    ["search", "-q", "IT Projektmanager", "-l", "Wien", "--page", "2"],
    "search-page2.json", "/jobs", "application/json",
  );
  const out = parseJSON<any>(result);
  expect(out.meta).toEqual({ count: 4, page: 2, total: 38, hasMore: true });
  const job = out.results.find((r: any) => r.id === "10037361");
  expect(job.title).toBe("IT - Projektmanager:in");
  expect(job.company).toBe("VBV");
  expect(job.location).toBe("Wien");
  expect(job.url).toBe("https://www.karriere.at/jobs/10037361");
  for (const r of out.results) {
    for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
  }
  expect(requests).toHaveLength(1);
  const q = requests[0].searchParams;
  expect(q.get("keywords")).toBe("IT Projektmanager");
  expect(q.get("locations")).toBe("Wien");
  expect(q.get("sort")).toBe("date");
  expect(q.get("page")).toBe("2");
});

test("search --limit caps results", async () => {
  const { result } = await runWithFixture(["search", "-q", "x", "--limit", "1"], "search-page2.json", "/jobs", "application/json");
  expect(parseJSON<any>(result).results).toHaveLength(1);
});

test("detail parses the captured page through the real CLI", async () => {
  const { result, requests } = await runWithFixture(["detail", "10037361"], "detail-10037361.html", "/jobs/10037361", "text/html");
  const job = parseJSON<any>(result);
  expect(job.id).toBe("10037361");
  expect(job.title).toBe("IT - Projektmanager:in");
  expect(job.company).toBe("VBV");
  expect(job.date).toBe("2026-11-20");
  expect(job.applyUrl).toBe("https://jobs.vbv.at/register/34?referrer=karriere_at");
  expect(job.homeOffice).toBe(true);
  expect(job.salary).toBe("ab 60.000 € jährlich");
  expect(job.isActive).toBe(true);
  expect(job.description).toContain("IT - Projektmanager:in");
  expect(job.description).not.toContain("<p>");
  expect(job.description).toContain("\n");
  expect(requests.map((r) => r.pathname)).toEqual(["/jobs/10037361"]);
});

test("detail plain output is readable", async () => {
  const { result } = await runWithFixture(["detail", "https://www.karriere.at/jobs/10037361", "--format", "plain"], "detail-10037361.html", "/jobs/10037361", "text/html");
  expect(result.exitCode).toBe(0);
  expect(result.stdout).toContain("Status: ACTIVE");
  expect(result.stdout).toContain("Posted: 2026-11-20");
});

const bad: [string[], string][] = [
  [["search", "-q", "x", "--bogus", "1"], "UNKNOWN_FLAG"],
  [["search"], "NO_QUERY"],
  [["search", "-q"], "BAD_ARG"],
  [["search", "-q", "x", "--page", "0"], "BAD_ARG"],
  [["search", "-q", "x", "--jobage", "1.5"], "BAD_ARG"],
  [["search", "-q", "x", "--format", "xml"], "BAD_ARG"],
  [["search", "-q", "x", "--sort", "salary"], "BAD_ARG"],
  [["detail"], "NO_ID"],
  [["detail", "https://jobs.vbv.at/jobs/10037361"], "BAD_ID"],
  [["detail", "https://www.karriere.at.evil.io/jobs/10037361"], "BAD_ID"],
  [["frobnicate"], "BAD_CMD"],
];
for (const [args, code] of bad) {
  test(`${args.join(" ")} exits 1 with ${code} on stderr`, async () => {
    const r = await runCLI(args);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  });
}
