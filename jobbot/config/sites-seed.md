# JobBot — site set-up list (SPEC §6)

Example list for Vienna, Bratislava and Budapest. **Delete the lines you refuse**, check the links, save, then run:

```bash
cd ~/ai-job-search && jobbot/.venv/bin/python jobbot/scripts/import_seed.py --dry-run   # preview
cd ~/ai-job-search && jobbot/.venv/bin/python jobbot/scripts/import_seed.py             # import + settings
```

Reading rules: only lines `- https://…` or `- *.domain` are imported; the domain kept is the host without
`www.` and it covers its subdomains. The text after "—" is a comment. `<!-- -->` blocks are ignored. A line
deleted **after** an import is not revoked: use `/deny`.

## Job portals — Austria

- https://www.karriere.at — portal karriere-search
- https://www.linkedin.com — portal linkedin-search (low volume)
- https://jobs.derstandard.at — portal derstandard-search
- https://www.hays.at — portal hays-search (staffing agency)
- https://www.randstad.at — portal randstad-search (staffing agency)
- https://www.michaelpage.at — portal michaelpage-search (recruitment agency; terms: personal use)
- https://www.hokify.at — partner shown by karriere.at

## Job portals — Slovakia / Hungary (regions off at the start)

- https://kariera.zoznam.sk — portal kariera-search, Bratislava
- https://www.profession.hu — portal profession-search, Budapest

## Job portals — remote

- https://jobgether.com — portal jobgether-search (remote jobs)

## International organisations (Vienna)

- https://careers.un.org — portal un-careers-search (UN / Inspira: UNODC, UNOV…)
- https://careers.unido.org — portal unido-search (UNIDO)
- https://vacancies.osce.org — portal osce-search (OSCE)
- https://careers.opecfund.org — portal opecfund-search (OPEC Fund)
- https://www.iaea.org — IAEA
- https://www.unodc.org — UNODC
- https://www.ctbto.org — CTBTO
- https://www.opec.org — OPEC
- https://iiasa.ac.at — IIASA
- https://www.icmpd.org — ICMPD

## Recruiting software — exact hosts

- https://jobs.lever.co — Lever
- https://boards.greenhouse.io — Greenhouse (former pages)
- https://job-boards.greenhouse.io — Greenhouse (new pages)
- https://jobs.smartrecruiters.com — SmartRecruiters
- https://apply.workable.com — Workable

<!--
## Recruiting software — generic groups (NOT imported: check the vendor's documentation first, SPEC §6)
- *.jobs.personio.de — Personio (career pages <company>.jobs.personio.de)
- *.jobs.personio.com — Personio
- *.myworkdayjobs.com — Workday
- *.successfactors.eu — SAP SuccessFactors (EU)
- *.successfactors.com — SAP SuccessFactors
- *.teamtailor.com — Teamtailor
- *.recruitee.com — Recruitee
- *.softgarden.io — softgarden
- *.onlyfy.io — onlyfy (formerly prescreen, Austria)
To enable a group after checking: move its line out of this comment block.
-->

## Career pages — banking, finance, insurance (Vienna)

- https://www.erstegroup.com — Erste Group
- https://www.erstedigital.com — Erste Digital (Erste's IT)
- https://www.rbinternational.com — Raiffeisen Bank International
- https://www.raiffeiseninformatik.at — Raiffeisen Informatik
- https://www.bankaustria.at — UniCredit Bank Austria
- https://www.bawaggroup.com — BAWAG
- https://www.oenb.at — Oesterreichische Nationalbank
- https://www.oekb.at — Oesterreichische Kontrollbank
- https://www.wienerborse.at — Wiener Börse
- https://www.uniqagroup.com — UNIQA
- https://group.vig — Vienna Insurance Group
- https://www.bnpparibas.at — BNP Paribas Austria

## Career pages — tech, industry, services (Vienna)

- https://www.dynatrace.com — Dynatrace
- https://www.bitpanda.com — Bitpanda
- https://www.frequentis.com — Frequentis
- https://www.kapsch.net — Kapsch
- https://www.cloudflight.io — Cloudflight
- https://www.omv.com — OMV
- https://a1.group — A1 Group
- https://www.magenta.at — Magenta Telekom
- https://www.siemens.com — Siemens
- https://www.ibm.com — IBM
- https://www.tieto.com — Tietoevry

## Career pages — French and European companies present in Vienna

- https://www.thalesgroup.com — Thales
- https://www.capgemini.com — Capgemini
- https://www.soprasteria.com — Sopra Steria
- https://www.atos.net — Atos
- https://eviden.com — Eviden
- https://www.se.com — Schneider Electric

## Public sector (Vienna)

- https://www.oebb.at — ÖBB
- https://www.wienerstadtwerke.at — Wiener Stadtwerke
- https://www.post.at — Österreichische Post
- https://www.wien.gv.at — City of Vienna
- https://www.tuwien.at — TU Wien
