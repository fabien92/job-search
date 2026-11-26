# Block CV (SPEC §9) — fictional example

A CV split into blocks, so that adapting it to one posting only means writing a small
`cv_overrides.tex`. This folder is a **fictional example** (Jane Doe). Copy it to
`documents/cv/jobbot/` (gitignored, backed up nightly) and replace the content with yours:

```bash
mkdir -p documents/cv/jobbot && cp -R jobbot/examples/cv/. documents/cv/jobbot/
```

Layout: `templates/cv/moncv-awesome` (unchanged). Name and contact details come from
`private/identity.tex` (fallback: `templates/identity_example.tex`).

```
cv.tex                 master: template layout + \input of the blocks
blocks/content.tex     default macros (the only things that may be redefined)
blocks/header.tex      header (contact details, optional photo)
blocks/experience.tex  roles, dates, bullets (fixed facts)
blocks/{education,training,skills,languages}.tex
variants/<name>.tex    overrides of one variant
pdf/<name>.pdf         compiled variants (generated)
```

Compile every variant (no AI involved):

```bash
jobbot/.venv/bin/python jobbot/scripts/build_cv_variants.py            # all
jobbot/.venv/bin/python jobbot/scripts/build_cv_variants.py techlead   # one
```

Each variant must come out at **exactly 2 pages**. If it overflows, shorten the text, never the layout
(the `\newpage` in `blocks/experience.tex` decides where page 2 starts).

## Contract of `cv_overrides.tex` (per-application adaptation)

Loaded after the variant; it may contain only `\renewcommand` (or `\cvphotofalse` / `\cvphototrue`) on:

| Macro | Content |
|---|---|
| `\cvHeadline` | headline under the name — **one line** (about 50 characters at most) |
| `\cvProfileText` | Profile paragraph — **4 lines** at most |
| `\cvAchievementOne/Two/Three` | `\textbf{Title} --- text`, 2–3 lines each |
| `\expCurrentBlocks` | order of `\expMgmt`, `\expTech`, `\expProj` (current role) |
| `\tsA` … `\tsI` | Technical Skills cells: `\skillcell{Title}{list}` |
| `\fsA` … `\fsD` | Functional Skills cells: `\funcell{Title}{list}` |

Forbidden: any layout command (`\vspace`, `\geometry`, colours, sizes) and the facts (roles, dates,
bullets). `jobbot/scripts/texguard.py` enforces this before LaTeX runs.

## Variants

The scoring step picks one variant per posting; `default_variant` in `jobbot/config/schedule.yaml` is
used when it did not. The names below are the ones `jobbot/commands/jobbot-scan.md` describes: if you
rename or add variants, update that file too.

| Variant | For | Photo |
|---|---|---|
| `delivery` | delivery / service delivery / release / project manager | yes |
| `techlead` | tech lead, architecture, DevOps, engineering manager | yes |
| `international-orgs` | international organisations | no (several refuse photos) |
| `support-it-manager` | IT support / service desk / incident / operations manager | yes |

Photo: put the file in `documents/cv/jobbot/` and set `\newcommand{\cvPhotoFile}{photo.jpg}` in
`blocks/content.tex` (replace the empty definition). With an empty `\cvPhotoFile` no photo is shown.
