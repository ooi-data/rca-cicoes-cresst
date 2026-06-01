# Data Products

## Regridded Profiler Mooring Profiles

A multi-instrument, pressure-gridded dataset derived from OOI Regional Cabled Array (RCA) profiler mooring data. Raw time-series data from the OOI S3 zarr store is sliced into individual profiles using the [OOI profile index](https://github.com/OOI-CabledArray/profileIndices), deduplicated on pressure, and interpolated onto a uniform pressure grid.

### Sites

#### Shallow Profilers

Science pod winched through the upper water column (~5–200 m) at 5 cm/s upcast, 10 cm/s downcast. ~9 profiles/day.

| Key | Site | Depth Range | CTD Refdes |
|-----|------|-------------|------------|
| `oregon_shelf` | Coastal Endurance Oregon Offshore | 5–200 m | CE04OSPS-SF01B-2A-CTDPFA107 |
| `slope_base` | Oregon Slope Base | 5–200 m | RS01SBPS-SF01A-2A-CTDPFA102 |
| `axial_base` | Axial Base | 5–200 m | RS03AXPS-SF03A-2A-CTDPFA302 |

#### Deep Profilers

Wire-following McLane profiler at ~25 cm/s.

| Key | Site | Depth Range | Water Depth | CTD Refdes |
|-----|------|-------------|-------------|------------|
| `oregon_shelf_deep` | Coastal Endurance Oregon Offshore | 175–500 m | 576 m | CE04OSPD-DP01B-01-CTDPFL105 |
| `slope_base_deep` | Oregon Slope Base | 150–2,900 m | 2,900 m | RS01SBPD-DP01A-01-CTDPFL104 |
| `axial_base_deep` | Axial Base | 150–2,465 m | 2,604 m | RS03AXPD-DP03A-01-CTDPFL304 |

### Dimensions

| Dimension | Description |
|-----------|-------------|
| `profile_number` | Integer profile index from the OOI profile index CSV |
| `sea_water_pressure` | Uniform pressure grid (dbar), set via `--grid` |

### Coordinates

| Coordinate | Type | Description |
|------------|------|-------------|
| `profile_number` | `int` | Primary dimension |
| `start_time` | `datetime64` | Profiler upcast start (platform depth) |
| `peak_time` | `datetime64` | Profiler peak (shallowest point) |
| `end_time` | `datetime64` | Profiler downcast end (platform depth) |

Time coordinates are interchangeable with `profile_number` via `ds.swap_dims({"profile_number": "peak_time"})`.

### Data Variables

#### Shallow profiler defaults

| Variable | Instrument | Cast |
|----------|------------|------|
| `sea_water_temperature` | CTD (CTDPFA) | upcast |
| `sea_water_practical_salinity` | CTD (CTDPFA) | upcast |
| `corrected_dissolved_oxygen` | CTD (CTDPFA) | upcast |
| `sea_water_density` | CTD (CTDPFA) | upcast |
| `salinity_corrected_nitrate` | Nitrate (NUTNRA) | upcast |
| `ph_seawater` | pH (PHSENA) | downcast |
| `pco2_seawater` | pCO₂ (PCO2WA) | downcast |

#### Deep profiler defaults

| Variable | Instrument | Cast |
|----------|------------|------|
| `sea_water_temperature` | CTD (CTDPFL) | upcast |
| `sea_water_practical_salinity` | CTD (CTDPFL) | upcast |
| `corrected_dissolved_oxygen` | Oxygen (DOSTAD) | upcast |
| `sea_water_density` | CTD (CTDPFL) | upcast |
| `fluorometric_chlorophyll_a` | Fluorometer (FLNTUA) | upcast |
| `flcdr_x_mmp_cds_fluorometric_cdom` | CDOM (FLCDRA) | upcast |

### Output Files

#### Regridded profiles (`regrid_profiler.py`)

```
<site>_profiles_<start>_<end>[_qf<flags>].<ext>
```

| Component | Description |
|-----------|-------------|
| `<site>` | Site key (e.g. `axial_base`) |
| `<start>` / `<end>` | Date range of profiles in the file (`YYYYMMDD`) |
| `_qf<flags>` | QARTOD flags removed, omitted when `--qaqc-filter none` |
| `<ext>` | `zarr` or `nc` |

Examples:

```
axial_base_profiles_20150107_20260511.zarr
axial_base_profiles_20150107_20260511_qf4.nc
```

#### Binned profiles (`bin_dataset.py`)

```
<input_stem>_binned_<N>h.<ext>
```

Example:

```
axial_base_profiles_20150107_20260511_binned_24h.zarr
```

#### Logs

One log file per run, written to `logs/`:

```
logs/<site>_<YYYYMMDD_HHMMSS>.log
```

### Generating the Data Product

```bash
# shallow profilers (~0–200 m)
python scripts/regrid_profiler.py oregon_shelf --grid 0 200 1 --format both
python scripts/regrid_profiler.py axial_base --grid 0 200 1 --format both --qaqc-filter basic
python scripts/regrid_profiler.py slope_base --grid 0 200 1 --format both

# deep profilers (site-dependent depth range)
python scripts/regrid_profiler.py oregon_shelf_deep --grid 175 500 1 --format both --qaqc-filter basic
python scripts/regrid_profiler.py slope_base_deep --grid 150 2900 1 --format both --qaqc-filter basic
python scripts/regrid_profiler.py axial_base_deep --grid 150 2465 1 --format both --qaqc-filter basic
```

See `scripts/regrid_profiler.py --help` for full options.
