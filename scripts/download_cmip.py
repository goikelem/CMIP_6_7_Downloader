#!/usr/bin/env python3
"""Download and spatially/temporally subset CMIP6/CMIP7 NetCDF datasets from ESGF."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.json"

KEEP_ENCODING = {
    "dtype", "_FillValue", "missing_value", "scale_factor",
    "add_offset", "units", "calendar",
}

PROJECT_INDEX_PATTERNS = {
    "cmip6": ("globus",),
    "cmip7": ("discovery",),
}

VARIANT_RE = re.compile(r"r(\d+)i(\d+)p(\d+)f(\d+)")
logger = logging.getLogger("cmip67")


def configure_logging(verbose: bool = False, log_file: str | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        p = Path(log_file).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(p, encoding="utf-8"))
    logging.basicConfig(level=level, format="%(message)s", handlers=handlers, force=True)


# --------------------------------------------------------------------------- #
# Config validation & resolution (pure)
# --------------------------------------------------------------------------- #
def validate_config(cfg: dict[str, Any]) -> None:
    """Validate required top-level and per-project config keys before execution."""
    if not isinstance(cfg, dict):
        raise SystemExit("Invalid config.json: root must be a JSON object.")
    required = ("output_dir", "area", "default_variables", "variables", "cmip6", "cmip7")
    missing = [k for k in required if k not in cfg]
    if missing:
        raise SystemExit(f"Invalid config.json: missing top-level keys {missing}")

    area = cfg["area"]
    if not isinstance(area, dict) or "lat_bounds" not in area or "lon_bounds" not in area:
        raise SystemExit("Invalid config.json: 'area' must define 'lat_bounds' and 'lon_bounds'.")
    if len(area["lat_bounds"]) != 2 or len(area["lon_bounds"]) != 2:
        raise SystemExit("Invalid config.json: 'lat_bounds' and 'lon_bounds' must each have 2 items.")

    for proj in ("cmip6", "cmip7"):
        pcfg = cfg[proj]
        for key in ("frequency_map", "experiments", "models"):
            if key not in pcfg:
                raise SystemExit(f"Invalid config.json: '{proj}' missing required key '{key}'.")


def norm_model(value: str) -> str:
    """Normalize model identifiers so config aliases match ESGF canonical IDs."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def safe_name(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


def _wrap_lon(x: float, lo: float) -> float:
    """Express longitude x in the convention [lo, lo+360]."""
    if lo <= x <= lo + 360:
        return x
    return (x - lo) % 360 + lo


def lonlat_mask(lat, lon, south: float, north: float, west: float, east: float) -> np.ndarray:
    """Boolean mask of grid points inside the box (lat/lon broadcastable arrays).

    Handles 0..360 and -180..180 datasets, ascending or descending latitude,
    and boxes crossing the dateline / prime meridian seam (west > east).
    """
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    if south > north:
        raise ValueError(f"SOUTH ({south}) must be <= NORTH ({north})")
    lat_mask = (lat >= south) & (lat <= north)

    if east - west >= 360:
        return lat_mask & np.ones_like(lon, dtype=bool)

    lo = 0.0 if np.nanmax(lon) > 180 else -180.0
    w, e = _wrap_lon(west, lo), _wrap_lon(east, lo)
    if w <= e:
        lon_mask = (lon >= w) & (lon <= e)
    else:
        lon_mask = (lon >= w) | (lon <= e)
    return lat_mask & lon_mask


def spatial_indexers(lat, lat_dims, lon, lon_dims, box):
    """Return {dim: integer indices} selecting the bounding index range of the box.

    * 1-D lat and lon on separate dims (regular grids): independent selection.
    * Otherwise (2-D curvilinear grids, or 1-D unstructured with a shared dim):
      the combined mask is reduced onto each dimension.
    """
    south, north, west, east = box
    lat = np.asarray(lat)
    lon = np.asarray(lon)
    if lat.ndim == 1 and lon.ndim == 1 and lat_dims != lon_dims:
        lat_idx = np.nonzero((lat >= south) & (lat <= north))[0]
        lon_mask_1d = lonlat_mask(np.ones_like(lon, dtype="float64"), lon, -90.0, 90.0, west, east)
        lon_idx = np.nonzero(lon_mask_1d)[0]
        return {lat_dims[0]: lat_idx, lon_dims[0]: lon_idx}

    if lat_dims != lon_dims or lat.shape != lon.shape:
        raise ValueError(f"Unsupported lat/lon layout: {lat_dims} {lat.shape} vs {lon_dims} {lon.shape}")
    mask = lonlat_mask(lat, lon, south, north, west, east)
    out = {}
    for axis, dim in enumerate(lat_dims):
        other = tuple(a for a in range(mask.ndim) if a != axis)
        out[dim] = np.nonzero(mask.any(axis=other) if other else mask)[0]
    return out


