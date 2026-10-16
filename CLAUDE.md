# HITL annotations 
When evaluating whether an annotation is data quality affecting keep in mind that any mention that 
the calibrations or coefficients have been corrected means that the data currently being served by the 
OOI system is good. 

## OOI annotation fields
Per OOI's stream_engine and ooi-data-explorations code; no published spec exists.
- `parameters`: OOI preload parameter IDs. Map to zarr names via `netcdf_name` in
  preload-database `csv/ParameterDefs.csv`. Empty list = whole stream (~91% of annotations).
- `qcFlag`: null = note, not a quality call. not_operational / not_available /
  pending_ingest = missing data, not bad data.
- `exclusionFlag`: ignore. When true, OOI drops the whole stream for that window at
  serve time; effectively unused.
- Null node/sensor/method/stream = wildcard for everything beneath it.

## Curation rules
- Decisions live in `annotations/ledger.csv` (one row per annotation id: mask / ignore /
  superseded). Before building `--qaqc-filter highest` products: `harvest-annotations --all`,
  `curate-annotations --all` (proposes rows for new or OOI-edited ids), review, approve.
  Windows always come from the latest harvest; never edit decisions' windows by hand.
- Official `parameters`, when present, take precedence over LLM `parameters_affected`.
- Shallow-profiler platform blowdowns are real ocean events, not data-quality problems:
  `ignore` them, even if flagged suspect or described as anomalous. Mooring failures (e.g. 181,
  anchor leg pulled to 400 m, "data suspect") are different and stay masked.
- Optode DAC firmware-noise annotations (2017–2021) are `superseded` by the DO splice
  (`DO_SPLICE_WINDOWS`); don't mask them.
- Masking matches node + parameter name, so a DOSTA annotation also masks the CTD's
  integrated DO on that node. Mask DOSTA rows only if CTD DO is affected too.
- Integrated packages carry several sensors in one stream. PHSENH is a SeapHOx: SBE 37
  CTD + SBE 63 optode + SeaFET pH on one pumped flow path. An annotation about one channel
  can be correctly attached and still affect the others (6794: O2 phase delay pinned and
  pH drifted to ~6.5 together). Check the data before masking or dismissing.
- Open-ended annotations mask to the end of the data, including later deployments.
  Usually OOI has since closed them (6794 was open-ended in our 2026-07-20 harvest;
  deployment 1 ended 2026-08-08). Re-harvest first; if still open and the next
  deployment looks good, ask OOI to close it (the ledger has no window override).

## Parameter inheritance (CTD conductivity problems)
OOI computes other instruments' products from the co-located CTD's practical salinity
(preload `parameterfunctionmap` -> `dpi_PRACSAL_L2`). A conductivity clog/drift on a CTD
therefore affects these products on the same node:

| Mask | Error per unit salinity | Why |
|------|-------------------------|-----|
| `sea_water_practical_salinity`, `sea_water_density` | density -0.79 kg/m3 | computed directly |
| `corrected_dissolved_oxygen`, `dissolved_oxygen` | ~0.7% | Garcia & Gordon salinity correction, umol/L -> umol/kg |
| `ph_total` (PHSENH, ISFET) | ~0.015 pH | chloride / sulfate / ionic-strength terms |
| `salinity_corrected_nitrate` | large | sea-salt (bromide) absorbance subtraction |

Do not mask: temperature (Sea-Bird: fouling doesn't affect the thermistor), PHSEN
`ph_seawater` (~0.002 pH per unit salinity, below sensor uncertainty), pCO2, chlorophyll,
CDOM, backscatter. Exception: on pumped profiling CTDs, an annotation describing a pump
failure may also affect temperature response.

Clogs are usually abrupt multi-unit steps (annotation 6394: -2.45 for 10 weeks), not slow
drift. BGC-Argo flags O2/NO3/pH as suspect (3) when salinity is bad; this product keeps
good data only, so mask. Inheritance is applied in code at load time
(`common.inherit_params`); ledger rows only need the base parameters.
