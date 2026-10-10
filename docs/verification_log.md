# Verification log

What manual verification of 15 companies' emissions data found (Sept 2026).
Every value in `data/bronze/emissions_raw.csv` has a source document and page.
This is the evidence base for the "garbage in, quantum out" pitch.

## Findings by type

**Mislabelled data**
- Outokumpu: aggregator (DitchCarbon) publishes the 2016 base year as "2023" (Scope 1 1,213,634 t;
  Scope 2 1,210,872 t). Overstates emissions ~1.7x. The same aggregator matched Fortum exactly:
  sources must be checked per value, not trusted or dismissed wholesale.
- UPM: table row "Scope 1 from regulated emissions trading schemes (%)" contains tonnes (1,550,000),
  in both the 2024 and 2025 reports (template error).
- Orion: base-year column contains the label "2023" instead of values (parser trap).
- KONE: footnote marker on the 2024 value describes 2025.

**Unit error**
- Metso: 2024 Scope 1 restated because one site used the wrong energy unit. Original 37,670 t (Financial review 2024,
  p.39) vs restated 33,245 t (Annual report 2025, p.94, footnote: "For Scope 1, the difference was due to the wrong
  energy unit used by one site"). Scope 1 only. Scope 2 was restated in the same release (location 75,652 -> 77,789;
  market 3,308 -> 4,412) with no specific reason stated (footnote: "internal validation and changes in methodology").
  Total location-based GHG (Scope 1+2+3) moved from 4,125,322 t (AR2024) to 62,563,203 t (AR2025) because of a method
  change for use of sold products (+58,437,881 t per the footnote), not because of the unit error.

**Restatements / multiple versions of one number**
- Kemira: 2023 market-based Scope 2 published as 488 kt (AR2023), 469,839 t (AR2024), 548,020 t (AR2025).
- Nordea: 2024 market-based Scope 2 restated from 3,037 t to 16,540 t (5.4x) for full coverage of the
  consolidated group + new emission factors. 2023 figures are on the old boundary.
- Stora Enso, Outokumpu, KONE, Kesko, Sampo, Metso: prior years and/or base years restated.
- Metso: sustainability-linked bond 2022 baseline restated from 48,944 t to 44,595 t.

**Methodology breaks (not comparable across years)**
- Elisa: 2021 Scope 1 corrected 5,927 -> 1,035 t; 2022-2023 stay on old method, so the reported
  "77% drop" 2023->2024 is most likely a methodology artefact.
- Neste: report states 2023 is not comparable with 2024-2025 (ESRS scope).
- Fortum: 2025 Scope 2 up ~434% (market) because heat losses moved from Scope 3; not restated.
- Metso 2023 / Sampo 2023 / Kesko 2023: older methods (CO2 only, net of certificates, pre-integration).
- Sampo: the 2024 figures are on a merged If + Topdanmark boundary with a common methodology. Board report 2025, p.84:
  "The Scope 1 and 2 GHG emissions for years 2022-2024 were recalculated following the merger of If and Topdanmark" (the PDF
  prints the dash as a mis-encoded character); the 2023 row in `emissions_raw.csv` is the pre-integration Sustainability
  Report 2023.
- Kesko: not settled by the PDF. Annual report 2025 (PDF p.125) says the 2024 recalculation was done by "adding previously
  missing information and correcting errors identified after the completion of the 2024 sustainability statement": data
  corrections, with no stated method change between 2023 and 2024.
- Metso 2023 has two rows in `emissions_raw.csv`: the GRI supplement (CO2 only, Scope 1 net of renewable gas
  certificates: 28,653 / 76,349 / 3,528) and Financial review 2024 p.39 (gross, ESRS E1-6: 36,912 / 76,956 / 3,229;
  Scope 1 +29%). Silver uses the GRI row only because of source-type ranking; the AR2024 row is the comparable basis.

**Boundary differences**
- Stora Enso: two tables in one report - GHG Protocol operational control (Scope 1 0.99 Mt) vs
  ESRS financial consolidation incl. joint operations (1.14 Mt). Totals equal; Scope 1 differs ~15%.
