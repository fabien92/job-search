# Search and scoring criteria

Edit this file freely: it is read at every run. Keep the `##` headings and the `EN :` / `DE :` /
`Strong :` / `Secondary :` / `Reject :` / `Flag :` labels as they are (the scripts read them); items
are separated by ` · `. Lines in brackets are notes and are ignored. The values below are an example
(IT delivery roles in Vienna): replace them with yours.

## Target titles

EN : IT Delivery Manager · Service Delivery Manager · IT Project Manager · Technical Project Manager · Program Manager · Tech Lead · Technical Lead · Engineering Manager · Solution Architect · Software Architect · IT Architect · Enterprise Architect · DevOps Engineer · Release Manager · Scrum Master · IT Consultant · Business Analyst (IT) · Application Manager · IT Service Manager

DE : IT-Projektmanager · IT-Projektleiter · Teamleitung IT-Betrieb · IT-Architekt · Lösungsarchitekt · Softwarearchitekt · Applikationsmanager · IT-Servicemanager

(Add titles in other languages on the EN line if your portals need them.)

## Keywords

(5 to 10 at most, to catch unexpected titles.)

DORA · EMIR · MiFID · derivatives · post-trade · CI/CD · offshore delivery

## Title exclusions

Head of · Director · VP / Vice President · CTO · CIO

(Leiter / Leitung are kept on purpose; add Bereichsleiter / Abteilungsleiter here if needed.)

## Type exclusions

Praktikum · Werkstudent · Internship · Trainee · Gyakornok · Stáž

## Excluded companies

Deloitte · PwC · EY · KPMG · Accenture · McKinsey · BCG · Bain

## Location

- Regions: see `regions.yaml`.
- Fully remote from anywhere in the world **if a candidate based in Europe is accepted**. Reject: US only, Americas only, APAC only, "must reside in" outside Europe, incompatible time zone.

## Language

- English: OK.
- German up to B2: OK.
- Reject: C2, verhandlungssicher, Muttersprache / native German.
- Keep with the flag "German to check": fließend, sehr gute Deutschkenntnisse.

## Contract

- OK: unbefristet / permanent · Teilzeit / part-time · befristet ≥ 12 months · Karenzvertretung.
- Keep with the flag "duration unknown": fixed term without a stated duration.
- Reject: fixed term < 12 months.
- Reject for now, recorded with the reason `freelance`: freelance · Werkvertrag · contractor.

## Salary

No filter. Report the amount as displayed, without conversion.

## Scoring profile

With `scoring: claude`, the detailed profile comes from the candidate profile written by `/setup`; the
two lines below tell the model what weighs most. With `scoring: rules`, they are the whole score: each
keyword found in a posting adds points.

- Strong : IT delivery · architecture · CI/CD · derivatives · capital markets · offshore · tech lead · project manager · support · business intelligence
- Secondary : python · oracle · sql · jira · vtom · claude · unix · linux · git · docker
- Not wanted: see `rejection-rules.md`.

## Rules mode

Read only with `scoring: rules` in `schedule.yaml` (no AI). A posting whose title or text contains a
`Reject` term is rejected; a `Flag` term keeps it and adds a warning to the alert. With
`scoring: claude` the Location, Language and Contract sections above do this job, with judgement.

- Reject : verhandlungssicher · Muttersprache · Muttersprachniveau · native German · Deutsch C2 · Deutsch C1 · Werkvertrag · freelance
- Flag : fließend · sehr gute Deutschkenntnisse · befristet
