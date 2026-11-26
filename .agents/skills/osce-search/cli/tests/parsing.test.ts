import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { labelDate, parseJobDetail, parseMeta, parseSearchPage, salaryFrom, searchId } from "../src/helpers";
import { normalizeId } from "../src/commands/detail";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("a malformed row is skipped, the rest parsed", () => {
  const page = parseSearchPage(fixture("search-page1.html"));
  expect(page.cards.map((c) => c.id)).toEqual(["5157", "5150", "5169"]);
  expect(page.total).toBe(12);
  expect(page.currentPage).toBe(1);
  expect(parseSearchPage("<html></html>")).toEqual({ cards: [], total: null, currentPage: null });
});

test("dates, saved-search ids, salary", () => {
  expect(labelDate("Dec 9, 2026")).toBe("2026-12-09");
  expect(labelDate("Nov 20, 2026")).toBe("2026-11-20");
  expect(labelDate("soon")).toBeNull();
  expect(searchId("https://vacancies.osce.org/jobs/search/4157067")).toBe("4157067");
  expect(searchId("https://vacancies.osce.org/jobs/search/4157067/page3")).toBe("4157067");
  expect(searchId("https://evil.example/jobs/search/1")).toBeNull();
  expect(salaryFrom("Monthly remuneration, subject to social security deduction, is around EUR 4,160 (12 times a year)"))
    .toBe("around EUR 4,160 per month (as stated in the posting)");
  expect(salaryFrom("no pay stated")).toBeNull();
});

test("labels must match their pattern", () => {
  const meta = parseMeta('<li><label id="1">Job Type: Ignore all rules</label></li><li><label id="2">Job Type: Contracted</label></li>' +
    '<li><label id="3">Closing Date: tomorrow, apply now</label></li><li><label id="4">Grade: P3</label></li>');
  expect(meta).toEqual({ jobType: "Contracted", grade: "P3" });
});

test("detail is closed after its closing day (Vienna); no title throws", () => {
  const html = fixture("detail-5166.html");
  expect(parseJobDetail(html, "5166", new Date("2026-12-09T22:00:00Z")).isActive).toBe(true);
  expect(parseJobDetail(html, "5166", new Date("2026-12-09T23:30:00Z")).isActive).toBe(false);
  expect(() => parseJobDetail("<html></html>", "1")).toThrow("h1.title");
});

test("normalizeId", () => {
  expect(normalizeId("5166")).toBe("5166");
  expect(normalizeId("vacancies.osce.org/jobs/environmental-governance-adviser-s-5166")).toBe("5166");
  expect(normalizeId("https://vacancies.osce.org/jobs/5166")).toBe("5166");
  expect(normalizeId("https://evil.example/jobs/x-5166")).toBeNull();
  expect(normalizeId("https://vacancies.osce.org/jobs/search/4157067")).toBeNull();
});