def year_indexer(years, y0: int, y1: int):
    years = np.asarray(years)
    return np.nonzero((years >= y0) & (years <= y1))[0]


# ---- ensemble-member selection (pure) ------------------------------------- #
def variant_rank(label) -> tuple:
    """Sort key for variant labels: r1i1p1f1 -> (1, 1, 1, 1); unparseable sorts last."""
    m = VARIANT_RE.match(str(label))
    return tuple(int(g) for g in m.groups()) if m else (10 ** 6, 0, 0, 0)


def variant_matches(label, patterns) -> bool:
    """True if the variant label fully matches any regex pattern."""
    return any(re.fullmatch(p, str(label)) for p in patterns)


def pick_first_members(pairs, n: int) -> set:
    """Keep the n lowest-ranked (source_id, variant_label) pairs per model."""
    per_model: dict = {}
    for source, variant in pairs:
        per_model.setdefault(source, set()).add(variant)
    keep = set()
    for source, variants in per_model.items():
        for variant in sorted(variants, key=variant_rank)[:n]:
            keep.add((source, variant))
    return keep


def member_mask(pairs, patterns=None, max_members=None) -> list[bool]:
    """Boolean list over (source_id, variant_label) pairs for --variants/--max-members."""
    pairs = list(pairs)
    if patterns:
        return [variant_matches(v, patterns) for _s, v in pairs]
    if max_members:
        keep = pick_first_members(pairs, max_members)
        return [p in keep for p in pairs]
    return [True] * len(pairs)


def resolve_variables(cfg, variables=None, variable_groups=None, all_variables=False) -> list[str]:
    """Resolve requested variable keys from --variables, --variable-groups, or --all-variables."""
    all_vars = cfg["variables"]
    groups = cfg.get("variable_groups", {})
    if all_variables:
        return list(all_vars)
    if not variables and not variable_groups:
        return list(cfg["default_variables"])
    ordered: list[str] = []
    seen: set[str] = set()
    unknown_groups = sorted({g.lower() for g in (variable_groups or [])} - set(groups))
    if unknown_groups:
        raise SystemExit(f"Unknown variable groups={unknown_groups} (valid: {sorted(groups)})")
    for grp in variable_groups or []:
        for vk in groups[grp.lower()]:
            if vk not in seen:
                seen.add(vk)
                ordered.append(vk)
    for vk_raw in variables or []:
        vk = vk_raw.lower()
        if vk not in seen:
            seen.add(vk)
            ordered.append(vk)
    unknown_vars = sorted(set(ordered) - set(all_vars))
    if unknown_vars:
        raise SystemExit(f"Unknown variables={unknown_vars} (valid: {sorted(all_vars)})")
    return ordered


