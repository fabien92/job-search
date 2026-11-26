import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { listUrl, parseHref, parseJobDetail, parseListing, skDate, wantedRegions } from "../src/helpers";
import { normalizeId } from "../src/commands/detail";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("listing cards and pager", () => {
  const p1 = parseListing(fixture("list-software-p1.html"), "informatika-software");
  expect(p1.cards.map((c) => c.id)).toEqual(["1488961", "1571009", "1565395"]);
  expect(p1.hasNext).toBe(true);
  expect(parseListing(fixture("list-software-p2.html"), "x").hasNext).toBe(false);
  expect(parseListing(fixture("list-sprava-p1.html"), "x").hasNext).toBe(false); // no pager at all
  expect(parseListing("<html></html>", "x")).toEqual({ cards: [], hasNext: false });
});

test("hrefs, ids, dates and regions", () => {
  expect(parseHref("pracovna-ponuka/1488961/linux-support-")).toEqual({ id: "1488961", url: "https://kariera.zoznam.sk/pracovna-ponuka/1488961/linux-support-" });
  expect(parseHref("redirect.php?type=banner_listing&amp;id=2056&amp;url=pracovna-ponuka/1528873/x")).toBeNull();
  expect(parseHref("https://evil.example/pracovna-ponuka/1488961")).toBeNull();
  expect(normalizeId("1559635")).toBe("1559635");
  expect(normalizeId("kariera.zoznam.sk/pracovna-ponuka/1559635/x-")).toBe("1559635");
  expect(normalizeId("https://kariera.zoznam.sk/reaguj-na-ponuku/1559635")).toBeNull();
  expect(normalizeId("https://u:p@kariera.zoznam.sk/pracovna-ponuka/1559635")).toBeNull();
  expect(skDate("26.11.2026")).toBe("2026-11-26");
  expect(skDate("5. 3. 2026")).toBe("2026-03-05");
  expect(skDate("31.13.2026")).toBeNull();
  expect(wantedRegions("Bratislava, Bratislavský kraj, Košice")).toEqual(["bratislavsky-kraj", "kosicky-kraj"]);
  expect(() => wantedRegions("Budapest")).toThrow(/unknown place/);
  expect(listUrl("informatika-software", "bratislavsky-kraj", 3)).toBe("https://kariera.zoznam.sk/pracovne-ponuky/informatika-software/bratislavsky-kraj?od=60");
});

test("an expired posting is inactive; a page without the detail block is an error", () => {
  expect(parseJobDetail(fixture("detail-1559635.html"), "1559635", "2027-01-10").isActive).toBe(false);
  expect(parseJobDetail(fixture("detail-1559635.html"), "1559635", "2026-11-26").isActive).toBe(true);
  expect(() => parseJobDetail("<html></html>", "1")).toThrow(/offer-detail-content/);
});
