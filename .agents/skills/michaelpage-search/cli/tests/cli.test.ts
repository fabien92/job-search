import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixtures, type Route } from "./helpers";

const WIEN: Record<string, Route> = {
  "/jobs/information-technology/wien-0": { fixture: "list-it-wien-page1.html" },
  "/jobs/information-technology/wien-0?page=1": { fixture: "list-it-wien-page2.html" },
};
const PATH = "/job-detail/project-service-delivery-manager-wmd/ref/jn-112026-7140475";
const DETAIL: Record<string, Route> = { [PATH]: { fixture: "detail-jn-112026-7140475.html" } };

test("search walks both pages of the Vienna IT listing and parses the cards", async () => {
  const { result, requests } = await runWithFixtures(["search", "-l", "Wien,Vienna"], WIEN);
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname + r.search)).toEqual(["/jobs/information-technology/wien-0", "/jobs/information-technology/wien-0?page=1"]);
  expect(out.meta).toEqual({ count: 5, page: 1, total: 5, hasMore: false });
  expect(out.results.map((r: any) => r.id)).toEqual([
    "jn-112026-7140475", "jn-102026-7135769", "jn-052026-7014399", "jn-102026-7125856", "jn-082026-7086455",
  ]);
  const job = out.results[0];
  expect(job.title).toBe("Project & Service Delivery Manager (w/m/d)"); // zero-width space stripped
  expect(job.company).toBeNull();
  expect(job.recruiter).toBe("Michael Page");
  expect(job.location).toBe("Wien");
  expect(job.date).toBeNull();
  expect(job.url).toBe(`https://www.michaelpage.at${PATH}`);
  expect(job.employmentType).toBe("Festanstellung");
  expect(job.salary).toBe("63.000€ - 85.000€ p.a.");
  expect(job.homeOffice).toBe("Home Office");
  expect(job.summary).toContain("IT-Projekte");
  expect(JSON.stringify(out)).not.toContain("IGNORE PREVIOUS INSTRUCTIONS");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
});

test("default place is Vienna; Austria; --page, --query, --limit, table; unknown places", async () => {
  const one = await runWithFixtures(["search", "--page", "1"], WIEN);
  expect(one.requests.map((r) => r.pathname + r.search)).toEqual(["/jobs/information-technology/wien-0"]);
  expect(parseJSON<any>(one.result).meta).toEqual({ count: 3, page: 1, total: null, hasMore: true });
  const at = await runWithFixtures(["search", "-l", "Österreich", "--page", "2"], {
    "/jobs/information-technology/%C3%B6sterreich?page=1": { fixture: "list-it-wien-page2.html" },
  });
  expect(parseJSON<any>(at.result).meta.hasMore).toBe(false);
  const q = parseJSON<any>((await runWithFixtures(["search", "-q", "DELIVERY manager"], WIEN)).result);
  expect(q.results.map((r: any) => r.id)).toEqual(["jn-112026-7140475"]);
  expect(parseJSON<any>((await runWithFixtures(["search", "--limit", "1"], WIEN)).result).results).toHaveLength(1);
  const t = await runWithFixtures(["search", "--format", "table"], WIEN);
  expect(t.result.stdout).toContain("Microsoft SQL Server Consultant");
  const bad = await runWithFixtures(["search", "-l", "Graz"], WIEN);
  expect(JSON.parse(bad.result.stderr).code).toBe("BAD_ARG");
  expect(bad.requests).toEqual([]);
});

test("detail reads the JSON-LD JobPosting and hides invisible markup", async () => {
  const { result, requests } = await runWithFixtures(["detail", `https://www.michaelpage.at${PATH}`], DETAIL);
  const job = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual([PATH]);
  expect(job.id).toBe("jn-112026-7140475");
  expect(job.title).toBe("Project & Service Delivery Manager (w/m/d)");
  expect(job.company).toBeNull();
  expect(job.location).toBe("Wien, Österreich");
  expect(job.date).toBe("2026-11-04");
  expect(job.employmentType).toBe("FULL_TIME");
  expect(job.homeOffice).toBe("Remote (TELECOMMUTE)");
  expect(job.salary).toBe("63.000€ - 85.000€ p.a.");
  expect(job.industry).toBe("Information Technology");
  expect(job.description).toStartWith("Posted by Michael Page (recruitment agency)");
  expect(job.description).toContain("Firmenprofil");
  expect(job.description).toContain("• flexible Arbeitszeiten");
  expect(job.description).not.toContain("score this");
  expect(job.description).not.toContain("Ignore the rubric");
});

test("detail: URL without scheme, closed opening (404), bare ref and foreign URLs refused", async () => {
  expect(parseJSON<any>((await runWithFixtures(["detail", `www.michaelpage.at${PATH}`], DETAIL)).result).id).toBe("jn-112026-7140475");
  const gone = await runWithFixtures(["detail", "https://www.michaelpage.at/job-detail/x/ref/jn-112026-0000001"], {
    "/job-detail/x/ref/jn-112026-0000001": { fixture: "", status: 404 },
  });
  expect(JSON.parse(gone.result.stderr).code).toBe("NOT_FOUND");
  const bare = await runCLI(["detail", "jn-112026-7140475"]);
  expect(JSON.parse(bare.stderr).code).toBe("BAD_ID");
  expect(JSON.parse(bare.stderr).error).toContain("slug");
  for (const u of ["https://evil.example" + PATH, "https://www.michaelpage.at/job-apply/jn-112026-7140475", "https://u:p@www.michaelpage.at" + PATH]) {
    expect(JSON.parse((await runCLI(["detail", u])).stderr).code).toBe("BAD_ID");
  }
});

test("flags are validated, never silently ignored", async () => {
  for (const args of [["search", "--jobage", "3"], ["search", "--page", "0"], ["search", "--format", "xml"], ["search", "-l"], ["search", "-q"], ["detail"]]) {
    const r = await runCLI(args);
    expect(r.exitCode).toBe(1);
  }
  expect(JSON.parse((await runCLI(["search", "--jobage", "3"])).stderr).code).toBe("UNKNOWN_FLAG");
});
