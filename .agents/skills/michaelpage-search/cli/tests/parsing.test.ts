import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { listUrl, parseSearchPage, placePaths, postingUrl } from "../src/helpers";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("a malformed card is skipped, the rest parsed; the next-page link is read", () => {
  const p1 = parseSearchPage(fixture("list-it-wien-page1.html"));
  expect(p1.cards.map((c) => c.id)).toEqual(["jn-112026-7140475", "jn-102026-7135769", "jn-052026-7014399"]);
  expect(p1.hasNext).toBe(true);
  expect(parseSearchPage(fixture("list-it-wien-page2.html")).hasNext).toBe(false);
  expect(parseSearchPage("<html></html>")).toEqual({ cards: [], hasNext: false });
});

test("places, page URLs and posting URLs", () => {
  expect(placePaths(undefined)).toEqual(["/jobs/information-technology/wien-0"]);
  expect(placePaths("Wien,Vienna,Austria")).toEqual(["/jobs/information-technology/wien-0", "/jobs/information-technology/%C3%B6sterreich"]);
  expect(() => placePaths("Linz")).toThrow(/unknown place/);
  expect(listUrl("/jobs/information-technology/wien-0", 1)).toBe("https://www.michaelpage.at/jobs/information-technology/wien-0");
  expect(listUrl("/jobs/information-technology/wien-0", 2)).toBe("https://www.michaelpage.at/jobs/information-technology/wien-0?page=1");
  expect(postingUrl("https://www.michaelpage.at/job-detail/a-b/ref/JN-112026-7140475/")).toEqual({
    url: "https://www.michaelpage.at/job-detail/a-b/ref/jn-112026-7140475", ref: "jn-112026-7140475",
  });
  expect(postingUrl("jn-112026-7140475")).toBeNull();
  expect(postingUrl("https://www.michaelpage.at/jobs/information-technology/wien-0")).toBeNull();
});
