import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { headerFields, listDate, parseJobDetail, parseSearchPage, siteLocation } from "../src/helpers";
import { normalizeId } from "../src/commands/detail";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("a malformed row is skipped, the rest parsed", () => {
  const page = parseSearchPage(fixture("search-all.html"));
  expect(page.cards).toHaveLength(3);
  expect(page.total).toBe(7);
  expect(parseSearchPage("<html></html>")).toEqual({ cards: [], total: null });
});

test("dates and location", () => {
  expect(listDate("Nov 26, 2026")).toBe("2026-11-26");
  expect(listDate("Jan 3, 2027")).toBe("2027-01-03");
  expect(listDate("soon")).toBeNull();
  expect(siteLocation("AT")).toBe("Vienna, Austria");
  expect(siteLocation("KE")).toBe("KE");
  expect(siteLocation(null)).toBeNull();
});

test("header table: labels and values must line up, else nothing", () => {
  const ok = "<table><tr><td><p>Grade:</p><p>Contract Type:</p><p>Job Category:</p></td><td><p> </p><p>P4</p><p>Fixed Term</p><p>IT</p></td></tr></table>";
  expect(headerFields(ok)).toEqual({ grade: "P4", contractType: "Fixed Term", category: "IT" });
  const shifted = "<table><tr><td><p>Grade:</p><p>Contract Type:</p><p>Job Category:</p></td><td><p>P4</p><p>IT</p></td></tr></table>";
  expect(headerFields(shifted)).toEqual({});
  expect(headerFields(null)).toEqual({});
});

test("detail closes after its deadline; no title throws", () => {
  const html = fixture("detail-1376928157.html");
  expect(parseJobDetail(html, "1376928157", new Date("2026-12-06T22:00:00Z")).isActive).toBe(true);
  expect(parseJobDetail(html, "1376928157", new Date("2026-12-06T23:30:00Z")).isActive).toBe(false);
  expect(() => parseJobDetail("<html></html>", "1")).toThrow("itemprop=title");
});

test("normalizeId", () => {
  expect(normalizeId("1376928157")).toBe("1376928157");
  expect(normalizeId("careers.opecfund.org/job/Head-of-Loan-Management/1376928157/")).toBe("1376928157");
  expect(normalizeId("https://evil.example/job/x/1376928157/")).toBeNull();
  expect(normalizeId("https://careers.opecfund.org/search/")).toBeNull();
});
