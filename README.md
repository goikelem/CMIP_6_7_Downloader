<a name="top"></a>

<div align="center">

<img src="assets/banner.svg" alt="CMIP 6/7 Downloader: search ESGF, crop your region, save compressed NetCDF4" width="100%">

<br>

![CMIP6](https://img.shields.io/badge/CMIP6-supported-1f6feb?style=for-the-badge)
![CMIP7](https://img.shields.io/badge/CMIP7-supported-8250df?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3-3776ab?style=for-the-badge&logo=python&logoColor=white)
![ESGF](https://img.shields.io/badge/Data-ESGF-0f6e8c?style=for-the-badge)
![NetCDF4](https://img.shields.io/badge/Output-NetCDF4-19a974?style=for-the-badge)
![Linux](https://img.shields.io/badge/Shell-Linux-f4a100?style=for-the-badge&logo=linux&logoColor=black)

**A command-line toolbox that finds CMIP6 and CMIP7 climate model data, crops it to your area and years, and records what it saves.**

[🚀 Quick start](#quick-start) •
[🧭 Recipes](#recipes) •
[🌡️ Variables](#variables) •
[🛰️ Experiments](#experiments) •
[🎛️ Options](#options) •
[📂 Output](#output) •
[🩺 Help](#help)

</div>

---

## ✨ Highlights

| | Feature | What you get |
|:-:|---|---|
| 🌍 | **Two generations** | CMIP6 (`member_id`, `table_id`) and CMIP7 (`variant_label`, branding suffix) in one CLI |
| ✂️ | **Region and time subsetting** | Bounding box and year range, applied with lazy `xarray` indexing |
| 🧩 | **Many grid layouts** | `0..360` or `-180..180` longitudes, dateline crossing, 2-D curvilinear and 1-D unstructured grids |
| 🔭 | **Look before you download** | `--probe`, `--list-only` and `--dry-run` |
| 💾 | **Safe writes** | Compressed NetCDF4, written to a `.part` file and then renamed |
| 🧾 | **Traceable** | JSON Lines manifest with file size and SHA-256 for each saved file |

## 🔄 How it works

```mermaid
flowchart LR
    A([🔎 Search ESGF]):::search --> B([🧪 Filter models,<br/>members, grid]):::filter
    B --> C([⬇️ Download<br/>or stream]):::get
    C --> D([✂️ Crop box<br/>and years]):::crop
    D --> E([💾 Write NetCDF4]):::save
    E --> F([🧾 SHA-256 +<br/>manifest]):::log

    classDef search fill:#1f6feb,stroke:#0b3d91,color:#fff
    classDef filter fill:#8250df,stroke:#4c2889,color:#fff
    classDef get fill:#0f6e8c,stroke:#08404f,color:#fff
    classDef crop fill:#f4a100,stroke:#9a6700,color:#000
    classDef save fill:#19a974,stroke:#0b6645,color:#fff
    classDef log fill:#cf222e,stroke:#82071e,color:#fff
```

---

<a name="quick-start"></a>

## 🚀 Quick start

### 1️⃣ Clone

```bash
git clone https://github.com/goikelem/CMIP_6_7_Downloader.git CMIP_67
cd CMIP_67
```

### 2️⃣ Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3️⃣ Explore

```bash
python3 scripts/download_cmip7.py --list-variables
```

### 4️⃣ Preview

```bash
python3 scripts/download_cmip7.py \
  --models ACCESS-ESM1-6 UKESM1-3-LL \
  --experiments historical \
  --resolutions monthly \
  --variables pr tas \
  --dry-run
```

### 5️⃣ Download

Start small, with one ensemble member per model:

```bash
python3 scripts/download_cmip7.py \
  --models ACCESS-ESM1-6 UKESM1-3-LL \
  --experiments historical \
  --resolutions monthly \
  --variables pr tas \
  --max-members 1
```

🎉 Your files are in `~/DATA/cmip7/`.

> [!IMPORTANT]
> By default, whole source files are downloaded into the `intake-esgf` cache and **then** cropped. Check your free disk space before large requests, or try `--prefer-streaming`.

> [!NOTE]
> What is published on ESGF changes over time. If a model or experiment returns nothing, [probe the index](#recipes).

### 🧰 Which script do I run?

| Script | Use it for |
|---|---|
| 🔵 `scripts/download_cmip6.py` | CMIP6 |
| 🟣 `scripts/download_cmip7.py` | CMIP7 |
| ⚙️ `scripts/download_cmip.py --project {cmip6,cmip7}` | Main entry point behind both |

<p align="right"><a href="#top">⬆️ Back to top</a></p>

---

<a name="recipes"></a>

## 🧭 Recipes

👇 **Click a task to open it.**

<details>
<summary>🔭 <b>Probe: what does the index hold?</b></summary>
<br>

```bash
python3 scripts/download_cmip7.py \
  --all-models \
  --experiments historical medium high \
  --resolutions daily monthly \
  --variables pr tas tasmax \
  --probe
```

- A model option is required, but the probe reports **every** model on the index. Member, grid and year filters are not applied.
- For CMIP6, the probe searches only the `day` and `Amon` tables. Variables configured for other tables (such as `mrro` and `mrso` in `Lmon`) can appear missing. Use `--list-only` to check them.

</details>

<details>
<summary>📋 <b>List matching datasets without downloading</b></summary>
<br>

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

</details>

<details>
<summary>🔵 <b>CMIP6: historical and scenarios</b></summary>
<br>

```bash
python3 scripts/download_cmip6.py \
  --models cesm2 mpi_esm1_2_hr \
  --experiments historical ssp2_4_5 ssp5_8_5 \
  --resolutions monthly \
  --variable-groups water_balance \
  --variants r1i1p1f1 \
  --grid gn
```

</details>

<details>
<summary>🟣 <b>CMIP7: daily and monthly</b></summary>
<br>

```bash
python3 scripts/download_cmip7.py \
  --models ACCESS-ESM1-6 CanESM5-1 UKESM1-3-LL \
  --experiments historical medium high \
  --resolutions daily monthly \
  --variables pr tas tasmax tasmin \
  --max-members 1
```

</details>

<details>
<summary>🗺️ <b>Custom region and years</b></summary>
<br>

The order is **SOUTH NORTH WEST EAST**.

```bash
python3 scripts/download_cmip6.py \
  --models cesm2 \
  --experiments ssp2_4_5 \
  --resolutions daily \
  --variables pr tasmax tasmin \
  --box 2 16 32 49 \
  --years 2020 2050
```

To cross the dateline, give a WEST value greater than EAST, for example `--box -10 10 170 -170`.

</details>

<details>
<summary>👥 <b>Choose ensemble members</b></summary>
<br>

| Goal | Add |
|---|---|
| One exact member | `--variants r1i1p1f1` |
| Regex: realisations 1 to 3 | `--variants 'r[1-3]i.*'` |
| First two members of each model | `--max-members 2` |

`--variants` and `--max-members` cannot be combined.

</details>

<details>
<summary>⏳ <b>Keep the full time axis, or stream</b></summary>
<br>

```bash
python3 scripts/download_cmip6.py \
  --models cesm2 \
  --experiments historical \
  --resolutions monthly \
  --variables pr \
  --no-time-subset \
  --prefer-streaming
```

`--prefer-streaming` asks for OPENDAP, Zarr or Kerchunk links instead of whole-file downloads.

</details>

<p align="right"><a href="#top">⬆️ Back to top</a></p>

---

<a name="variables"></a>

## 🌡️ Variables

The default is `pr`. Pick others with `--variables`, `--variable-groups` or `--all-variables`.

### 📦 Groups

| Group | Variables |
|---|---|
| 🌤️ `core_atmos` | `pr` `tas` `tasmax` `tasmin` `huss` `hurs` `sfcwind` `psl` |
| 🌧️ `precipitation` | `pr` `prc` `prsn` |
| 🌡️ `temperature` | `tas` `tasmax` `tasmin` `ts` |
| 💨 `evaporation` | `evspsbl` `tran` `evspsblveg` `evspsblsoi` `evspsblpot` |
| 🏞️ `runoff_hydrology` | `mrro` `mrros` `rivo` `mrso` `mrsos` |
| ♨️ `surface_fluxes` | `hfls` `hfss` `evspsbl` |
| 💧 `water_balance` | `pr` `evspsbl` `mrro` `mrso` |

<details>
<summary>📖 <b>All 23 variables</b></summary>
<br>

| Key | Description | Units |
|---|---|---|
| `psl` | Sea level pressure | Pa |
| `pr` | Total precipitation flux (liquid + solid) | kg m⁻² s⁻¹ |
| `prc` | Convective precipitation flux | kg m⁻² s⁻¹ |
| `prsn` | Snowfall flux | kg m⁻² s⁻¹ |
| `tas` | Near-surface (2 m) air temperature | K |
| `tasmax` | Daily maximum near-surface air temperature | K |
| `tasmin` | Daily minimum near-surface air temperature | K |
| `ts` | Surface skin temperature | K |
| `huss` | Near-surface specific humidity | 1 |
| `hurs` | Near-surface relative humidity | % |
| `sfcwind` | Near-surface wind speed | m s⁻¹ |
| `evspsbl` | Total evaporation (including sublimation and transpiration) | kg m⁻² s⁻¹ |
| `tran` | Plant transpiration (land) | kg m⁻² s⁻¹ |
| `evspsblveg` | Canopy evaporation / interception loss | kg m⁻² s⁻¹ |
| `evspsblsoi` | Bare soil evaporation | kg m⁻² s⁻¹ |
| `evspsblpot` | Potential evapotranspiration | kg m⁻² s⁻¹ |
| `mrro` | Total runoff (surface + subsurface) | kg m⁻² s⁻¹ |
| `mrros` | Surface runoff | kg m⁻² s⁻¹ |
| `rivo` | River discharge | m³ s⁻¹ |
| `mrso` | Total soil moisture content | kg m⁻² |
| `mrsos` | Upper-layer soil moisture content | kg m⁻² |
| `hfls` | Surface upward latent heat flux | W m⁻² |
| `hfss` | Surface upward sensible heat flux | W m⁻² |

CMIP7 branding suffixes are shown by `--list-variables`.

</details>

<a name="experiments"></a>

## 🛰️ Experiments and models

Use the **key** on the command line. Years are the defaults from `config.json`.

<details open>
<summary>🔵 <b>CMIP6</b></summary>
<br>

| Key | ESGF ID | Years |
|---|---|---|
| `historical` | `historical` | 1980–2014 |
| `ssp1_1_9` | `ssp119` | 2015–2100 |
| `ssp1_2_6` | `ssp126` | 2015–2100 |
| `ssp2_4_5` | `ssp245` | 2015–2100 |
| `ssp3_7_0` | `ssp370` | 2015–2100 |
| `ssp4_3_4` | `ssp434` | 2015–2100 |
| `ssp4_6_0` | `ssp460` | 2015–2100 |
| `ssp5_3_4os` | `ssp534-over` | 2015–2100 |
| `ssp5_8_5` | `ssp585` | 2015–2100 |

</details>

<details open>
<summary>🟣 <b>CMIP7</b></summary>
<br>

| Key | ESGF ID | Years |
|---|---|---|
| `historical` | `historical` | 1980–2021 |
| `very_low` | `scen7-vl` | 2022–2100 |
| `low` | `scen7-l` | 2022–2100 |
| `medium_low` | `scen7-ml` | 2022–2100 |
| `medium` | `scen7-m` | 2022–2100 |
| `high` | `scen7-h` | 2022–2100 |

</details>

### 🤖 Model selection (pick one)

| Option | Meaning |
|---|---|
| `--models A B` | Only these models. Case, hyphens and underscores are ignored |
| `--all-models` | All models in `config.json` (58 for CMIP6, 24 for CMIP7) |
| `--no-model-filter` | Everything ESGF returns, which can be very large |

A model listed in `config.json` is not necessarily published for your request.

<p align="right"><a href="#top">⬆️ Back to top</a></p>

---

<a name="options"></a>

## 🎛️ Options

Downloads and previews need `--experiments`, `--resolutions` (`daily`, `monthly`) and one model option. `--list-variables` and `--list-indices` do not.

<details>
<summary>🔍 <b>Discovery and preview</b></summary>
<br>

| Option | Action |
|---|---|
| `--list-variables` | Show variables, CMIP7 suffixes and groups |
| `--list-indices` | Show enabled ESGF indices |
| `--probe` | Show availability for each variable, experiment and resolution |
| `--list-only` | Show matching datasets |
| `--dry-run` | Show planned output paths and log them to the manifest |

</details>

<details>
<summary>🧪 <b>Selection and subsetting</b></summary>
<br>

| Option | Action |
|---|---|
| `--variables V [V ...]` | Variable keys |
| `--variable-groups G [G ...]` | Variable groups |
| `--all-variables` | Every configured variable |
| `--variants PAT [PAT ...]` | Members whose label fully matches a regex |
| `--max-members N` | First `N` members of each model |
| `--grid LABEL` | One `grid_label`, such as `gn` or `g115` |
| `--box S N W E` | Region in degrees |
| `--years START END` | Inclusive year range |
| `--no-time-subset` | Keep all time steps |

</details>

<details>
<summary>🌐 <b>Indices, files and logging</b></summary>
<br>

| Option | Action |
|---|---|
| `--indices PAT [PAT ...]` | Use indices whose name contains a pattern |
| `--all-indices` | Search every enabled index |
| `--prefer-streaming` | Prefer streaming links |
| `--output-dir DIR` | Change the output root. Relative paths start at your home folder |
| `--overwrite` | Replace existing files |
| `--config FILE` | Use another configuration file |
| `--manifest FILE` | Change the manifest path |
| `--log-file FILE` | Also write the log to a file |
| `--verbose` | Debug logging |

CMIP6 searches the `globus` index by default; CMIP7 searches the `discovery` indices. If none match, all enabled indices are used.

</details>

## ⚙️ Configuration

Edit [`config.json`](config.json) to set your own defaults:

```json
{
  "output_dir": "~/DATA",
  "area": {
    "lat_bounds": [2, 16],
    "lon_bounds": [32, 49]
  },
  "default_variables": ["pr"]
}
```

This is an excerpt: change these values in place and keep the other keys. The default box (2–16° N, 32–49° E) covers the Ethiopia region.

<p align="right"><a href="#top">⬆️ Back to top</a></p>

---

<a name="output"></a>

## 📂 Output

```text
~/DATA/
└── 📁 cmip7/                      # or cmip6/
    ├── 🧾 manifest.jsonl
    └── 📁 historical/             # experiment key
        └── 📁 monthly/            # resolution
            └── 📁 pr/             # variable key
                └── 🌐 UKESM1-3-LL_historical_r1i1p1f2_mon_pr_tavg-u-hxy-u_g110.nc
```

Existing files are skipped unless you add `--overwrite`, so you can rerun an interrupted command.

### 🧾 Manifest statuses

| Status | Meaning |
|---|---|
| 🟢 `saved` | Written, with `bytes` and `sha256` |
| 🔵 `skipped_exists` | File was already there |
| ⚪ `empty_subset` | Nothing inside your box or years |
| 🔴 `failed` | Dataset error, with the message |
| 🟡 `dry_run_planned` / `dry_run_exists` | Preview entry |

Search-level failures and empty searches appear in the console log, not in the manifest.

Count entries by status:

```bash
python3 -c 'import collections, json, pathlib; p = pathlib.Path.home()/"DATA/cmip7/manifest.jsonl"; print(collections.Counter(json.loads(l)["status"] for l in p.open()))'
```

---

<a name="help"></a>

## 🩺 Troubleshooting

<details>
<summary>❓ <b>No datasets found</b></summary>
<br>

Run the same request with `--probe`. For CMIP7, compare the branding suffixes the index holds with the one requested.

</details>

<details>
<summary>❓ <b>No ESGF index matches</b></summary>
<br>

Run `--list-indices`, then use `--indices` or `--all-indices`.

</details>

<details>
<summary>❓ <b>Empty spatial or temporal subset</b></summary>
<br>

Check the `--box` order (SOUTH NORTH WEST EAST) and that `--years` overlaps the dataset.

</details>

<details>
<summary>❓ <b><code>ModuleNotFoundError: intake_esgf</code></b></summary>
<br>

Activate the environment with `source .venv/bin/activate`, then run `pip install -r requirements.txt`.

</details>

## 🧪 Tests

```bash
python3 -m unittest discover -v tests
```

## 🗂️ Repository layout

```text
CMIP_67/
├── 🎨 assets/banner.svg
├── 🐍 scripts/
│   ├── download_cmip.py      # core CLI
│   ├── download_cmip6.py     # CMIP6 wrapper
│   └── download_cmip7.py     # CMIP7 wrapper
├── 🧪 tests/test_helpers.py
├── ⚙️ config.json
├── 📦 requirements.txt
└── 📘 *.md                   # guides
```

## 📚 More documentation

- 📘 [User guide](cmip_67_user_guide.md)
- 📗 [Extended user guide](cmip_67_extended_user_guide.md)
- 🗂️ [Directories and file structure](cmip_67_directories_and_file_structure.md)

## 🤝 Contributing

Found a problem or have an idea? [Open an issue](https://github.com/goikelem/CMIP_6_7_Downloader/issues).

---

<div align="center">

🌍 **Happy climate data hunting!** ⭐ Star the repo if it helps your work.

<a href="#top">⬆️ Back to top</a>

</div>
