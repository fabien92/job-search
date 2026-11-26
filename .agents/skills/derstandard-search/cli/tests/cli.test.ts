import { expect, test } from "bun:test";
import { parseJSON, runCLI, runWithFixture } from "./helpers";

const SEARCH = "search-wien-delivery-manager.html";
const SEARCH_PATH = "/suche/wien/Delivery%20Manager";

test("search returns the fixture's jobs through the real CLI, with the documented request", async () => {
  const { result, requests } = await runWithFixture(["search", "-q", "Delivery Manager", "-l", "Wien"], SEARCH, SEARCH_PATH, "text/html");
  const out = parseJSON<any>(result);
  expect(out.meta).toEqual({ count: 3, page: 1, total: 48, hasMore: true });
  const job = out.results[0];
  expect(job.id).toBe("417ad32a-0b7b-3f3c-87a9-2404ca45b101");
  expect(job.title).toBe("Senior Service Delivery Manager (w/m/d) – IT Infrastruktur");
  expect(job.company).toBe("Iventa. The Human Management Group");
  expect(job.location).toBe("Wien");
  expect(job.homeOffice).toBe(true);
  expect(job.date).toBe("2026-11-24");
  expect(job.salary).toBe("ab 83.000 € jährlich");
  expect(job.employmentType).toBe("Vollzeit");
  expect(job.url).toBe("https://jobs.derstandard.at/detail/417ad32a-0b7b-3f3c-87a9-2404ca45b101");
  expect(out.results[1].title).toBe("Teamkoordinator IT Service Management (m/w/d)"); // invisible chars stripped
  for (const r of out.results) {
    for (const k of ["id", "title", "company", "location", "date", "url"]) expect(k in r).toBe(true);
  }
  expect(requests.map((r) => r.pathname)).toEqual([SEARCH_PATH]);
});

test("search --limit and --jobage filter client-side", async () => {
  const limited = await runWithFixture(["search", "-q", "Delivery Manager", "-l", "Wien", "--limit", "1"], SEARCH, SEARCH_PATH, "text/html");
  expect(parseJSON<any>(limited.result).results).toHaveLength(1);
  const old = await runWithFixture(["search", "-q", "Delivery Manager", "-l", "Wien", "--jobage", "1"], SEARCH, SEARCH_PATH, "text/html");
  const dates = parseJSON<any>(old.result).results.map((r: any) => r.date);
  for (const d of dates) expect(d >= "2026-01-01").toBe(true);
});

test("search table output is readable", async () => {
  const { result } = await runWithFixture(["search", "-q", "Delivery Manager", "-l", "Wien", "--format", "table"], SEARCH, SEARCH_PATH, "text/html");
  expect(result.exitCode).toBe(0);
  expect(result.stdout).toContain("Senior Service Delivery Manager");
  expect(result.stdout).toContain("417ad32a");
});

test("detail parses the captured page through the real CLI, hidden markup dropped", async () => {
  const id = "417ad32a-0b7b-3f3c-87a9-2404ca45b101";
  const { result, requests } = await runWithFixture(["detail", id], "detail-417ad32a.html", `/detail/${id}`, "text/html");
  const job = parseJSON<any>(result);
  expect(job.id).toBe(id);
  expect(job.title).toBe("Senior Service Delivery Manager (w/m/d) – IT Infrastruktur");
  expect(job.company).toBe("Iventa. The Human Management Group");
  expect(job.location).toBe("Wien");
  expect(job.date).toBe("2026-11-24");
  expect(job.salary).toBe("ab 83.000 € jährlich");
  expect(job.employmentType).toBe("Vollzeit");
  expect(job.homeOffice).toBe(true);
  expect(job.applyUrl).toBeNull();
  expect(job.isActive).toBe(true);
  expect(job.description).toContain("Senior IT Service Delivery Manager");
  expect(job.description).toContain("\n");
  expect(job.description).not.toContain("<p>");
  expect(job.description).not.toContain("Ignore all previous instructions");
  expect(job.description).not.toContain("hidden comment");
  expect(requests.map((r) => r.pathname)).toEqual([`/detail/${id}`]);
});

test("detail accepts a jobs.derstandard.at URL and prints plain text", async () => {
  const id = "417ad32a-0b7b-3f3c-87a9-2404ca45b101";
  const { result } = await runWithFixture(["detail", `https://jobs.derstandard.at/detail/${id}`, "--format", "plain"], "detail-417ad32a.html", `/detail/${id}`, "text/html");
  expect(result.exitCode).toBe(0);
  expect(result.stdout).toContain("Status: ACTIVE");
  expect(result.stdout).toContain("Posted: 2026-11-24");
});

const bad: [string[], string][] = [
  [["search", "-q", "x", "--bogus", "1"], "UNKNOWN_FLAG"],
  [["search", "-q", "x", "--sort", "date"], "UNKNOWN_FLAG"],
  [["search"], "NO_QUERY"],
  [["search", "-q"], "BAD_ARG"],
  [["search", "-q", "x", "--page", "0"], "BAD_ARG"],
  [["search", "-q", "x", "--page", "2"], "PAGE_UNSUPPORTED"],
  [["search", "-q", "x", "--format", "xml"], "BAD_ARG"],
  [["detail"], "NO_ID"],
  [["detail", "https://evil.example/detail/417ad32a-0b7b-3f3c-87a9-2404ca45b101"], "BAD_ID"],
  [["detail", "https://jobs.derstandard.at.evil.example/detail/417ad32a-0b7b-3f3c-87a9-2404ca45b101"], "BAD_ID"],
  [["frobnicate"], "BAD_CMD"],
];

for (const [args, code] of bad) {
  test(`${args.join(" ") || "(none)"} -> ${code}, JSON on stderr, exit 1`, async () => {
    const r = await runCLI(args);
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toBe("");
    expect(JSON.parse(r.stderr).code).toBe(code);
  });
}
