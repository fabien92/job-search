import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixtures, type Route } from "./helpers";

const WIEN: Record<string, Route> = {
  "/jobs/wien/wien/": { fixture: "list-wien-page1.html" },
  "/jobs/wien/wien/page-2/": { fixture: "list-wien-page2.html" },
};
const CANONICAL = "/jobs/senior-project-manager-mit-fokus-implementierung-mwd_wien_47720442/";
const DETAIL: Record<string, Route> = {
  "/jobs/job_wien_47720442/": { fixture: "detail-47720442.html", finalPath: CANONICAL },
};

test("search walks every page of the Vienna listing and parses the cards", async () => {
  const { result, requests } = await runWithFixtures(["search", "-l", "Wien,Vienna,Vienne"], WIEN);
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/jobs/wien/wien/", "/jobs/wien/wien/page-2/"]);
  expect(out.meta).toEqual({ count: 5, page: 1, total: 33, hasMore: false });
  expect(out.results.map((r: any) => r.id)).toEqual(["47720442", "47569632", "47607006", "47815606", "47730596"]);
  const job = out.results[0];
  expect(job.title).toBe("Senior Project Manager mit Fokus Implementierung (m/w/d)"); // zero-width space stripped
  expect(job.company).toBeNull();
  expect(job.recruiter).toBe("Randstad");
  expect(job.location).toBe("Wien, Wien");
  expect(job.date).toBe("2026-11-06");
  expect(job.url).toBe(`https://www.randstad.at${CANONICAL}`);
  expect(job.employmentType).toBe("Festanstellung");
  expect(job.salary).toBe("€4,500 pro monat");
  expect(out.results[1].date).toBe("2026-10-08");
  expect(JSON.stringify(out)).not.toContain("IGNORE PREVIOUS INSTRUCTIONS");
  for (const r of out.results) for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
});

test("-s edv-it walks only the IT listing of Vienna; an empty Berufsfeld listing is no error", async () => {
  const { result, requests } = await runWithFixtures(["search", "-l", "Wien", "-s", "edv-it"], {
    "/jobs/s-edv-it/wien/wien/": { fixture: "list-it-wien.html" },
  });
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/jobs/s-edv-it/wien/wien/"]); // total 2: no page-2
  expect(out.meta).toEqual({ count: 2, page: 1, total: 2, hasMore: false });
  expect(out.results.map((r: any) => r.title)).toEqual(["Senior DevOps / Platform Engineer (m/f/d)", "DevOps / Platform Engineer (m/f/d)"]);
  expect(out.results[0].date).toBe("2026-11-05");
  const empty = await runWithFixtures(["search", "-l", "Graz", "--specialism", "edv-it"], {
    "/jobs/s-edv-it/steiermark/graz/": { fixture: "" }, // 200, no cards, no heading
  });
  expect(parseJSON<any>(empty.result).meta).toEqual({ count: 0, page: 1, total: 0, hasMore: false });
  const bad = await runWithFixtures(["search", "-l", "Wien", "-s", "qt-it"], {});
  expect(bad.result.exitCode).toBe(1);
  expect(JSON.parse(bad.result.stderr).code).toBe("BAD_ARG");
  expect(bad.requests).toEqual([]);
});

test("without -l the whole of Austria is walked from /jobs/", async () => {
  const { result, requests } = await runWithFixtures(["search", "--page", "1"], {
    "/jobs/": { fixture: "list-wien-page1.html" },
  });
  const out = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/jobs/"]);
  expect(out.meta).toEqual({ count: 3, page: 1, total: 33, hasMore: true });
});

test("--jobage, --limit, table output and unknown places", async () => {
  const old = parseJSON<any>((await runWithFixtures(["search", "-l", "Wien", "--jobage", "0"], WIEN)).result);
  expect(old.results).toEqual([]); // fixtures are from 2026, older than 0 days by now
  expect(parseJSON<any>((await runWithFixtures(["search", "-l", "Wien", "--limit", "1"], WIEN)).result).results).toHaveLength(1);
  const t = await runWithFixtures(["search", "-l", "Wien", "--format", "table"], WIEN);
  expect(t.result.exitCode).toBe(0);
  expect(t.result.stdout).toContain("DevOps");
  const bad = await runWithFixtures(["search", "-l", "Innsbruck"], WIEN);
  expect(bad.result.exitCode).toBe(1);
  expect(JSON.parse(bad.result.stderr).code).toBe("BAD_ARG");
  expect(bad.requests).toEqual([]);
});

test("detail follows the id redirect, reads the summary box and hides invisible markup", async () => {
  const { result, requests } = await runWithFixtures(["detail", "47720442"], DETAIL);
  const job = parseJSON<any>(result);
  expect(requests.map((r) => r.pathname)).toEqual(["/jobs/job_wien_47720442/"]);
  expect(job.title).toBe("Senior Project Manager mit Fokus Implementierung (m/w/d)");
  expect(job.url).toBe(`https://www.randstad.at${CANONICAL}`);
  expect(job.company).toBeNull();
  expect(job.location).toBe("Wien, Wien");
  expect(job.date).toBe("2026-11-06");
  expect(job.validThrough).toBe("2027-01-04"); // "4. Jänner 2027"
  expect(job.employmentType).toBe("Festanstellung");
  expect(job.hours).toBe("Full-Time");
  expect(job.salary).toBe("€4,500 pro monat");
  expect(job.specialism).toBe("Lager, Logistik & Transport");
  expect(job.reference).toBe("SENIO09509");
  expect(job.description).toStartWith("Posted by Randstad (staffing agency)");
  expect(job.description).toContain("Ihre Aufgaben");
  expect(job.description).toContain("• Hands-on Implementierung");
  expect(job.description).not.toContain("score this");
  expect(job.description).not.toContain("Ignore the rubric");
});

test("detail accepts a posting URL; a closed opening (410) is NOT_FOUND; foreign URLs are refused", async () => {
  const viaUrl = await runWithFixtures(["detail", `https://www.randstad.at${CANONICAL}`], DETAIL);
  expect(parseJSON<any>(viaUrl.result).id).toBe("47720442");
  const gone = await runWithFixtures(["detail", "40000001"], { "/jobs/job_wien_40000001/": { fixture: "", status: 410 } });
  expect(gone.result.exitCode).toBe(1);
  expect(JSON.parse(gone.result.stderr).code).toBe("NOT_FOUND");
  const foreign = await runCLI(["detail", "https://evil.example/jobs/x_wien_47720442/"]);
  expect(JSON.parse(foreign.stderr).code).toBe("BAD_ID");
});

test("flags are validated, never silently ignored", async () => {
  for (const args of [["search", "-q", "manager"], ["search", "--page", "0"], ["search", "--format", "xml"], ["search", "-l"], ["search", "-s"]]) {
    const r = await runCLI(args);
    expect(r.exitCode).toBe(1);
  }
  expect(JSON.parse((await runCLI(["search", "-q", "manager"])).stderr).code).toBe("UNKNOWN_FLAG");
});
