# Directory and File Structure

## Repository Layout
```text
CMIP_67/
├── config.json                                 # Area bounds, variables, CMIP7 branding suffixes, experiments, models
├── requirements.txt                            # Python package dependencies
├── .gitignore                                  # Excludes __pycache__, *.pyc, .part temporary files
├── README.md                                   # Overview and quickstart commands
├── cmip_67_user_guide.md                       # Detailed CLI workflows and options
├── cmip_67_directories_and_file_structure.md   # Repository and output layout reference
├── scripts/
│   ├── download_cmip.py                        # Core search, subsetting, and NetCDF writer CLI
│   ├── download_cmip6.py                       # CMIP6 CLI wrapper
│   └── download_cmip7.py                       # CMIP7 CLI wrapper
└── tests/
    └── test_helpers.py                         # Unit tests for spatial indexing, variants, CLI, and config validation
```

## Output Directory Layout
Subsets are written under `<output_dir>/<project>/` (default `~/DATA/<project>/`):
```text
~/DATA/
├── cmip6/
│   ├── manifest.jsonl
│   └── <experiment_key>/
│       └── <daily|monthly>/
│           └── <variable_key>/
│               └── <source_id>_<experiment_id>_<member_id>_<table_id>_<variable_id>_<grid_label>.nc
└── cmip7/
    ├── manifest.jsonl
    └── <experiment_key>/
        └── <daily|monthly>/
            └── <variable_key>/
                └── <source_id>_<experiment_id>_<variant_label>_<frequency>_<variable_id>_<branding_suffix>_<grid_label>.nc
```
