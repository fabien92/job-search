import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { germanDate, listUrl, parseSearchPage, placePaths } from "../src/helpers";
import { normalizeId } from "../src/commands/detail";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("a malformed card is skipped, the rest parsed; no cards means total 0", () => {
  const page = parseSearchPage(fixture("list-wien-page1.html"));
  expect(page.cards.map((c) => c.id)).toEqual(["47720442", "47569632", "47607006"]);
  expect(page.total).toBe(33);
  expect(parseSearchPage("<html></html>")).toEqual({ cards: [], total: 0 });
  expect(parseSearchPage('<h1 class="sortbar__count">1.234 Jobs gefunden</h1>').total).toBe(1234);
  expect(parseSearchPage(fixture("list-it-wien.html")).total).toBe(2); // "2 EDV &amp; IT Jobs in Wien, Wien für Sie gefunden"
  expect(parseSearchPage('<h1 class="sortbar__count">1 EDV &amp; IT Job in Wien, Wien für Sie gefunden</h1>').total).toBe(1);
});

test("German dates, Austrian month names included", () => {
  expect(germanDate("veröffentlicht am 8. Oktober 2026")).toBe("2026-10-08");
  expect(germanDate("gültig bis 4. Jänner 2027")).toBe("2027-01-04");
  expect(germanDate("1. März 2027")).toBe("2027-03-01");
  expect(germanDate("3. Feber 2027")).toBe("2027-02-03");
  expect(germanDate("32. Mai 2027")).toBeNull();
  expect(germanDate("bald")).toBeNull();
  expect(germanDate("heute gepostet", "2026-11-26")).toBe("2026-11-26");
  expect(germanDate("vor 1 Tag veröffentlicht", "2026-11-26")).toBe("2026-11-25");
  expect(germanDate("vor 30 Tagen veröffentlicht", "2026-03-01")).toBe("2026-01-30");
  expect(germanDate("nur noch heute gültig", "2026-11-26")).toBe("2026-11-26");
  expect(germanDate("noch 1 Tag gültig", "2026-12-31")).toBe("2027-01-01");
  expect(germanDate("noch 6 Tage gültig", "2026-11-26")).toBe("2026-12-02");
});

test("places map to listing paths; ids and URLs", () => {
  expect(placePaths("Wien,Vienna,Graz")).toEqual(["/jobs/wien/wien/", "/jobs/steiermark/graz/"]);
  expect(placePaths(undefined)).toEqual(["/jobs/"]);
  expect(() => placePaths("Bratislava")).toThrow(/unknown place/);
  expect(placePaths("Wien,Graz", "edv-it")).toEqual(["/jobs/s-edv-it/wien/wien/", "/jobs/s-edv-it/steiermark/graz/"]);
  expect(placePaths(undefined, "EDV-IT")).toEqual(["/jobs/s-edv-it/"]);
  expect(() => placePaths("Wien", "it")).toThrow(/unknown specialism/);
  expect(listUrl("/jobs/wien/wien/", 1)).toBe("https://www.randstad.at/jobs/wien/wien/");
  expect(listUrl("/jobs/", 3)).toBe("https://www.randstad.at/jobs/page-3/");
  expect(normalizeId("47720442")).toBe("47720442");
  expect(normalizeId("www.randstad.at/jobs/buchhalterin-mwd_wien_47821027/")).toBe("47821027");
  expect(normalizeId("https://www.randstad.at/jobs/bewerben/47720442")).toBeNull();
  expect(normalizeId("https://user:pw@www.randstad.at/jobs/x_wien_47720442/")).toBeNull();
  expect(normalizeId("12")).toBeNull();
});
