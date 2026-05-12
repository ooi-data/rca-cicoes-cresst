# Data Products

## Regridded Shallow Profiler Profiles

A multi-instrument, pressure-gridded dataset derived from OOI Regional Cabled Array (RCA) Shallow Profiler Mooring data. Raw time-series data from the OOI S3 zarr store is sliced into individual profiles using the [OOI profile index](https://github.com/OOI-CabledArray/profileIndices), deduplicated on pressure, and interpolated onto a uniform pressure grid.

### Sites

| Key | Site | CTD Refdes |
|-----|------|------------|
| `oregon_shelf` | Coastal Endurance Oregon Offshore | CE04OSPS-SF01B-2A-CTDPFA107 |
| `slope_base` | Oregon Slope Base | RS01SBPS-SF01A-2A-CTDPFA102 |
| `axial_base` | Axial Base | RS03AXPS-SF03A-2A-CTDPFA302 |

### Dimensions

| Dimension | Description |
|-----------|-------------|
| `profile_number` | Integer profile index from the OOI profile index CSV |
| `sea_water_pressure` | Uniform pressure grid (dbar), default 0–220 at 0.25 dbar spacing |

### Coordinates

| Coordinate | Type | Description |
|------------|------|-------------|
| `profile_number` | `int` | Primary dimension |
| `start_time` | `datetime64` | Profiler upcast start (platform depth) |
| `peak_time` | `datetime64` | Profiler peak (shallowest point, ~5 m) |
| `end_time` | `datetime64` | Profiler downcast end (platform depth) |

Time coordinates are interchangeable with `profile_number` via `ds.swap_dims({"profile_number": "peak_time"})`.

### Data Variables

| Variable | Instrument | Cast | Units |
|----------|------------|------|-------|
| `sea_water_temperature` | CTD (CTDPFA) | upcast |
| `sea_water_practical_salinity` | CTD (CTDPFA) | upcast |
| `corrected_dissolved_oxygen` | CTD (CTDPFA) | upcast |
| `sea_water_density` | CTD (CTDPFA) | upcast | kg/m³ |
| `salinity_corrected_nitrate` | Nitrate (NUTNRA) | upcast |
| `ph_seawater` | pH (PHSENA) | downcast |
| `pco2_seawater` | pCO₂ (PCO2WA) | downcast |

CTD variables are sampled on the upcast. pH and pCO₂ are sampled on the downcast.

### Output Files

Files are named `<site>_profiles_<start>_<end>.<ext>`, e.g.:

```
axial_base_profiles_20150107_20260511.nc
oregon_shelf_profiles_20150101_20260508.zarr
```

Available formats: zarr (recommended for large datasets), NetCDF-4.

### Generating the Data Product

```bash
python scripts/regrid_profiler.py oregon_shelf
python scripts/regrid_profiler.py axial_base --grid 0 220 0.5 --format nc
python scripts/regrid_profiler.py slope_base --format both
```

See `scripts/regrid_profiler.py --help` for full options.
