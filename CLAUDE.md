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
  (`substitute` rows in `config/adjustments.csv`); don't mask them.
- Window-based one-offs (substitute a variable, apply an offset, mask a window OOI hasn't
  annotated) go in `config/adjustments.csv`, one variable per row, not in code.
- Masking matches node + parameter name, so a DOSTA annotation also masks the CTD's
  integrated DO on that node. Mask DOSTA rows only if CTD DO is affected too.
- Integrated packages carry several sensors in one stream. PHSENH is a SeapHOx: SBE 37
  CTD + SBE 63 optode + SeaFET pH on one pumped flow path. An annotation about one channel
  can be correctly attached and still affect the others (6794: O2 phase delay pinned and
  pH drifted to ~6.5 together). Check the data before masking or dismissing.
- Open-ended annotations mask to the end of the data, including later deployments.
  Usually OOI has since closed them (6794 was open-ended in the 2026-07-20 harvest;
  deployment 1 ended 2026-08-08). Re-harvest first; if still open and the next
  deployment looks good, ask OOI to close it; meanwhile a `mask` row in
  `config/adjustments.csv` can cover a window the annotation gets wrong.

## Parameter inheritance (CTD conductivity problems)
A CTD salinity problem also affects products OOI computes from it on the same node (DO,
PHSENH `ph_total`, nitrate, density). `common.inherit_params` adds these at load time, so ledger
rows only need the base parameters. Which products are and aren't masked, and why:
`docs/parameter_dependencies.md`.
