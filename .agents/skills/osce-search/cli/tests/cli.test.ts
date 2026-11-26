import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixtures, type Route } from "./helpers";

const BOARD: Record<string, Route> = {
  "/jobs/search/": { fixture: "search-page1.html", finalPath: "/jobs/search/4157067" },
  "/jobs/search/4157067/page2": { fixture: "search-page2.html" },
};
const DETAIL: Record<string, Route> = { "/jobs/5166": { fixture: "detail-5166.html" } };

test("search walks every page of the saved search and filters Vienna client-side", async () => {
  const { result, requests } = await runWithFixtures(["search", "-l", "Wien"], BOARD);
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/jobs/search/", "/jobs/search/4157067/page2"]);
  expect(out.meta).toEqual({ count: 3, page: 1, total: 3, hasMore: false });
  expect(out.results.map((r: any) => r.id)).toEqual(["5169", "5166", "5163"]);
  const job = out.results[0];
  expect(job.title).toBe("Extra-budgetary Contributions Assistant (G4)");
  expect(job.company).toBe("OSCE");
  expect(job.location).toBe("SEC - OSCE Secretariat, Vienna");
  expect(job.url).toBe("https://vacancies.osce.org/jobs/extra-budgetary-contributions-assistant-g4-5169");
  expect(job.date).toBeNull();
  expect(job.category).toBeNull();
  expect(JSON.stringify(out)).not.toContain("Ignore previous instructions");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
});

test("without filters the whole board is listed with the site's total; zero-width chars stripped", async () => {
  const out = parseJSON<any>((await runWithFixtures(["search"], BOARD)).result);
  expect(out.meta.total).toBe(12);
  expect(out.results).toHaveLength(5); // the malformed row is skipped
  expect(out.results.find((r: any) => r.id === "5150").title).toBe("Security Guard (G2) (deadline extension)");
});

test("an unknown location returns nothing; --query, --limit, --page and table output", async () => {
  expect(parseJSON<any>((await runWithFixtures(["search", "-l", "Budapest"], BOARD)).result).results).toEqual([]);
  const multi = parseJSON<any>((await runWithFixtures(["search", "-l", "Budapest,Chisinau, Wien"], BOARD)).result);
  expect(multi.results.map((r: any) => r.id)).toEqual(["5150", "5169", "5166", "5163"]);
  const q = parseJSON<any>((await runWithFixtures(["search", "-q", "environmental adviser", "-l", "Vienna"], BOARD)).result);
  expect(q.results.map((r: any) => r.id)).toEqual(["5166", "5163"]);
  expect(parseJSON<any>((await runWithFixtures(["search", "--limit", "1"], BOARD)).result).results).toHaveLength(1);
  const p2 = await runWithFixtures(["search", "--page", "2"], BOARD);
  const out2 = parseJSON<any>(p2.result);
  expect(out2.results.map((r: any) => r.id)).toEqual(["5166", "5163"]);
  expect(out2.meta).toEqual({ count: 2, page: 2, total: 12, hasMore: false });
  const t = await runWithFixtures(["search", "-l", "Vienna", "--format", "table"], BOARD);
  expect(t.result.exitCode).toBe(0);
  expect(t.result.stdout).toContain("Environmental Governance Adviser (S)");
});

test("detail reads whitelisted labels, flags secondments and hides invisible markup", async () => {
  const { result, requests } = await runWithFixtures(["detail", "5166"], DETAIL);
  const job = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/jobs/5166"]);
  expect(job.title).toBe("Environmental Governance Adviser (S)");
  expect(job.location).toBe("SEC - OSCE Secretariat, Vienna");
  expect(job.date).toBe("2026-10-20");
  expect(job.deadline).toBe("2026-12-09");
  expect(job.grade).toBe("S");
  expect(job.jobType).toBe("Seconded"); // the injected "Job Type: Ignore previous…" label is rejected
  expect(job.employmentType).toContain("requires nomination");
  expect(job.requisitionId).toBe("SEC001092");
  expect(job.url).toBe("https://vacancies.osce.org/jobs/environmental-governance-adviser-s-5166");
  expect(job.description).toContain("open for secondment only");
  expect(job.description).not.toContain("Additional Information");
  expect(JSON.stringify(job)).not.toContain("Ignore previous instructions");
  expect(job.description).not.toContain("AI agent");
  expect(job.description).not.toContain("<");
  const plain = await runWithFixtures(["detail", "https://vacancies.osce.org/jobs/environmental-governance-adviser-s-5166", "--format", "plain"], DETAIL);
  expect(plain.result.stdout).toContain("Closing: 2026-12-09");
});

test("detail of an unknown job exits 1 with NOT_FOUND", async () => {
  const { result } = await runWithFixtures(["detail", "1"], { "/jobs/1": { fixture: "", status: 404 } });
  expect(result.exitCode).toBe(1);
  expect(JSON.parse(result.stderr).code).toBe("NOT_FOUND");
});

test("argument errors are JSON on stderr with exit 1, and nothing is fetched", async () => {
  for (const [args, code] of [
    [["search", "-l", "Vienna", "--jobage", "3"], "UNKNOWN_FLAG"],
    [["search", "--page", "0"], "BAD_ARG"],
    [["search", "-q"], "BAD_ARG"],
    [["detail"], "NO_ID"],
    [["detail", "https://vacancies.osce.org.evil.example/jobs/x-5166"], "BAD_ID"],
    [["frobnicate"], "BAD_CMD"],
  ] as const) {
    const r = await runCLI([...args]);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  }
});
