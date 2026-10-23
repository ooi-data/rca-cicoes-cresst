# Parameter dependencies

How OOI computes the variables in our products, drawn from the
[preload database](https://github.com/oceanobservatories/preload-database) `ParameterDefs.csv`
(`master` as of 2026-10-23). Each box is an OOI data product (DPI); arrows point from an
input to the product computed from it. Blue boxes feed our products (our variable names in
italics). Practical salinity (`PRACSAL_L2`, amber) is the main shared input: a bad salinity
also corrupts every product it points to, which is what `common.inherit_params` handles. An arrow
means "used in", not "strongly affected by": see the sensitivity table in `CLAUDE.md` (e.g. PHSEN
`ph_seawater` changes only ~0.002 pH per unit salinity). Unlinked boxes depend only on their own
sensor and calibration.
Calibration constants, raw L0 counts, and surface-mooring / OPTAA branches are omitted.

Regenerate: `python -m rca_cicoes_cresst.param_graph`

```mermaid
flowchart LR
    ABSTHRM_L1["<b>ABSTHRM_L1</b>"]
    CDOMFLO_L1["<b>CDOMFLO_L1</b><br/><i>flcdr_x_mmp_cds_fluorometric_cdom</i><br/><i>fluorometric_cdom</i>"]
    CHLAFLO_L1["<b>CHLAFLO_L1</b><br/><i>fluorometric_chlorophyll_a</i>"]
    CO2THRM_L1["<b>CO2THRM_L1</b>"]
    CONDWAT_L1["<b>CONDWAT_L1</b>"]
    DENSITY_L2["<b>DENSITY_L2</b><br/><i>sea_water_density</i>"]
    DOCONCF_L2["<b>DOCONCF_L2</b><br/><i>corrected_dissolved_oxygen</i>"]
    DOCONCS_L1["<b>DOCONCS_L1</b>"]
    DOXYGEN_L2["<b>DOXYGEN_L2</b><br/><i>corrected_dissolved_oxygen</i>"]
    FLUBSCT_L1["<b>FLUBSCT_L1</b>"]
    FLUBSCT_L2["<b>FLUBSCT_L2</b><br/><i>optical_backscatter</i>"]
    NITRTSC_L2["<b>NITRTSC_L2</b><br/><i>salinity_corrected_nitrate</i>"]
    PCO2WAT_L1["<b>PCO2WAT_L1</b><br/><i>pco2_seawater</i>"]
    PHWATER_L2["<b>PHWATER_L2</b><br/><i>ph_seawater</i><br/><i>ph_total</i>"]
    PRACSAL_L2["<b>PRACSAL_L2</b><br/><i>sea_water_practical_salinity</i>"]
    PRESWAT_L1["<b>PRESWAT_L1</b>"]
    TEMPWAT_L1["<b>TEMPWAT_L1</b><br/><i>sea_water_temperature</i>"]
    ABSTHRM_L1 --> PHWATER_L2
    CO2THRM_L1 --> PCO2WAT_L1
    CONDWAT_L1 --> PRACSAL_L2
    DOCONCS_L1 --> DOXYGEN_L2
    FLUBSCT_L1 --> FLUBSCT_L2
    PRACSAL_L2 --> DENSITY_L2
    PRACSAL_L2 --> DOCONCF_L2
    PRACSAL_L2 --> DOXYGEN_L2
    PRACSAL_L2 --> FLUBSCT_L2
    PRACSAL_L2 --> NITRTSC_L2
    PRACSAL_L2 --> PHWATER_L2
    PRESWAT_L1 --> CONDWAT_L1
    PRESWAT_L1 --> DENSITY_L2
    PRESWAT_L1 --> DOCONCF_L2
    PRESWAT_L1 --> DOXYGEN_L2
    PRESWAT_L1 --> PHWATER_L2
    PRESWAT_L1 --> PRACSAL_L2
    TEMPWAT_L1 --> CONDWAT_L1
    TEMPWAT_L1 --> DENSITY_L2
    TEMPWAT_L1 --> DOCONCF_L2
    TEMPWAT_L1 --> DOXYGEN_L2
    TEMPWAT_L1 --> FLUBSCT_L2
    TEMPWAT_L1 --> NITRTSC_L2
    TEMPWAT_L1 --> PHWATER_L2
    TEMPWAT_L1 --> PRACSAL_L2
    classDef product fill:#dbeafe,stroke:#1d4ed8
    classDef salinity fill:#fde68a,stroke:#b45309,stroke-width:2px
    class CDOMFLO_L1,CHLAFLO_L1,DENSITY_L2,DOCONCF_L2,DOXYGEN_L2,FLUBSCT_L2,NITRTSC_L2,PCO2WAT_L1,PHWATER_L2,TEMPWAT_L1 product
    class PRACSAL_L2 salinity
    linkStyle 5,6,7,8,9,10 stroke:#b45309,stroke-width:2px
```
