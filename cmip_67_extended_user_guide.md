# CMIP_67 Extended User Guide

## 1. Overview & Architecture

**CMIP_67** is a Python command-line toolkit for querying, inspecting, spatially and temporally subsetting, and downloading **CMIP6** and **CMIP7** climate model datasets from ESGF catalogs via `intake-esgf` and `xarray`.

Key components in the repository:
* `scripts/download_cmip.py`: Core CLI application (`main`, `parse_args`, `probe`, `search`, `crop_dataset`, `write_netcdf`, and manifest/logging logic).
* `scripts/download_cmip6.py`: Thin wrapper invoking `download_cmip.py` with `--project cmip6`.
* `scripts/download_cmip7.py`: Thin wrapper invoking `download_cmip.py` with `--project cmip7`.
* `config.json`: Central configuration holding `output_dir`, default spatial `area` bounds, `variables`, `variable_groups`, `temporal_resolutions`, and project-specific sections (`cmip6` and `cmip7`).
* `tests/test_helpers.py`: Unit tests for coordinate/index helpers, ensemble variant matching, variable resolution, CLI argument parsing, and regression checks.

### Project-Specific Index Defaults
* **CMIP6 (`cmip6`)**: Defaults to index patterns matching `("globus",)` because STAC republishing of CMIP6 can exhibit `member_id` metadata issues and legacy Solr nodes are largely decommissioned.
* **CMIP7 (`cmip7`)**: Defaults to index patterns matching `("discovery",)` for ESGF2 STAC discovery indices.
* You can inspect enabled indices via `--list-indices`, filter them by substring via `--indices PAT [PAT ...]`, or query all enabled indices via `--all-indices`.

---

## 2. Installation & Environment Setup

