# Template: moncv-awesome

- **Type:** CV
- **Source extension:** .tex
- **Engine/toolchain:** lualatex
- **Page limit:** 2 page(s)
- **Fonts:** Source Sans 3 (body) and Roboto (class header macros) — the TeX Live OTF files (`fonts/opentype/adobe/sourcesans/SourceSans3-*.otf`, `fonts/opentype/google/roboto/Roboto-*.otf`), loaded by file name with `Renderer=Node`; no system font needed. Icons via Font Awesome 6 (`fontawesome6` package)
- **Class/packages:** `awesome-cv.cls` v1.6.1 (bundled in this folder); fontspec, unicode-math, fontawesome6, tcolorbox, tabularx, enumitem, ulem, graphicx, hyperref, afterpage — all standard TeX Live packages

## Compile command

    cd cv && rm -f <file>.pdf && mkdir -p build && lualatex -interaction=nonstopmode -output-directory=build <file>.tex && mv build/<file>.pdf ./

## Style rules

- **Paths:** keep the first line `\def\tpl{../templates/cv/moncv-awesome}` before `\documentclass`; every class/icon path goes through `\tpl` (`\documentclass[11pt, a4paper]{\tpl/awesome-cv}`, `\tpl/icons/*.png`). Compiling from `cv/` needs exactly that value.
- **Geometry and colours are fixed:** `left=1.3cm, top=0.8cm, right=1.3cm, bottom=1.4cm, footskip=0.4cm`; `\colorlet{awesome}{awesome-red}`, `acvSectionColorHighlight` true, `accent` = `0A66C2`, name colour `1F1F1F`. Do not change them per application.
- **Header:** name 31 pt bold; headline 16 pt dark grey with three roles separated by `\textbullet`; a two-column contact table (mail, phone / location, LinkedIn / languages) with PNG icons; photo 3.25 cm square on the right. Email and phone stay as literal text inside `\href` (ATS reads them).
- **Section order:** Profile → Key Achievements → Professional Experience → Education → Additional Training → Technical Skills → Functional Skills → Languages. Section titles in English (`\cvsection{...}`).
- **Profile:** one `\cvparagraph{}` of 4-6 sentences, tailored per posting.
- **Key Achievements:** exactly 3 `\item \textbf{Title} --- description` bullets with measurable results.
- **Experience:** employer line `\textbf{Employer} \hfill dates | country`; role line `{\large \textbf{Title}} \hfill dates`; optional `Environment:` line; bullets grouped under `\textbf{\uline{Label}}` sub-headings, each list starting with `\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}`. Earlier employers may use `{\large \textbf{Title, Employer}}`.
- **Dates:** `MM/YYYY -- MM/YYYY` (`-- Present` for the current role).
- **Technical Skills:** 3 × 3 grid (`tabularx` with `X X X`, rows separated by `\\[10mm]`), one bold group title + comma-separated skills per cell. **Functional Skills:** 2 × 2 grid of `0.47\textwidth` minipages. **Languages:** 3-column `tabularx`.
- **Photo:** `[YOUR_PHOTO_PATH]` is relative to the compile directory. Use the candidate's own photo file (never commit it — `*.jpg`/`*.jpeg` are gitignored); if no photo is wanted, delete the right-hand header minipage and widen the left one to `\textwidth`.

## Known pitfalls

- **Manual page break:** `\newpage` after the current employer splits the CV into two pages. When content grows or shrinks, move this break (never let a role title sit alone at the bottom of page 1) and re-check that the result is exactly 2 pages.
- **Engine:** lualatex. The class loads the fonts by file name (`Extension=.otf`), a luaotfload lookup in the TeX tree; do not switch back to family names (`Source Sans 3`), which pick the system TTF in `/Library/Fonts`.
- **Font change of 2026-11-24:** the original loaded the system TTFs by family name with `Renderer=HarfBuzz`; every hyphen in the PDF text layer then came out as U+00AD (soft hyphen), so "on-call" or "end-to-end" could be missed by ATS parsers. The TeX Live OTFs with `Renderer=Node` give the same metrics and identical line and page breaks (checked on the full English CV) and map hyphens to ASCII `-`.
- **Sandboxed compile:** if lualatex fails with "metric data not found or bad" (luaotfload cannot write its font cache), run it with `TEXMFVAR=$TMPDIR/texmf-var` so the cache goes to a writable directory.
- **Icons are PNG:** the repo `.gitignore` ignores `*.png`, so `icons/` is not versioned. Keep the copies in this folder (from `templates/moncv/assets/icons/`); a fresh clone must restore them before compiling.
- Escape `&`, `%`, `#`, `_` in content (`\&`, `\%`, …); use `\textasciitilde` for "~".
