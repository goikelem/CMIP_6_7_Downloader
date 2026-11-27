# CMIP6 / CMIP7 Toolbox User Guide

## 1. Entrypoints
- `scripts/download_cmip.py --project {cmip6|cmip7} ...` — main CLI entrypoint.
- `scripts/download_cmip6.py ...` — shorthand wrapper forwarding `--project cmip6`.
- `scripts/download_cmip7.py ...` — shorthand wrapper forwarding `--project cmip7`.

## 2. Common Workflows

### List Variables, Groups, and ESGF Indices
```bash
python3 scripts/download_cmip.py --project cmip7 --list-variables
python3 scripts/download_cmip.py --project cmip6 --list-indices
```

### Probe Availability on ESGF
```bash
python3 scripts/download_cmip7.py --all-models --experiments historical medium high --resolutions daily monthly --variable-groups water_balance --probe
```

### Filter Ensemble Members & Grids
```bash
# Exact member or regex match
python3 scripts/download_cmip6.py --all-models --experiments ssp2_4_5 --resolutions monthly --variants r1i1p1f1

# First N members per model (natural r-number ordering)
python3 scripts/download_cmip6.py --all-models --experiments ssp2_4_5 --resolutions monthly --max-members 2 --grid gn
```

### Dry-Run, Logging, and Manifests
```bash
python3 scripts/download_cmip7.py --models CESM3 --experiments historical --resolutions monthly --dry-run --log-file run.log
```
Each processed dataset appends a JSON line to `<output_dir>/<project>/manifest.jsonl` containing `timestamp_utc`, `status`, `out_file`, `bytes`, and `sha256`.

## 3. Running Unit Tests
```bash
python3 -m unittest discover -v tests
```
