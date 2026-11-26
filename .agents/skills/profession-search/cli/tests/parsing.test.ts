import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "path";
import { feedUrl, fold, parseFeed, parseJobDetail, parseLink, slugPlace, wantedPlaces } from "../src/helpers";
import { normalizeId } from "../src/commands/detail";

const fixture = (name: string) => readFileSync(join(import.meta.dir, "fixtures", name), "utf8");

test("feed items: malformed and foreign links skipped, duplicates once", () => {
  const xml = fixture("rss-it.rss");
  expect(parseFeed(xml).map((c) => c.id)).toEqual(["3059519", "3058862", "3059477", "3047267", "3055291"]);
  const twice = xml.replace("</channel>", xml.match(/<item>[\s\S]*?<\/item>/)![0] + "</channel>");
  expect(parseFeed(twice)).toHaveLength(5);
  expect(parseFeed("<rss></rss>")).toEqual([]);
});

test("links, slugs and places", () => {
  expect(parseLink("https://www.profession.hu/allas/sap-rendszeruzemelteto-budapest-3058862/p/569")).toEqual({
    id: "3058862", slug: "sap-rendszeruzemelteto-budapest-3058862", url: "https://www.profession.hu/allas/sap-rendszeruzemelteto-budapest-3058862",
  });
  expect(parseLink("https://www.profession.hu/allas/x-kft-3059477/optimum/p/569")?.id).toBe("3059477");
  expect(parseLink("https://www.profession.hu/allasok/budapest/1,0,23")).toBeNull();
  expect(parseLink("https://stat.profession.hu/allas/x-3058862")).toBeNull();
  expect(slugPlace("it-szerviztechnikus-szekesfehervar-es-kornyeke-laurel-kft-3055411")).toBe("Székesfehérvár");
  expect(slugPlace("senior-sap-fi-co-consultant-avl-erd-3047529")).toBe("Érd");
  expect(slugPlace("pos-uzemeltetesi-szakerto-magyar-posta-zrt-3055291")).toBeNull();
  expect(fold("Győr")).toBe("gyor");
  expect(wantedPlaces("Budapest, Győr")).toEqual(new Set(["budapest", "gyor"]));
  expect(wantedPlaces(undefined)).toBeNull();
  expect(() => wantedPlaces("Bratislava")).toThrow(/unknown place/);
  expect(feedUrl("it")).toBe("https://www.profession.hu/partner/files/rss-it.rss");
  expect(normalizeId("3058862")).toBe("3058862");
  expect(normalizeId("www.profession.hu/allas/sap-budapest-3058862")).toBe("3058862");
  expect(normalizeId("https://www.profession.hu/jelentkezes/3058862")).toBeNull();
  expect(normalizeId("https://user:pw@www.profession.hu/allas/x-3058862")).toBeNull();
  expect(normalizeId("12")).toBeNull();
});

test("an expired posting is inactive; a page without JobPosting is an error", () => {
  const job = parseJobDetail(fixture("detail-3058862.html"), "3058862", "2027-01-10");
  expect(job.isActive).toBe(false);
  expect(parseJobDetail(fixture("detail-3058862.html"), "3058862", "2026-11-26").isActive).toBe(true);
  expect(() => parseJobDetail("<html></html>", "1")).toThrow(/JobPosting/);
});
