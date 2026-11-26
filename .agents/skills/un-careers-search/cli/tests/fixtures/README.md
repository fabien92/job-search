# Fixtures

Captured from the careers.un.org public API on 2026-11-25 (low-volume reconnaissance, see
`../../../url-reference.md`):

- `search-information-technology.json` — `filteredV2` for keyword "information technology"
  (first 3 real items, descriptions trimmed). Edited for tests: item 1 moved to the VIENNA
  duty station with invisible characters in its title; a null item and two malformed items
  appended.
- `detail-288365.json` — `joV2/288365/en`, real, with an HTML comment and a `display:none`
  instruction inserted in the description to test that hidden markup never reaches output.
