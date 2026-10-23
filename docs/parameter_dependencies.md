# Parameter dependencies

How OOI computes the variables in our products, drawn from the
[preload database](https://github.com/oceanobservatories/preload-database) `ParameterDefs.csv`
(`master` as of 2026-10-23). Each box is an OOI data product (DPI), labelled with OOI's
display name and DPI code; arrows point from an input to the product computed from it. Blue boxes
are our products (our variable names in italics); grey boxes are intermediate inputs; unlinked
boxes depend only on their own sensor and calibration. Calibration constants, raw L0 counts, and
surface-mooring / OPTAA branches are omitted.

Regenerate: `python -m rca_cicoes_cresst.param_graph`

```mermaid
flowchart LR
    ABSTHRM_L1["<b>pH Sensor Thermistor Temperature</b><br/>ABSTHRM_L1"]
    CDOMFLO_L1["<b>CDOM Concentration</b><br/>CDOMFLO_L1<br/><i>flcdr_x_mmp_cds_fluorometric_cdom</i><br/><i>fluorometric_cdom</i>"]
    CHLAFLO_L1["<b>Chlorophyll-a Concentration</b><br/>CHLAFLO_L1<br/><i>fluorometric_chlorophyll_a</i>"]
    CO2THRM_L1["<b>pCO2 Sensor Thermistor Temperature</b><br/>CO2THRM_L1"]
    CONDWAT_L1["<b>Seawater Conductivity</b><br/>CONDWAT_L1"]
    DENSITY_L2["<b>Seawater Density</b><br/>DENSITY_L2<br/><i>sea_water_density</i>"]
    DOCONCF_L2["<b>Dissolved Oxygen - Pressure Temp Sal Corrected (CTD)</b><br/>DOCONCF_L2<br/><i>corrected_dissolved_oxygen</i>"]
    DOCONCS_L1["<b>Dissolved Oxygen - Temp Corrected</b><br/>DOCONCS_L1"]
    DOXYGEN_L2["<b>Dissolved Oxygen - Temp Pressure Sal Corrected</b><br/>DOXYGEN_L2<br/><i>corrected_dissolved_oxygen</i>"]
    FLUBSCT_L1["<b>Total Volume Scattering Coefficient</b><br/>FLUBSCT_L1"]
    FLUBSCT_L2["<b>Optical Backscatter</b><br/>FLUBSCT_L2<br/><i>optical_backscatter</i>"]
    NITRTSC_L2["<b>Nitrate Concentration - Temp and Sal Corrected</b><br/>NITRTSC_L2<br/><i>salinity_corrected_nitrate</i>"]
    PCO2WAT_L1["<b>pCO2 Seawater</b><br/>PCO2WAT_L1<br/><i>pco2_seawater</i>"]
    PHWATER_L2["<b>pH</b><br/>PHWATER_L2<br/><i>ph_seawater</i><br/><i>ph_total</i>"]
    PRACSAL_L2["<b>Practical Salinity</b><br/>PRACSAL_L2<br/><i>sea_water_practical_salinity</i>"]
    PRESWAT_L1["<b>Seawater Pressure</b><br/>PRESWAT_L1"]
    TEMPWAT_L1["<b>Seawater Temperature</b><br/>TEMPWAT_L1<br/><i>sea_water_temperature</i>"]
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
    subgraph Legend
        lg_in[intermediate input] -->|computed from| lg_prod[our product]
        lg_sal[practical salinity] -->|computed from salinity:<br/>CTD problems can carry over| lg_prod2[our product]
    end
    classDef default fill:#e5e7eb,stroke:#4b5563,color:#111827
    classDef product fill:#bfdbfe,stroke:#1d4ed8,color:#0b1f4d
    classDef salinity fill:#fcd34d,stroke:#b45309,stroke-width:2px,color:#451a03
    class CDOMFLO_L1,CHLAFLO_L1,DENSITY_L2,DOCONCF_L2,DOXYGEN_L2,FLUBSCT_L2,NITRTSC_L2,PCO2WAT_L1,PHWATER_L2,TEMPWAT_L1 product
    class PRACSAL_L2,lg_sal salinity
    class lg_prod,lg_prod2 product
    linkStyle default stroke:#6b7280
    linkStyle 5,6,7,8,9,10,26 stroke:#b45309,stroke-width:2px
```

## Salinity inheritance

Practical salinity (`PRACSAL_L2`, amber) is the main shared input, so a CTD conductivity
clog or drift also affects the products it points to on the same node. An arrow means "used in",
not "strongly affected by":

| Mask | Error per unit salinity | Why |
|------|-------------------------|-----|
| `sea_water_practical_salinity`, `sea_water_density` | density -0.79 kg/m3 | computed directly |
| `corrected_dissolved_oxygen`, `dissolved_oxygen` | ~0.7% | Garcia & Gordon salinity correction, umol/L -> umol/kg |
| `ph_total` (PHSENH, ISFET) | ~0.015 pH | chloride / sulfate / ionic-strength terms |
| `salinity_corrected_nitrate` | large | sea-salt (bromide) absorbance subtraction |

Not masked: temperature (Sea-Bird: fouling doesn't affect the thermistor), PHSEN
`ph_seawater` (~0.002 pH per unit salinity, below sensor uncertainty), pCO2, chlorophyll,
CDOM, backscatter. Exception: on pumped profiling CTDs, a pump failure may also affect
temperature response.

Clogs are usually abrupt multi-unit steps (annotation 6394: -2.45 for 10 weeks), not slow
drift. BGC-Argo flags O2/NO3/pH as suspect (3) when salinity is bad; our products keep good
data only, so they mask. `common.inherit_params` adds these at load time, so ledger rows only
need the base parameters.