# --------------------------------------------------------------------------- #
# Manifest & checksum helpers
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def append_manifest(manifest_path: Path, record: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# --------------------------------------------------------------------------- #
# xarray-dependent helpers
# --------------------------------------------------------------------------- #
LAT_NAMES = ["lat", "latitude", "nav_lat", "y"]
LON_NAMES = ["lon", "longitude", "nav_lon", "x"]


def get_coord_name(ds, candidates):
    for name in candidates:
        if name in ds.coords or name in ds.variables:
            return name
    raise ValueError(f"Could not find coordinate among {candidates}; found {list(ds.coords)}")


def crop_dataset(ds, box, years=None):
    """Crop to box (and optional inclusive (y0, y1) years) using lazy isel."""
    lat_name = get_coord_name(ds, LAT_NAMES)
    lon_name = get_coord_name(ds, LON_NAMES)
    lat, lon = ds[lat_name], ds[lon_name]
    indexers = spatial_indexers(lat.values, lat.dims, lon.values, lon.dims, box)
    if any(len(ix) == 0 for ix in indexers.values()):
        return None

    if years is not None and "time" in ds.dims:
        idx = year_indexer(ds["time"].dt.year.values, *years)
        if len(idx) == 0:
            return None
        indexers["time"] = idx
    return ds.isel(indexers)


def write_netcdf(ds, out_file: Path, label: str) -> None:
    """Write atomically (temp file + rename) with sane encoding and compression."""
    ds = ds.copy()
    for name, var in ds.variables.items():
        enc = {k: v for k, v in var.encoding.items() if k in KEEP_ENCODING}
        if name in ds.data_vars and var.dtype.kind in "iuf":
            enc.update(zlib=True, complevel=4)
        var.encoding = enc
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    ds.attrs["history"] = (
        f"{stamp}: subset by download_cmip.py ({label}); " + str(ds.attrs.get("history", ""))
    ).strip()
    tmp = out_file.with_name(out_file.name + ".part")
    try:
        ds.to_netcdf(tmp, engine="netcdf4")
        os.replace(tmp, out_file)
    finally:
        if tmp.exists():
            tmp.unlink()


# --------------------------------------------------------------------------- #
# ESGF index handling
# --------------------------------------------------------------------------- #
def index_name(idx) -> str:
    return str(idx)


def select_indices(indices, patterns):
    """Indices whose name contains any pattern (case-insensitive substring)."""
    pats = [str(p).lower() for p in patterns]
    keep = [i for i in indices if any(p in index_name(i).lower() for p in pats)]
    dropped = [index_name(i) for i in indices if i not in keep]
    if not keep:
        raise SystemExit(
            f"No ESGF index matches {patterns}; available: {[index_name(i) for i in indices]}"
        )
    if dropped:
        logger.info("  Indices in use: %s (skipped: %s)", [index_name(i) for i in keep], dropped)
    return keep


def default_indices(cat, project):
    """Per-project default index subset (see PROJECT_INDEX_PATTERNS)."""
    patterns = PROJECT_INDEX_PATTERNS.get(project, ())
    if not patterns:
        return cat.indices
    keep = [i for i in cat.indices if any(p in index_name(i).lower() for p in patterns)]
    return keep or cat.indices


# --------------------------------------------------------------------------- #
# Search / dataframe helpers
# --------------------------------------------------------------------------- #
def describe(exc) -> str:
    """Exceptions from intake-esgf (e.g. NoSearchResults) can have an empty str()."""
    return f"{type(exc).__name__}: {exc}".rstrip(": ")


def is_no_results(exc) -> bool:
    return "NoSearchResults" in type(exc).__name__


def search(make_catalog, terms, relaxable, file_kwargs=None):
    """Search ESGF; if a facet combination matches nothing, relax facets one by one."""
    dropped = []
    last_exc = None
    file_kwargs = file_kwargs or {}
    while True:
        t = {k: v for k, v in terms.items() if k not in dropped}
        cat = None
        try:
            cat = make_catalog()
            cat.search(**t, **file_kwargs)
            if not cat.df.empty:
                return cat, dropped
            last_exc = None
        except Exception as exc:
            last_exc = None if is_no_results(exc) else exc
        remaining = [k for k in relaxable if k in t]
        if not remaining:
            if last_exc is not None:
                raise last_exc
            return cat, dropped
        dropped.append(remaining[0])


def variant_column(df):
    """CMIP7 results use 'variant_label'; CMIP6 results use 'member_id'."""
    cols = df.columns if hasattr(df, "columns") else df
    for col in ("variant_label", "member_id"):
        if col in cols:
            return col
    return None


def _clean_facet(value):
    """None for missing/NaN facets, else their string value."""
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    s = str(value)
    return s if s and s != "nan" else None


def dataset_stem(row, fallback_key, df_columns):
    """Compact, unique output-file stem built from a result-row's facets."""
    vcol = variant_column(df_columns)
    freq = row.get("frequency")
    if _clean_facet(freq) is None:
        freq = row.get("table_id")
    parts = [
        row.get("source_id"),
        row.get("experiment_id"),
        row.get(vcol) if vcol else None,
        freq,
        row.get("variable_id"),
        row.get("variable_branding_suffix"),
        row.get("grid_label"),
    ]
    stem = "_".join(p for p in (_clean_facet(x) for x in parts) if p)
    return safe_name(stem) if stem else safe_name(fallback_key)


def hashable_key_columns(df):
    """Columns usable for drop_duplicates (skips list/dict-valued columns)."""
    cols = []
    for col in df.columns:
        if col in ("id", "key"):
            continue
        sample = df[col].dropna()
        if len(sample) and isinstance(sample.iloc[0], (list, dict, set)):
            continue
        cols.append(col)
    return cols


def dedupe_datasets(df):
    """One record per dataset, keeping the newest version."""
    if df is None or df.empty:
        return df
    key_cols = [c for c in hashable_key_columns(df) if c != "version"]
    if "version" in df.columns:
        out = df.assign(_v=df["version"].map(lambda x: str(x) if x == x and x is not None else ""))
        out = out.sort_values("_v", ascending=False)
        out = out.drop_duplicates(subset=key_cols, keep="first").drop(columns="_v")
    else:
        out = df.drop_duplicates(subset=key_cols, keep="first")
    return out


def apply_local_facets(df, frequency, table_id, suffix, dropped=()):
    """Re-apply frequency/table/branding-suffix restrictions on the dataframe."""
    notes = []
    for facet, value in (
        ("variable_branding_suffix", suffix),
        ("table_id", table_id),
        ("frequency", frequency),
    ):
        if value is None:
            continue
        if facet not in df.columns:
            if facet in dropped:
                notes.append(
                    f"could not re-apply relaxed {facet}={value} "
                    f"(no '{facet}' column in results; verify with --probe)"
                )
            continue
        before = len(df)
        df = df[df[facet].astype(str) == str(value)]
        if before != len(df):
            notes.append(f"{facet}={value}: kept {len(df)}/{before} records")
    return df, notes


def filter_models(df, requested_models, report_missing):
    """Local model filter bridging config aliases and ESGF source_id values."""
    if "source_id" not in df.columns:
        return df, []
    wanted = {norm_model(m) for m in requested_models}
    available = {norm_model(m) for m in df["source_id"].astype(str).unique()}
    matched = sorted(wanted & available)
    if report_missing:
        names = sorted(m for m in requested_models if norm_model(m) not in available)
        if names:
            logger.info("  Not available for this combination: %s", ", ".join(names))
    mask = df["source_id"].astype(str).map(lambda s: norm_model(s) in wanted)
    return df[mask], matched


def filter_members(df, patterns=None, max_members=None):
    """Apply --variants / --max-members on the variant/member column."""
    col = variant_column(df)
    if col is None:
        logger.info("  Note: results have no variant_label/member_id column; member filter skipped.")
        return df
    pairs = list(zip(df["source_id"].astype(str), df[col].astype(str)))
    mask = member_mask(pairs, patterns=patterns, max_members=max_members)
    return df[np.array(mask)]


def filter_grid(df, grid):
    if "grid_label" not in df.columns:
        logger.info("  Note: results have no grid_label column; --grid skipped.")
        return df
    return df[df["grid_label"].astype(str) == str(grid)]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", choices=["cmip6", "cmip7"], required=True)
    p.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to config.json (default: ../config.json next to scripts/)",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--models", nargs="+", help="Model IDs/aliases.")
    g.add_argument(
        "--all-models",
        action="store_true",
        help="All models listed for this project in config.json.",
    )
    g.add_argument(
        "--no-model-filter",
        action="store_true",
        help="Every model ESGF returns (can be very large).",
    )
    p.add_argument(
        "--experiments",
        nargs="+",
        help="Config experiment keys, e.g. ssp1_2_6 or very_low",
    )
    p.add_argument("--resolutions", nargs="+", choices=["daily", "monthly"])
    p.add_argument("--variables", nargs="+", help="Config variable keys, e.g. tas pr")
    p.add_argument(
        "--variable-groups",
        nargs="+",
        help="Config variable group keys, e.g. water_balance evaporation runoff_hydrology",
    )
    p.add_argument("--all-variables", action="store_true")
    p.add_argument(
        "--list-variables",
        action="store_true",
        help="Print configured variables, CMIP7 branded suffixes, and variable groups, then exit.",
    )
    p.add_argument(
        "--box",
        nargs=4,
        type=float,
        metavar=("SOUTH", "NORTH", "WEST", "EAST"),
        help="Spatial box in degrees; default comes from config.json",
    )
    p.add_argument(
        "--years",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Inclusive year range; default is the experiment's 'years' in config.json",
    )
    p.add_argument(
        "--no-time-subset",
        action="store_true",
        help="Keep the full time axis of each dataset.",
    )
    p.add_argument("--output-dir", help="Override output_dir from config.json")
    p.add_argument(
        "--list-only",
        action="store_true",
        help="Search and report matching ESGF datasets without downloading.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve queries and planned output paths without downloading files.",
    )
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--probe",
        action="store_true",
        help="Print what the index holds for every requested variable x experiment "
             "x resolution (availability matrix), then exit.",
    )
    p.add_argument(
        "--variants",
        nargs="+",
        metavar="PAT",
        help="Only ensemble members whose variant (e.g. r1i1p1f1) fully matches "
             "a regex PAT; e.g. 'r1i1p1f1' or 'r[1-3]i.*'.",
    )
    p.add_argument(
        "--max-members",
        type=int,
        metavar="N",
        help="Keep only the first N ensemble members of each model (by r-number).",
    )
    p.add_argument(
        "--grid",
        metavar="LABEL",
        help="Only this grid_label, e.g. gn (CMIP6) or g115 (CMIP7).",
    )
    p.add_argument(
        "--indices",
        nargs="+",
        metavar="PAT",
        help="Restrict to ESGF indices whose name contains any PAT "
             "(substring, case-insensitive; see --list-indices).",
    )
    p.add_argument(
        "--all-indices",
        action="store_true",
        help="Search every enabled index instead of the per-project default subset.",
    )
    p.add_argument(
        "--list-indices",
        action="store_true",
        help="Print the available ESGF indices and exit.",
    )
    p.add_argument(
        "--prefer-streaming",
        action="store_true",
        help="Open datasets via OPENDAP/Zarr/Kerchunk links instead of downloading "
             "whole files into the intake-esgf cache.",
    )
    p.add_argument("--manifest", help="Optional path for JSONL run manifest output.")
    p.add_argument("--log-file", help="Optional log file path.")
    p.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    args = p.parse_args(argv)
    if args.years and args.no_time_subset:
        p.error("--years and --no-time-subset are mutually exclusive")
    if args.variants and args.max_members:
        p.error("--variants and --max-members are mutually exclusive")
    if args.max_members is not None and args.max_members < 1:
        p.error("--max-members must be >= 1")
    if args.indices and args.all_indices:
        p.error("--indices and --all-indices are mutually exclusive")
    for pat in args.variants or []:
        try:
            re.compile(pat)
        except re.error as exc:
            p.error(f"invalid --variants pattern {pat!r}: {exc}")
    if args.all_variables and (args.variables or args.variable_groups):
        p.error("--all-variables cannot be combined with --variables or --variable-groups")
    if not (args.list_indices or args.list_variables):
        if not args.experiments:
            p.error("the following arguments are required: --experiments")
        if not args.resolutions:
            p.error("the following arguments are required: --resolutions")
        if not (args.models or args.all_models or args.no_model_filter):
            p.error("Specify --models MODEL [...], --all-models or --no-model-filter.")
    return args


