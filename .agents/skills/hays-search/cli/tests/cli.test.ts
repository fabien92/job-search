import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixtures, type Route } from "./helpers";

const AT = "/en/jobsearch/job-offers/c/Austria/8BB21453-D8A8-11D3-AFB2-00105AB00B48";
const BOARD: Record<string, Route> = {
  [`${AT}/p/1?q=`]: { fixture: "search-page1.html" },
  [`${AT}/p/2?q=`]: { fixture: "search-page2.html" },
};
const DETAIL: Record<string, Route> = {
  "/jobsuche/stellenangebote-jobs-detail?prospectNr=903672/1": { fixture: "detail-903672.html" },
};

test("search walks every page of Austria and filters Vienna client-side (Wien / Vienna / bei Wien)", async () => {
  const { result, requests } = await runWithFixtures(["search", "-l", "Vienna"], BOARD);
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname + r.search)).toEqual([`${AT}/p/1?q=`, `${AT}/p/2?q=`]);
  expect(out.meta).toEqual({ count: 3, page: 1, total: 3, hasMore: false });
  expect(out.results.map((r: any) => r.id)).toEqual(["904003-1", "903894-1", "901080-1"]);
  const job = out.results[0];
  expect(job.title).toBe("Senior Information Security Officer (m/f/d)");
  expect(job.company).toBeNull();
  expect(job.recruiter).toBe("Hays");
  expect(job.location).toBe("Vienna");
  expect(job.date).toBe("2026-11-25"); // "25.11.26"
  expect(out.results[2].date).toBe("2026-11-18"); // "Wed Nov 18 13:26:00 CET 2026"
  expect(job.url).toBe("https://www.hays.at/jobsuche/stellenangebote-jobs-detail?prospectNr=904003/1");
  expect(job.employmentType).toBe("Permanent employment with our customer");
  expect(out.results[1].title).toBe("Elektrischer Baukoordinator (m/w/d)"); // zero-width space stripped
  expect(JSON.stringify(out)).not.toContain("Ignore previous instructions");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
});

test("without filters the site's total is kept; the malformed card is skipped", async () => {
  const out = parseJSON<any>((await runWithFixtures(["search"], BOARD)).result);
  expect(out.meta.total).toBe(22);
  expect(out.results).toHaveLength(5);
});

test("--jobage, several places, --query, --page, --limit and table output", async () => {
  const old = parseJSON<any>((await runWithFixtures(["search", "--jobage", "0"], BOARD)).result);
  expect(old.results).toEqual([]); // fixtures are from November 2026, older than 0 days by now
  const multi = parseJSON<any>((await runWithFixtures(["search", "-l", "Graz, Tirol"], BOARD)).result);
  expect(multi.results.map((r: any) => r.id)).toEqual(["903199-1", "902971-1"]);
  const q = await runWithFixtures(["search", "-q", "project manager", "--page", "1"], {
    [`${AT}/p/1?q=project%20manager`]: { fixture: "search-page2.html" },
  });
  const outq = parseJSON<any>(q.result);
  expect(outq.results.map((r: any) => r.id)).toEqual(["902971-1", "901080-1"]);
  expect(outq.meta).toEqual({ count: 2, page: 1, total: 22, hasMore: true });
  expect(parseJSON<any>((await runWithFixtures(["search", "--limit", "1"], BOARD)).result).results).toHaveLength(1);
  const t = await runWithFixtures(["search", "-l", "Wien", "--format", "table"], BOARD);
  expect(t.result.exitCode).toBe(0);
  expect(t.result.stdout).toContain("Technical Solution Manager");
});

test("detail reads the sections, JSON-LD facts and salary, and hides invisible markup", async () => {
  const { result, requests } = await runWithFixtures(["detail", "903672-1"], DETAIL);
  const job = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname + r.search)).toEqual(["/jobsuche/stellenangebote-jobs-detail?prospectNr=903672/1"]);
  expect(job.title).toBe("Governance, Risk & Compliance Product Owner (m/f/d)");
  expect(job.location).toBe("Vienna");
  expect(job.date).toBe("2026-11-24");
  expect(job.company).toBeNull();
  expect(job.industry).toBe("Versicherungen");
  expect(job.employmentType).toBe("Permanent employment with our customer (FULL_TIME, PERMANENT)");
  expect(job.salary).toContain("at least 75.000 € gross per year");
  expect(job.startDate).toBe("asap");
  expect(job.validThrough).toBeNull();
  expect(job.description).toStartWith("Posted by Hays (recruitment agency)");
  expect(job.description).toContain("Responsibilities\n• Take functional ownership");
  expect(job.description).toContain("Profile\n");
  expect(job.description).not.toContain("Ignore previous instructions");
  expect(job.description).not.toContain("AI agent");
  expect(job.description).not.toContain("<");
  const plain = await runWithFixtures(["detail", "https://www.hays.at/jobsuche/stellenangebote-jobs-detail-governance-risk-compliance-product-owner--vienna-903672/1", "--format", "plain"], DETAIL);
  expect(plain.result.stdout).toContain("Online since: 2026-11-24");
});

test("a closed opening (redirect to stelle-nicht-verfuegbar) exits 1 with NOT_FOUND", async () => {
  const { result } = await runWithFixtures(["detail", "100001/1"], {
    "/jobsuche/stellenangebote-jobs-detail?prospectNr=100001/1": { fixture: "", finalPath: "/jobsuche/stelle-nicht-verfuegbar" },
  });
  expect(result.exitCode).toBe(1);
  expect(JSON.parse(result.stderr).code).toBe("NOT_FOUND");
});

test("argument errors are JSON on stderr with exit 1, and nothing is fetched", async () => {
  for (const [args, code] of [
    [["search", "--remote", "x"], "UNKNOWN_FLAG"],
    [["search", "--page", "0"], "BAD_ARG"],
    [["search", "--jobage", "two"], "BAD_ARG"],
    [["search", "-q"], "BAD_ARG"],
    [["detail"], "NO_ID"],
    [["detail", "https://www.hays.at.evil.example/jobsuche/stellenangebote-jobs-detail-x-903672/1"], "BAD_ID"],
    [["frobnicate"], "BAD_CMD"],
  ] as const) {
    const r = await runCLI([...args]);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  }
});
