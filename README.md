# CMIP6 / CMIP7 ESGF Subset & Download Toolbox

CLI toolbox for searching, subsetting (spatial bounding box + year range), and writing compressed NetCDF4 files from **CMIP6** and **CMIP7** archives via `intake-esgf`.

## Quickstart

```bash
pip install -r requirements.txt

# Inspect configured variables, CMIP7 branding suffixes, and groups
python3 scripts/download_cmip.py --project cmip7 --list-variables

# Inspect available ESGF indices
python3 scripts/download_cmip.py --project cmip6 --list-indices

# Probe ESGF index availability before downloading
python3 scripts/download_cmip6.py --all-models --experiments historical ssp2_4_5 --resolutions monthly --probe

# Dry-run to inspect target output paths and write manifest entries
python3 scripts/download_cmip7.py --models CESM3 UKESM1-3-LL --experiments historical medium --resolutions monthly --variable-groups core_atmos --dry-run

# Execute download and spatial/temporal subsetting
python3 scripts/download_cmip6.py --models CESM2 MPI-ESM1-2-HR --experiments historical ssp5_8_5 --resolutions daily --variables pr tasmax tasmin
```

## Key Features
- **Dual CMIP6 & CMIP7 Support**: Handles CMIP6 `member_id` / `table_id` conventions alongside CMIP7 `variant_label` / `variable_branding_suffix` mappings.
- **Lazy Positional Subsetting**: Uses `xarray.Dataset.isel` with support for `0..360` and `-180..180` longitudes, dateline-crossing boxes, ascending/descending latitudes, 2-D curvilinear grids, and 1-D unstructured grids.
- **Atomic NetCDF4 Output + Manifest**: Writes `.part` staging files with `zlib=True, complevel=4` compression, verifies SHA-256 checksums, and records every dataset outcome in `manifest.jsonl`.
- **Dry-Run & Probe Modes**: `--probe` inspects live ESGF index coverage; `--dry-run` previews planned output files without downloading data.

See `cmip_67_user_guide.md` for full CLI flags and `cmip_67_directories_and_file_structure.md` for repository and output layouts.