- Consolidation approaches differ: most operational control; Elisa, Metso, Kesko, Orion financial.
- Kesko: K-stores are franchises, so store emissions are Scope 3 cat 14, not Scope 1+2.
- UPM: Scope 1 excludes mobile combustion and non-production sites.
- Wartsila: from 2024 the boundary includes companies with <10 employees, which are not in the baseline
  (`emissions_raw.csv` note, 2024 row).

**Portfolio changes**
- Nokia: Scope 1 -65% 2023->2024 from divesting the marine fleet (Submarine Networks); Infinera
  included from Mar 2025; 2019 base year reconstructed from Infinera's 2020-2024 data.
- Fortum (recycling, divested 2024), Kemira (Oil & Gas, 2024), Elisa, Orion (VMD acquired Jul 2022).

**Estimated / assumed values inside reported numbers**
- KONE: >90% of Scope 1+2 measured, remainder extrapolated. Sustainability Statement 2025, printed p.60, Table 18
  footnote on the Scope 1 and 2 chart (which plots 2018, 2023, 2024, 2025): "KONE's environmental reporting covers over 90%
  of our Scope 1 and 2 emissions. The remaining emissions are extrapolated to cover 100% of KONE's operations."
- Metso: small sites excluded but an estimate added. Annual report 2025, PDF p.95: "An estimate of emissions in
  locations excluded due to not having energy-intensive operations has been added into reported emissions" and "These
  estimates have been added for all the reporting years and the historical figures are therefore restated." (so 2024 too).
- Sampo: 2024 Scope 1 restated +60% from a higher assumed car mileage. Board report 2025, p.84: "Scope 1 emissions
  increased by 679 tCO2eq in 2022 and 530 tCO2eq in 2024 mainly due to an increase of the annual mileage, which is used
  in calculation assumptions."
- Orion: climate metrics not externally validated (stated in report).

**Scope 2 method matters**
- Market vs location gaps: Metso 49x, Elisa ~30x, Nokia 23x. Kemira and UPM: Scope 2 is a large share.
- Kesko 2023 "location-based" used residual-mix factors (actually a market-based method).
- Sampo: market-based above location-based (2022, 2024).
- Nokia: market-based cooling equals location-based (fallback factor).

**Scope 3 / financed emissions traps**
- Nordea: total Scope 3 19.8 Mt (financed), ~1,400x own Scope 1+2. Sampo: similar (cat 15).
- Wartsila: Scope 3 112 Mt (~2,000x Scope 1+2); in 2023 it was 2.0 Mt because use of sold products
  was not yet included. Metso and Nokia similar.

**Gross vs net, gases, biogenic**
- KONE: gross Scope 1 in table, net (after renewable gas certificates) in footnote.
- UPM: CO2 only by choice; Neste/Outokumpu labels say CO2 but methods cover CO2e.
- Stora Enso biogenic Scope 1 ~12x fossil Scope 1; UPM ~6x. Excluded from Scope 1.
- Orion: refrigerants use AR6 GWP, inhaler HFCs use AR4 in the same inventory.

**Positive consistency (confidence signal)**
- Orion: 2023 Scope 1 + market Scope 2 = 13,940 t, exactly the baseline quoted two years later.
- Fortum aggregator values matched the primary table exactly.

## Pipeline flags on the verified data (all genuine)
- STERV.HE 2024, 2025 - E05 source disagreement (two boundaries)
- METSO.HE 2023 - E05 source disagreement (GRI basis vs AR2024 gross ESRS basis, Scope 1 differs 22%)
- ELISA.HE 2024, 2025 - E08 YoY jump (methodology break)
- NOKIA.HE 2024 - E08 (divestment)
- NDA-FI.HE 2024 - E08 (boundary restatement)

Checks currently miss Scope 2 swings (Fortum, Outokumpu, Kemira) because E08 only covers Scope 1.
