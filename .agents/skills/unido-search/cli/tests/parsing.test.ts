import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { listDate, microdataInstant, parseJobDetail, parseSearchPage } from "../src/helpers";
import { normalizeId } from "../src/commands/detail";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("a malformed row is skipped, the rest parsed", () => {
  const page = parseSearchPage(fixture("search-vienna.html"));
  expect(page.cards).toHaveLength(3);
  expect(page.total).toBe(12);
  expect(parseSearchPage("<html></html>")).toEqual({ cards: [], total: null });
});

test("dates", () => {
  expect(listDate("30-Nov-2026")).toBe("2026-11-30");
  expect(listDate("3-Jan-2027")).toBe("2027-01-03");
  expect(listDate("soon")).toBeNull();
  expect(microdataInstant("Mon Nov 30 23:00:00 UTC 2026")?.toISOString()).toBe("2026-11-30T23:00:00.000Z");
  expect(microdataInstant("garbage")).toBeNull();
});

test("detail is closed after validThrough; no title throws", () => {
  const html = fixture("detail-1376269755.html");
  expect(parseJobDetail(html, "1376269755", new Date("2026-11-30T12:00:00Z")).isActive).toBe(true);
  expect(parseJobDetail(html, "1376269755", new Date("2026-12-01T00:00:00Z")).isActive).toBe(false);
  expect(() => parseJobDetail("<html></html>", "1")).toThrow("itemprop=title");
});

test("normalizeId", () => {
  expect(normalizeId("1376269755")).toBe("1376269755");
  expect(normalizeId("careers.unido.org/job/Vienna-X/1376269755/")).toBe("1376269755");
  expect(normalizeId("https://evil.example/job/x/1376269755/")).toBeNull();
  expect(normalizeId("https://careers.unido.org/search/")).toBeNull();
});
