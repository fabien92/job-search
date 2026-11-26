import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixture } from "./helpers";

const SEARCH = "search-all.html";
const DETAIL = "detail-1376928157.html";
const search = (args: string[]) => runWithFixture(["search", ...args], SEARCH, "/search/", "text/html");

test("search lists the board with the documented request; AT becomes the Vienna HQ", async () => {
  const { result, requests } = await search(["-l", "Wien"]);
  const out = parseJSON<any>(result);
  expect(out.meta).toEqual({ count: 3, page: 1, total: 3, hasMore: true }); // the trimmed fixture says 7, holds 3
  const job = out.results[0];
  expect(job.id).toBe("1368064557");
  expect(job.title).toBe("Senior Risk Policy Officer"); // zero-width space stripped
  expect(job.company).toBe("OPEC Fund for International Development");
  expect(job.location).toBe("Vienna, Austria");
  expect(job.date).toBe("2026-11-26");
  expect(job.url).toBe("https://careers.opecfund.org/job/Senior-Risk-Policy-Officer/1368064557/");
  expect(JSON.stringify(out)).not.toContain("Ignore previous instructions");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
  expect(requests).toHaveLength(1);
  expect(requests[0].searchParams.get("q")).toBe("");
});

test("location list, unknown location, --query, --jobage, --limit, table", async () => {
  expect(parseJSON<any>((await search(["-l", "Budapest"])).result).results).toEqual([]);
  expect(parseJSON<any>((await search(["-l", "Bratislava,Vienna"])).result).results).toHaveLength(3);
  expect(parseJSON<any>((await search(["-q", "investment analyst"])).result).results.map((r: any) => r.id)).toEqual(["1361322057"]);
  // --jobage depends on today's clock: check the parsed dates, and a window that keeps everything
  const all = parseJSON<any>((await search([])).result);
  expect(all.meta.total).toBe(7);
  expect(all.results.map((r: any) => r.date)).toEqual(["2026-11-26", "2026-11-21", "2026-11-06"]);
  expect(parseJSON<any>((await search(["--jobage", "100000"])).result).results).toHaveLength(3);
  expect(parseJSON<any>((await search(["--limit", "1"])).result).results).toHaveLength(1);
  const t = await search(["-l", "Vienna", "--format", "table"]);
  expect(t.result.exitCode).toBe(0);
  expect(t.result.stdout).toContain("Head of Loan Management");
});

test("detail reads microdata and the header table, hides invisible markup", async () => {
  const { result, requests } = await runWithFixture(["detail", "1376928157"], DETAIL, "/job/job/1376928157/", "text/html");
  const job = parseJSON<any>(result);
  expect(job.title).toBe("Head of Loan Management");
  expect(job.location).toBe("Vienna, Austria");
  expect(job.date).toBe("2026-11-06");
  expect(job.deadline).toBe("2026-12-06");
  expect(job.grade).toBe("H1");
  expect(job.category).toBe("Management");
  expect(job.department).toBe("Finance / Financial Administration");
  expect(job.employmentType).toBe("Fixed Term Contract · International / Local");
  expect(job.url).toBe("https://careers.opecfund.org/job/Head-of-Loan-Management/1376928157/");
  expect(job.description).toContain("all nationalities are eligible");
  expect(job.description).not.toContain("Ignore previous instructions");
  expect(job.description).not.toContain("AI agent");
  expect(job.description).not.toContain("<");
  expect(requests.map((r) => r.pathname)).toEqual(["/job/job/1376928157/"]);
  const plain = await runWithFixture(["detail", "https://careers.opecfund.org/job/x/1376928157/", "--format", "plain"], DETAIL, "/job/job/1376928157/", "text/html");
  expect(plain.result.stdout).toContain("Posted: 2026-11-06");
});

test("argument errors are JSON on stderr with exit 1, and nothing is fetched", async () => {
  for (const [args, code] of [
    [["search", "--jobage", "x"], "BAD_ARG"],
    [["search", "--remote", "yes"], "UNKNOWN_FLAG"],
    [["search", "--page", "2"], "PAGE_UNSUPPORTED"],
    [["detail"], "NO_ID"],
    [["detail", "https://careers.opecfund.org.evil.example/job/x/1376928157/"], "BAD_ID"],
    [["frobnicate"], "BAD_CMD"],
  ] as const) {
    const r = await runCLI([...args]);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  }
});
