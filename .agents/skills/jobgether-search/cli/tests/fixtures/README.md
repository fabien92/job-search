# Fixtures

Captured from `https://jobgether.com/astroapi/ai/jobs.json` on 2026-11-26
(`keyword=project manager&locations=austria&sort=date`, limit 25), trimmed:

- `search-page1.json` — 9 real offers from pages 1–8 chosen for their `location` (Europe,
  EMEA, Anywhere, "Anywhere, United States", "Austria, Delaware (USA)"), one republished offer
  (6afede07…, URL with the original's id 6a9b1c54…), one with `salaryRange`; a zero-width space
  inserted in the first title; one malformed row (bad id, foreign URL) appended;
  `hasMore: true`.
- `search-page2.json` — 3 real offers from page 2 (Anywhere), `hasMore: false`.
- `error-400.json` — the API's answer to `locations=narnia`.