Run commands from the repository root (`CMIP_67/`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

To run unit tests (including offline helper and CLI tests):

```bash
python3 -m unittest discover tests
```

---

## 3. Configuration (`config.json`)

`config.json` controls output paths, default spatial boxes, variable definitions, variable groups, and CMIP6/CMIP7 experiment and model catalogs.

### Top-Level Keys
* `output_dir`: Base output root (default `~/DATA`). Relative paths not starting with `/` are resolved under `Path.home()`, and results are written under `<output_root>/<project>/`.
* `area`:
  * `lat_bounds`: `[SOUTH, NORTH]` in degrees latitude (e.g., `[2, 16]`).
  * `lon_bounds`: `[WEST, EAST]` in degrees longitude (e.g., `[32, 49]`).
* `default_variables`: Fallback variable key list when neither `--variables`, `--variable-groups`, nor `--all-variables` is passed.
* `variables`: Dictionary mapping internal variable keys (such as `pr`, `tas`, `tasmax`, `tasmin`, `evspsbl`, `mrro`, `mrso`, `rivo`) to:
  * `esgf_variable_id`: CMIP6 / base ESGF variable ID.
  * `esgf_table_id`: Mapping of `"daily"` and `"monthly"` to CMIP tables (such as `day`, `Eday`, `Amon`, `Lmon`, `Emon`, `Rmon`).
  * `label`, `category`, `units`: Metadata descriptors.
  * `cmip7`: Optional CMIP7 override dictionary specifying `esgf_variable_id` and `branding_suffix` per resolution (`"daily"` and `"monthly"`), such as `tmax-h2m-hxy-u` or `tavg-u-hxy-lnd`.
* `variable_groups`: Named collections of variable keys (`core_atmos`, `precipitation`, `temperature`, `evaporation`, `runoff_hydrology`, `surface_fluxes`, `water_balance`).
* `cmip6` and `cmip7`: Each defines `source`, `frequency_map` (`"daily": "day"`, `"monthly": "mon"`), optional `table_map`, `experiments` (mapping experiment keys to `esgf_id` and default `[START_YEAR, END_YEAR]`), and `models`.

### Inspecting Configured Variables & Groups

```bash
python3 scripts/download_cmip.py --project cmip6 --list-variables
python3 scripts/download_cmip.py --project cmip7 --list-variables
```

---

## 4. Discovery & Pre-Flight Workflows

### A. Check ESGF Indices
```bash
python3 scripts/download_cmip6.py --list-indices
python3 scripts/download_cmip7.py --list-indices
```

### B. Probe Index Availability (`--probe`)
Use `--probe` before downloading to inspect what datasets, branding suffixes (for CMIP7), and models exist on the catalog for each requested combination:

```bash
# CMIP6 probe
python3 scripts/download_cmip6.py \
  --all-models \
  --experiments historical ssp2_4_5 \
  --resolutions monthly \
  --variable-groups water_balance \
  --probe

# CMIP7 probe
python3 scripts/download_cmip7.py \
  --all-models \
  --experiments historical medium high \
  --resolutions daily monthly \
  --variables pr tas tasmax \
  --probe
```

### C. List Matching Records Without Subsetting (`--list-only`)
```bash
python3 scripts/download_cmip6.py \
  --models cesm2 gfdl_esm4 \
  --experiments historical \
  --resolutions monthly \
  --variables pr tas \
  --variants r1i1p1f1 \
  --grid gn \
  --list-only
```

### D. Dry Run (`--dry-run`)
`--dry-run` evaluates matching datasets and target output paths without executing `to_dataset_dict()` downloads, writing dry-run status entries to the manifest:

```bash
python3 scripts/download_cmip7.py \
  --models ACCESS-ESM1-6 UKESM1-3-LL \
  --experiments historical \
  --resolutions monthly \
  --variables pr tas \
  --dry-run \
  --log-file dry_run_cmip7.log
```

---

## 5. End-to-End Download & Subsetting Workflows

### CMIP6 Examples

```bash
# Single realization and grid over default box and experiment year bounds
python3 scripts/download_cmip6.py \
  --models cesm2 mpi_esm1_2_hr ukesm1_0_ll \
  --experiments historical ssp2_4_5 ssp5_8_5 \
  --resolutions monthly \
  --variable-groups water_balance \
  --variants r1i1p1f1 \
  --grid gn

# Daily temperature & precipitation for first 2 ensemble members, custom box & year range
python3 scripts/download_cmip6.py \
  --models cesm2 gfdl_esm4 \
  --experiments ssp2_4_5 \
  --resolutions daily \
  --variables pr tasmax tasmin \
  --max-members 2 \
  --box 2 16 32 49 \
  --years 2020 2050
```

### CMIP7 Examples

```bash
# CMIP7 historical and scenario runs using wrapper script
python3 scripts/download_cmip7.py \
  --models ACCESS-ESM1-6 CanESM5-1 UKESM1-3-LL \
  --experiments historical medium high \
  --resolutions daily monthly \
  --variables pr tas tasmax tasmin \
  --box 2 16 32 49
```

### Unbounded Time Axis (`--no-time-subset`)
To retain the full available time axis instead of subsetting to experiment `years` or `--years`:

```bash
python3 scripts/download_cmip6.py \
  --models cesm2 \
  --experiments historical \
  --resolutions monthly \
  --variables pr \
  --no-time-subset
```

### Streaming Mode (`--prefer-streaming`)
Pass `--prefer-streaming` to prefer streaming access (such as OPENDAP/Zarr/Kerchunk where available) with fallback to file download:

```bash
python3 scripts/download_cmip6.py \
  --models cesm2 \
  --experiments ssp2_4_5 \
  --resolutions monthly \
  --variables tas \
  --prefer-streaming
```

---

## 6. Filtering, Facet Relaxation & Output Layout

### Model, Member & Grid Filtering
* **Models**: Choose one of `--models MODEL [MODEL ...]`, `--all-models`, or `--no-model-filter`. Model names are normalized (`norm_model`) so hyphen/underscore/case differences (e.g., `mpi_esm1_2_hr` vs. `MPI-ESM1-2-HR`) match cleanly.
* **Ensemble Members**:
  * `--variants PAT [PAT ...]`: Full-regex match (`re.fullmatch`) against variant/member labels (e.g., `r1i1p1f1` or `r[1-3]i.*`).
  * `--max-members N`: Keeps the first `N` members per model sorted naturally by `(r, i, p, f)` numbers.
* **Grid**: `--grid LABEL` filters on `grid_label` (e.g., `gn`, `gr`, `g115`).
* **Deduplication**: `dedupe_datasets()` retains one record per dataset, preferring the highest `version` string when multiple versions are present.

### Facet Relaxation & Local Re-Filtering
When an exact query returns no hits, `search()` can progressively relax facets from `["table_id", "variable_branding_suffix", "frequency"]` and re-apply frequency, table, and branding-suffix constraints locally via `apply_local_facets()` so incompatible frequencies or suffixes are not silently mixed.

### Output Directory & File Naming
Files are saved under:

```text
<output_root>/<project>/<experiment_key>/<resolution>/<variable_key>/<dataset_stem>.nc
```

* Writes use a temporary `.part` file and atomic replacement (`os.replace`) with `zlib` compression (`complevel=4`), stripping stale source chunking metadata that can fail upon subsetting.
* Existing `.nc` files are skipped unless `--overwrite` is supplied.

---

## 7. Logging & Manifest Auditing

* **Console & File Logging**: Use `--verbose` for detailed debug output and `--log-file PATH` to write logs to disk.
* **JSONL Manifest (`manifest.jsonl`)**: Each processed dataset records a JSON object per line containing status, output path, byte count, SHA-256 checksum, and any error message. You can inspect completed or failed items with standard command-line tools or Python:

```bash
# Count entries by status
python3 -c 'import collections, json; p="manifest.jsonl"; c=collections.Counter(json.loads(l)["status"] for l in open(p)); print(c)'
```

---

## 8. Troubleshooting Common Issues

* **No datasets found for a CMIP7 variable or experiment**: Run with `--probe` to inspect available `variable_branding_suffix` values and published experiments on the discovery index.
* **Index mismatch**: Check enabled indices with `--list-indices` and override with `--indices` or `--all-indices` if a node or index name differs from defaults.
* **Empty spatial or temporal subset**: Confirm `--box` (`SOUTH NORTH WEST EAST` with `SOUTH <= NORTH`) overlaps the dataset grid and `--years` overlaps the dataset time coverage.
* **Re-running after partial or interrupted runs**: Re-run the same command without `--overwrite` to skip already-written `.nc` files, or pass `--overwrite` to regenerate outputs.