import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { extractJsObject, formatSalary, parseJobDetail, parseSearchPage, viennaDate } from "../src/helpers";
import { buildUrl, locationSlug } from "../src/commands/search";
import { normalizeId } from "../src/commands/detail";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("Apollo payload: undefined outside strings becomes null, inside strings is kept", () => {
  const src = 'push({"a":undefined,"b":"undefined value","c":[undefined],"d":{"e":"x\\"undefined"}})';
  expect(extractJsObject(src, 0)).toEqual({ a: null, b: "undefined value", c: [null], d: { e: 'x"undefined' } });
});

test("one malformed edge never breaks the others", () => {
  const page = parseSearchPage(fixture("search-wien-delivery-manager.html"));
  expect(page.cards.map((c) => c.id.slice(0, 8))).toEqual(["417ad32a", "cfcfc22d", "063733bd"]);
  expect(page.total).toBe(48);
});

test("a page without jobListings is a loud error, not an empty result", () => {
  expect(() => parseSearchPage("<html><body>nothing</body></html>")).toThrow(/jobListings/);
});

test("dates are Vienna calendar dates", () => {
  expect(viennaDate("2026-11-24T23:30:00Z")).toBe("2026-11-25");
  expect(viennaDate("garbage")).toBeNull();
});

test("salary and URLs", () => {
  expect(formatSalary(83000, "YEARLY")).toBe("ab 83.000 € jährlich");
  expect(formatSalary(3200, "MONTHLY")).toBe("ab 3.200 € monatlich");
  expect(formatSalary(null, "YEARLY")).toBeNull();
  expect(locationSlug("Niederösterreich")).toBe("niederoesterreich");
  expect(locationSlug("St. Pölten")).toBe("st-poelten");
  expect(locationSlug(undefined)).toBe("oesterreich");
  expect(buildUrl({ query: "IT Projektmanager", location: "Wien", page: 1, format: "json" }))
    .toBe("https://jobs.derstandard.at/suche/wien/IT%20Projektmanager");
  expect(buildUrl({ location: "Graz", page: 1, format: "json" })).toBe("https://jobs.derstandard.at/suche/graz/alle");
});

test("detail id normalisation rejects other hosts", () => {
  const id = "417ad32a-0b7b-3f3c-87a9-2404ca45b101";
  expect(normalizeId(id.toUpperCase())).toBe(id);
  expect(normalizeId(`jobs.derstandard.at/detail/${id}`)).toBe(id);
  expect(normalizeId(`https://user@jobs.derstandard.at/detail/${id}`)).toBeNull();
  expect(normalizeId(`https://derstandard.at/detail/${id}`)).toBeNull();
  expect(normalizeId("12345")).toBeNull();
});

test("expired posting is reported inactive", () => {
  const html = '<script type="application/ld+json">{"@type":"JobPosting","title":"X","validThrough":"2026-01-01T00:00:00Z","datePosted":"2025-12-01T00:00:00Z"}</script>';
  expect(parseJobDetail(html, "417ad32a-0b7b-3f3c-87a9-2404ca45b101", "2026-11-25").isActive).toBe(false);
});