# --------------------------------------------------------------------------- #
# Probe: what does the index actually hold?
# --------------------------------------------------------------------------- #
def probe(make_catalog, project, var_specs, resolutions, exp_keys, project_cfg):
    """Availability matrix for every requested combination."""
    logger.info("\n[PROBE] project=%s", project.upper())
    empty_exps = []
    for resolution in resolutions:
        frequency = project_cfg["frequency_map"][resolution]
        table_id = project_cfg.get("table_map", {}).get(resolution)
        wanted = var_specs[resolution]
        var_ids = sorted({v for v, _s in wanted.values()})
        for exp_key in exp_keys:
            exp_id = project_cfg["experiments"][exp_key]["esgf_id"]
            terms = dict(
                project=project.upper(),
                experiment_id=exp_id,
                variable_id=var_ids,
                frequency=frequency,
            )
            if table_id:
                terms["table_id"] = table_id
            logger.info("\n[PROBE] %s (%s) | %s (%s)", exp_key, exp_id, resolution, frequency)
            df = None
            cat = None
            try:
                cat = make_catalog()
                cat.search(**terms)
                df = cat.df
            except Exception as exc:
                if not is_no_results(exc):
                    logger.info("  search failed: %s", describe(exc))
                    continue
                df = cat.df if cat is not None else None
            if df is None or df.empty:
                logger.info("  NOT ON INDEX for any requested variable")
                empty_exps.append((exp_key, exp_id, var_ids[0], frequency))
                continue
            for var_key, (var_id, suffix) in wanted.items():
                rows = df[df["variable_id"].astype(str) == var_id]
                if rows.empty:
                    logger.info("  %-9s (%s): variable_id not on index", var_key, var_id)
                    continue
                if "variable_branding_suffix" in rows.columns:
                    have = sorted(rows["variable_branding_suffix"].astype(str).unique())
                    if suffix and suffix in have:
                        sel = rows[rows["variable_branding_suffix"].astype(str) == suffix]
                        models = sorted(sel["source_id"].astype(str).unique())
                        logger.info(
                            "  %-9s (%s + %s): %d datasets, %d models: %s",
                            var_key, var_id, suffix, len(sel), len(models), ", ".join(models),
                        )
                    else:
                        logger.info(
                            "  %-9s (%s): wanted suffix %s NOT available; index holds: %s",
                            var_key, var_id, suffix or "(none)", ", ".join(have),
                        )
                else:
                    models = sorted(rows["source_id"].astype(str).unique())
                    logger.info(
                        "  %-9s (%s): %d datasets, %d models: %s",
                        var_key, var_id, len(rows), len(models), ", ".join(models),
                    )
    for exp_key, exp_id, var_id, frequency in empty_exps:
        try:
            cat = make_catalog()
            cat.search(project=project.upper(), variable_id=var_id, frequency=frequency)
            df = cat.df
            if df is not None and not df.empty and "experiment_id" in df.columns:
                exps = sorted(df["experiment_id"].astype(str).unique())
                logger.info(
                    "\n[PROBE] hint: %s/%s is published for these experiments (none of them was %s): %s",
                    var_id, frequency, exp_id, ", ".join(exps),
                )
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(verbose=args.verbose, log_file=args.log_file)

    with Path(args.config).expanduser().resolve().open(encoding="utf-8") as f:
        cfg = json.load(f)
    validate_config(cfg)

    if args.list_variables:
        logger.info("Configured variables (%d):", len(cfg["variables"]))
        logger.info(
            "  %-11s %-9s %-9s %-20s %-20s LABEL",
            "KEY", "CMIP6_ID", "CMIP7_ID", "CMIP7_DAILY", "CMIP7_MONTHLY",
        )
        for vk, vc in cfg["variables"].items():
            c7 = vc.get("cmip7", {})
            c7_id = c7.get("esgf_variable_id", vc["esgf_variable_id"])
            c7_day = c7.get("branding_suffix", {}).get("daily", "-")
            c7_mon = c7.get("branding_suffix", {}).get("monthly", "-")
            logger.info(
                "  %-11s %-9s %-9s %-20s %-20s %s",
                vk, vc["esgf_variable_id"], c7_id, c7_day, c7_mon, vc.get("label", ""),
            )
        if cfg.get("variable_groups"):
            logger.info("\nConfigured variable groups (--variable-groups):")
            for gk, gvars in cfg["variable_groups"].items():
                logger.info("  %-18s: %s", gk, ", ".join(gvars))
        return 0

    import platform
    import intake_esgf
    from intake_esgf import ESGFCatalog

    if args.list_indices:
        cat = ESGFCatalog()
        logger.info("Available ESGF indices (enabled in the intake-esgf config):")
        for idx in cat.indices:
            logger.info("  %s", index_name(idx))
        for proj in PROJECT_INDEX_PATTERNS:
            default = [index_name(i) for i in default_indices(cat, proj)]
            logger.info("Default for %s: %s", proj, default)
        logger.info("Override with --indices PATTERN... (substring match) or --all-indices.")
        return 0

    project = args.project.lower()
    project_cfg = cfg[project]
    output_root = Path(args.output_dir or cfg["output_dir"]).expanduser()
    if not output_root.is_absolute():
        output_root = Path.home() / output_root
    output_root = output_root / project

    manifest_path = (
        Path(args.manifest).expanduser()
        if args.manifest
        else output_root / cfg.get("manifest_filename", "manifest.jsonl")
    )

    var_keys = resolve_variables(
        cfg,
        variables=args.variables,
        variable_groups=args.variable_groups,
        all_variables=args.all_variables,
    )
    unknown_exps = sorted(set(args.experiments) - set(project_cfg["experiments"]))
    if unknown_exps:
        raise SystemExit(
            f"Unknown experiments={unknown_exps} (valid: {sorted(project_cfg['experiments'])})"
        )

    var_specs = {}
    for resolution in args.resolutions:
        specs = {}
        for var_key in var_keys:
            var_cfg = cfg["variables"][var_key]
            cmip7 = var_cfg.get("cmip7", {})
            var_id = (
                cmip7.get("esgf_variable_id", var_cfg["esgf_variable_id"])
                if project == "cmip7"
                else var_cfg["esgf_variable_id"]
            )
            suffix = cmip7.get("branding_suffix", {}).get(resolution) if project == "cmip7" else None
            specs[var_key] = (var_id, suffix)
        var_specs[resolution] = specs

    def make_catalog():
        cat = ESGFCatalog()
        if args.all_indices:
            return cat
        if args.indices:
            cat.indices = select_indices(cat.indices, args.indices)
        else:
            cat.indices = default_indices(cat, project)
        return cat

    try:
        intake_esgf.conf["break_on_error"] = False
    except TypeError:
        intake_esgf.conf.set(break_on_error=False)

    banner_cat = make_catalog()
    logger.info(
        "[%s] intake-esgf %s | python %s | indices: %s",
        project.upper(),
        intake_esgf.__version__,
        platform.python_version(),
        ", ".join(index_name(i) for i in banner_cat.indices),
    )

    if args.probe:
        probe(make_catalog, project, var_specs, args.resolutions, args.experiments, project_cfg)
        return 0

    if args.box:
        box = tuple(args.box)
    else:
        box = (*cfg["area"]["lat_bounds"], *cfg["area"]["lon_bounds"])
    if box[0] > box[1]:
        raise SystemExit(f"Invalid box: SOUTH {box[0]} > NORTH {box[1]}")

    if args.models:
        requested_models = args.models
    elif args.all_models:
        requested_models = project_cfg["models"]
    else:
        requested_models = None

    member_note = ""
    if args.variants:
        member_note = f", variants={'/'.join(args.variants)}"
    elif args.max_members:
        member_note = f", max {args.max_members} member(s) per model"

    stats = {"saved": 0, "skipped": 0, "empty": 0, "failed": 0, "dry_run": 0}
    combo_report = []
    unseen_models = {norm_model(m) for m in (requested_models or [])}

    for var_key in var_keys:
        for resolution in args.resolutions:
            frequency = project_cfg["frequency_map"][resolution]
            var_table = cfg["variables"][var_key].get("esgf_table_id", {}).get(resolution)
            table_id = (
                (var_table or project_cfg.get("table_map", {}).get(resolution))
                if project == "cmip6"
                else project_cfg.get("table_map", {}).get(resolution)
            )
            var_id, suffix = var_specs[resolution][var_key]
            for exp_key in args.experiments:
                exp_id = project_cfg["experiments"][exp_key]["esgf_id"]
                if args.no_time_subset:
                    years = None
                elif args.years:
                    years = tuple(args.years)
                else:
                    years = tuple(project_cfg["experiments"][exp_key].get("years") or ()) or None
                label = f"{var_key} | {exp_key} ({exp_id}) | {resolution}" + (
                    f" | years {years[0]}-{years[1]}" if years else ""
                )
                logger.info("\n[%s] %s", project.upper(), label)

                file_kwargs = None
                if years is not None:
                    file_kwargs = {
                        "file_start": f"{years[0]}-01-01",
                        "file_end": f"{years[1]}-12-31",
                    }

                try:
                    terms = dict(
                        project=project.upper(),
                        experiment_id=exp_id,
                        variable_id=var_id,
                        frequency=frequency,
                    )
                    if table_id:
                        terms["table_id"] = table_id
                    if suffix:
                        terms["variable_branding_suffix"] = suffix
                    relaxable = ["table_id", "variable_branding_suffix", "frequency"]
                    cat, dropped = search(make_catalog, terms, relaxable, file_kwargs)
                    if dropped:
                        logger.info(
                            "  Note: facets relaxed during search because they matched nothing, "
                            "then re-applied locally: %s",
                            dropped,
                        )

                    if cat is None or cat.df is None or cat.df.empty:
                        logger.info(
                            "  No datasets indexed for this combination. Run with --probe to inspect."
                        )
                        stats["empty"] += 1
                        combo_report.append((label, "not on index"))
                        continue

                    df = cat.df
                    df, notes = apply_local_facets(df, frequency, table_id, suffix, dropped)
                    for note in notes:
                        logger.info("  Note: %s", note)
                    if df.empty:
                        others = cat.df
                        have = []
                        if "variable_branding_suffix" in others.columns:
                            have = sorted(others["variable_branding_suffix"].astype(str).unique())
                        logger.info(
                            "  No records with the requested frequency/branded variant (%s)%s.",
                            "suffix " + suffix if suffix else frequency,
                            f"; index holds: {', '.join(have)}" if have else "",
                        )
                        stats["empty"] += 1
                        combo_report.append((label, "wrong frequency/variant"))
                        continue

                    if requested_models is not None:
                        df, matched = filter_models(
                            df, requested_models, report_missing=bool(args.models)
                        )
                        unseen_models -= set(matched)
                        if df.empty:
                            logger.info(
                                "  None of the requested models are available for this combination."
                            )
                            stats["empty"] += 1
                            combo_report.append((label, "no requested model"))
                            continue
                    if args.variants or args.max_members:
                        df = filter_members(
                            df, patterns=args.variants, max_members=args.max_members
                        )
                    if args.grid:
                        df = filter_grid(df, args.grid)
                    df = dedupe_datasets(df)

                    if df.empty:
                        logger.info("  No datasets left after member/grid filtering.")
                        stats["empty"] += 1
                        combo_report.append((label, "filtered out"))
                        continue
                    cat.df = df

                    logger.info(
                        "  Matching dataset records: %d%s%s",
                        len(df),
                        member_note if member_note else "",
                        f", grid={args.grid}" if args.grid else "",
                    )
                    if args.list_only:
                        vcol = variant_column(df)
                        cols = [
                            c
                            for c in [
                                "source_id", "experiment_id", vcol, "frequency",
                                "table_id", "variable_id", "variable_branding_suffix", "grid_label",
                            ]
                            if c in df.columns
                        ]
                        table = df[cols].drop_duplicates()
                        sort_by = [c for c in ["source_id", vcol] if c in cols]
                        if sort_by:
                            table = table.sort_values(sort_by)
                        logger.info("%s", table.to_string(index=False))
                        combo_report.append((label, f"{len(df)} records"))
                        continue

                    out_dir = output_root / exp_key / resolution / var_key

                    if args.dry_run:
                        n_dry = 0
                        for idx_row, row in df.iterrows():
                            stem = dataset_stem(row, str(idx_row), df.columns)
                            out_file = out_dir / f"{stem}.nc"
                            state = "exists" if (out_file.exists() and not args.overwrite) else "planned"
                            logger.info("  [DRY-RUN] %s -> %s", state, out_file)
                            append_manifest(
                                manifest_path,
                                {
                                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                    "project": project,
                                    "experiment": exp_key,
                                    "resolution": resolution,
                                    "variable": var_key,
                                    "out_file": str(out_file),
                                    "status": f"dry_run_{state}",
                                },
                            )
                            stats["dry_run"] += 1
                            n_dry += 1
                        combo_report.append((label, f"dry-run {n_dry} planned"))
                        continue

                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        datasets = cat.to_dataset_dict(
                            add_measures=False,
                            prefer_streaming=args.prefer_streaming,
                            minimal_keys=False,
                        )
                    if not datasets:
                        logger.info("  ESGF returned no readable datasets.")
                        stats["empty"] += 1
                        combo_report.append((label, "no readable dataset"))
                        continue

                    keyed = cat.df.set_index("key") if "key" in cat.df.columns else None
                    n_saved = n_skipped = 0
                    for dataset_key, ds in datasets.items():
                        out_file = None
                        try:
                            row = None
                            if keyed is not None and dataset_key in keyed.index:
                                row = keyed.loc[dataset_key]
                            stem = (
                                dataset_stem(row, dataset_key, cat.df.columns)
                                if row is not None
                                else safe_name(dataset_key)
                            )
                            out_file = out_dir / f"{stem}.nc"
                            if out_file.exists() and not args.overwrite:
                                logger.info("  Exists, skipped: %s", out_file)
                                stats["skipped"] += 1
                                n_skipped += 1
                                append_manifest(
                                    manifest_path,
                                    {
                                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                        "project": project,
                                        "experiment": exp_key,
                                        "resolution": resolution,
                                        "variable": var_key,
                                        "dataset_key": dataset_key,
                                        "out_file": str(out_file),
                                        "status": "skipped_exists",
                                    },
                                )
                                continue

                            cropped = crop_dataset(ds, box, years)
                            if cropped is None:
                                logger.info("  Empty spatial/temporal subset: %s", dataset_key)
                                stats["empty"] += 1
                                append_manifest(
                                    manifest_path,
                                    {
                                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                        "project": project,
                                        "experiment": exp_key,
                                        "resolution": resolution,
                                        "variable": var_key,
                                        "dataset_key": dataset_key,
                                        "out_file": str(out_file),
                                        "status": "empty_subset",
                                    },
                                )
                                continue

                            out_dir.mkdir(parents=True, exist_ok=True)
                            write_netcdf(cropped, out_file, f"box S/N/W/E={box}, years={years}")
                            digest = sha256_file(out_file)
                            logger.info("  Saved: %s (%s)", out_file, dict(cropped.sizes))
                            stats["saved"] += 1
                            n_saved += 1
                            append_manifest(
                                manifest_path,
                                {
                                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                    "project": project,
                                    "experiment": exp_key,
                                    "resolution": resolution,
                                    "variable": var_key,
                                    "dataset_key": dataset_key,
                                    "out_file": str(out_file),
                                    "bytes": out_file.stat().st_size,
                                    "sha256": digest,
                                    "status": "saved",
                                },
                            )
                        except Exception as exc:
                            stats["failed"] += 1
                            logger.error("  Dataset failed [%s]: %s", dataset_key, describe(exc))
                            append_manifest(
                                manifest_path,
                                {
                                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                    "project": project,
                                    "experiment": exp_key,
                                    "resolution": resolution,
                                    "variable": var_key,
                                    "dataset_key": dataset_key,
                                    "out_file": str(out_file) if out_file else None,
                                    "status": "failed",
                                    "error": describe(exc),
                                },
                            )
                        finally:
                            try:
                                ds.close()
                            except Exception:
                                pass

                    n_failed_open = sum(
                        1 for c in caught if "exception opening" in str(c.message)
                    )
                    n_missing = len(df) - len(datasets)
                    if n_failed_open:
                        stats["failed"] += n_failed_open
                        logger.warning(
                            "  %d dataset(s) failed to open (see intake-esgf/xarray warnings).",
                            n_failed_open,
                        )
                    n_no_files = max(0, n_missing - n_failed_open)
                    if n_no_files:
                        stats["empty"] += n_no_files
                        logger.info(
                            "  %d dataset(s) have no files within the requested years%s.",
                            n_no_files,
                            f" {years[0]}-{years[1]}" if years else "",
                        )
                    combo_report.append((label, f"saved {n_saved}, skipped {n_skipped}"))
                except Exception as exc:
                    stats["failed"] += 1
                    logger.error("  Search/download failed: %s", describe(exc))
                    combo_report.append((label, "FAILED"))

    logger.info("\nSummary: %s", ", ".join(f"{k}={v}" for k, v in stats.items()))
    if combo_report:
        logger.info("\nRecap:")
        for label, status in combo_report:
            logger.info("  %s: %s", label, status)
        unavailable = [label for label, status in combo_report if status == "not on index"]
        if unavailable:
            logger.info("\nNot published on the index right now (%d):", len(unavailable))
            for label in unavailable:
                logger.info("  %s", label)
            logger.info("  CMIP7 publication is ongoing; re-check later with --probe.")
    if requested_models is not None and unseen_models:
        never = sorted({m for m in requested_models if norm_model(m) in unseen_models})
        logger.info(
            "\nConfigured/requested models not seen on the index in any combination: %s",
            ", ".join(never),
        )
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
