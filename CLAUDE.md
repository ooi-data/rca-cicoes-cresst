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
- Official `parameters`, when present, take precedence over LLM `parameters_affected`.
- Optode DAC firmware-noise annotations (2017–2021) are superseded by the DO splice
  (`DO_SPLICE_SUPERSEDED_IDS`); don't re-curate them as masks.
- Masking matches node + parameter name, so a DOSTA annotation also masks the CTD's
  integrated DO on that node. Curate DOSTA rows only if CTD DO is affected too.
- If the text describes a different sensor than the one annotated (e.g. 6794),
  flag it for review instead of masking.
- Open-ended annotations mask to the end of the data; re-check them each release.

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
good data only, so mask. Apply this inheritance deterministically, not via the LLM.
