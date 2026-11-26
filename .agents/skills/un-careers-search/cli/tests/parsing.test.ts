import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { grade, locationCode, parseJobDetail, parseSearchData, titleCase } from "../src/helpers";
import { normalizeId } from "../src/commands/detail";
import { buildBody, spanFor } from "../src/commands/search";

const fixture = (name: string) => JSON.parse(readFileSync(join(import.meta.dir, "fixtures", name), "utf8")).data;

test("malformed items are skipped, the rest parsed", () => {
  const page = parseSearchData(fixture("search-information-technology.json"));
  expect(page.cards.map((c) => c.id)).toEqual(["289094", "288522", "280754"]);
  expect(page.total).toBe(14);
  expect(() => parseSearchData({})).toThrow("data.list");
});

test("location codes, grades and title case", () => {
  expect(locationCode("Wien")).toBe("VIENNA");
  expect(locationCode("Vienna")).toBe("VIENNA");
  expect(locationCode("Addis Ababa")).toBe("ADDIS ABABA");
  expect(locationCode("Genève")).toBe("GENEVE");
  expect(grade("P3")).toBe("P-3");
  expect(grade("G-6")).toBe("G-6");
  expect(grade("CON")).toBe("CON");
  expect(titleCase("NEW YORK")).toBe("New York");
  expect(titleCase("Vienna")).toBe("Vienna");
});

test("jobage maps to the portal's 1/7/30-day span", () => {
  expect(spanFor(undefined)).toBeNull();
  expect(spanFor(1)).toBe("1");
  expect(spanFor(2)).toBe("7");
  expect(spanFor(30)).toBe("30");
  expect(spanFor(45)).toBeNull();
  expect(buildBody({ query: " it ", location: "Wien", jobage: 5, page: 1, format: "json" }).filterConfig).toEqual({ keyword: "it", ds: ["VIENNA"], span: ["7"] });
  expect(buildBody({ page: 3, format: "json" })).toEqual({
    filterConfig: {},
    pagination: { page: 2, itemPerPage: 100, sortBy: "startDate", sortDirection: -1 },
  });
});

test("detail: closed after the deadline; apply link only on inspira.un.org over https", () => {
  const data = fixture("detail-288365.json");
  expect(parseJobDetail(data, new Date("2026-11-26T00:00:00Z")).isActive).toBe(true);
  expect(parseJobDetail(data, new Date("2026-12-03T00:00:00Z")).isActive).toBe(false);
  expect(parseJobDetail({ ...data, inspiraURL: "https://inspira.un.org.evil.example/x" }).applyUrl).toBeNull();
  expect(parseJobDetail({ ...data, inspiraURL: "http://inspira.un.org/x" }).applyUrl).toBeNull();
  expect(() => parseJobDetail({})).toThrow();
});

test("normalizeId accepts ids and careers.un.org URLs only", () => {
  expect(normalizeId("289094")).toBe("289094");
  expect(normalizeId("careers.un.org/jobSearchDescription/289094")).toBe("289094");
  expect(normalizeId("https://careers.un.org/jobSearchDescription/289094?language=en")).toBe("289094");
  expect(normalizeId("https://careers.un.org.evil.example/jobSearchDescription/1")).toBeNull();
  expect(normalizeId("https://careers.un.org/other/1")).toBeNull();
  expect(normalizeId("abc")).toBeNull();
});
