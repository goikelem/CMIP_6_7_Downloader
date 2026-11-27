"""Unit tests for the pure helpers (need only numpy):  python3 -m unittest discover tests"""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from download_cmip import (  # noqa: E402
    norm_model, safe_name, lonlat_mask, spatial_indexers,
    year_indexer, parse_args, variant_rank, variant_matches,
    pick_first_members, member_mask, resolve_variables,
    validate_config, dataset_stem, sha256_file, main,
)

BOX = (2, 16, 32, 49)  # Ethiopia


class Helpers(unittest.TestCase):
    def test_norm_model_matches_config_aliases(self):
        for alias, canon in [
            ("e3sm_1_0", "E3SM-1-0"),
            ("mpi_esm_1_2_ham", "MPI-ESM-1-2-HAM"),
            ("inm_cm4_8", "INM-CM4-8"),
            ("ACCESS-ESM1-6", "access_esm1_6"),
            ("CanESM5-1", "canesm51"),
            ("UKCM2a-0-HH", "ukcm2a0hh"),
        ]:
            self.assertEqual(norm_model(alias), norm_model(canon))

    def test_safe_name(self):
        self.assertEqual(safe_name("a/b c.d"), "a_b_c.d")

    def _lon_select(self, lon, box=BOX):
        lat = np.arange(-89.5, 90, 1.0)
        ix = spatial_indexers(lat, ("lat",), lon, ("lon",), box)
        return lat[ix["lat"]], lon[ix["lon"]]

    def test_lon_0_360(self):
        la, lo = self._lon_select(np.arange(0.5, 360, 1.0))
        self.assertTrue(lo.min() >= 32 and lo.max() <= 49 and len(lo) == 17)
        self.assertTrue(la.min() >= 2 and la.max() <= 16)

    def test_lon_minus180_180(self):
        la, lo = self._lon_select(np.arange(-179.5, 180, 1.0))
        self.assertTrue(lo.min() >= 32 and lo.max() <= 49 and len(lo) == 17)

    def test_separate_1d_dims_returns_true_lon_indices(self):
        lat = np.array([0.0, 5.0, 10.0, 20.0])
        lon = np.array([10.0, 35.0, 45.0, 60.0])
        ix = spatial_indexers(lat, ("y",), lon, ("x",), BOX)
        self.assertEqual(list(ix["y"]), [1, 2])
        self.assertEqual(list(ix["x"]), [1, 2])

    def test_negative_west_on_both_conventions(self):
        box = (-10, 10, -20, 20)
        for lon in (np.arange(0.5, 360, 1.0), np.arange(-179.5, 180, 1.0)):
            _, lo = self._lon_select(lon, box)
            self.assertEqual(len(lo), 40)

    def test_dateline_crossing(self):
        _, lo = self._lon_select(np.arange(0.5, 360, 1.0), (-10, 10, 170, -170))
        self.assertEqual(len(lo), 20)
        self.assertTrue(all((x >= 170) or (x <= 190) for x in lo))

    def test_descending_latitude(self):
        lat = np.arange(89.5, -90, -1.0)
        ix = spatial_indexers(lat, ("lat",), np.arange(0.5, 360), ("lon",), BOX)
        self.assertEqual(len(ix["lat"]), 14)

    def test_curvilinear_2d(self):
        lon2, lat2 = np.meshgrid(np.arange(0.5, 360), np.arange(-89.5, 90))
        ix = spatial_indexers(lat2, ("y", "x"), lon2, ("y", "x"), BOX)
        self.assertEqual((len(ix["y"]), len(ix["x"])), (14, 17))

    def test_unstructured_shared_dim(self):
        lat = np.array([0., 5., 10., 50.])
        lon = np.array([40., 40., 300., 40.])
        ix = spatial_indexers(lat, ("ncol",), lon, ("ncol",), BOX)
        self.assertEqual(list(ix["ncol"]), [1])

    def test_empty_box(self):
        ix = spatial_indexers(
            np.arange(-90., 91, 30), ("lat",), np.arange(0., 360, 30), ("lon",), (1, 2, 1, 2)
        )
        self.assertEqual(len(ix["lat"]), 0)

    def test_invalid_box(self):
        with self.assertRaises(ValueError):
            lonlat_mask(np.zeros(2), np.zeros(2), 10, 0, 0, 1)

    def test_year_indexer(self):
        self.assertEqual(list(year_indexer([1979, 1980, 2014, 2015], 1980, 2014)), [1, 2])

    def test_dataset_stem_cmip6_and_cmip7(self):
        row6 = {
            "source_id": "CESM2",
            "experiment_id": "historical",
            "member_id": "r1i1p1f1",
            "table_id": "Amon",
            "variable_id": "pr",
            "grid_label": "gn",
        }
        self.assertEqual(
            dataset_stem(row6, "fallback", list(row6.keys())),
            "CESM2_historical_r1i1p1f1_Amon_pr_gn",
        )
        row7 = {
            "source_id": "CESM3",
            "experiment_id": "scen7-m",
            "variant_label": "r1i1p1f1",
            "frequency": "mon",
            "variable_id": "tas",
            "variable_branding_suffix": "tmaxavg-h2m-hxy-u",
            "grid_label": "g115",
        }
        self.assertEqual(
            dataset_stem(row7, "fallback", list(row7.keys())),
            "CESM3_scen7-m_r1i1p1f1_mon_tas_tmaxavg-h2m-hxy-u_g115",
        )

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sample.bin"
            p.write_bytes(b"cmip67")
            self.assertEqual(len(sha256_file(p)), 64)

    def test_validate_config_rejects_incomplete(self):
        with self.assertRaises(SystemExit):
            validate_config({"output_dir": "~/DATA"})


class VariantSelection(unittest.TestCase):
    def test_variant_rank(self):
        self.assertEqual(variant_rank("r1i1p1f1"), (1, 1, 1, 1))
        self.assertLess(variant_rank("r2i1p1f1"), variant_rank("r10i1p1f1"))
        self.assertLess(variant_rank("r1i1p1f1"), variant_rank("r1i1p2f1"))
        self.assertLess(variant_rank("r1i1p1f1"), variant_rank("weird"))

    def test_variant_matches_fullmatch_semantics(self):
        self.assertTrue(variant_matches("r1i1p1f1", ["r1i1p1f1"]))
        self.assertFalse(variant_matches("r10i1p1f1", ["r1i1p1f1"]))
        self.assertTrue(variant_matches("r10i1p1f1", ["r1.*"]))
        self.assertTrue(variant_matches("r1i1p1f1", ["r[1-3]i.*"]))
        self.assertFalse(variant_matches("r4i1p1f1", ["r[1-3]i.*"]))

    def test_pick_first_members(self):
        pairs = [
            ("A", "r1i1p1f1"), ("A", "r10i1p1f1"), ("A", "r2i1p1f1"),
            ("B", "r1i1p2f1"), ("B", "r3i1p1f1"),
        ]
        keep = pick_first_members(pairs, 1)
        self.assertEqual(keep, {("A", "r1i1p1f1"), ("B", "r1i1p2f1")})
        keep2 = pick_first_members(pairs, 2)
        self.assertEqual(
            keep2,
            {("A", "r1i1p1f1"), ("A", "r2i1p1f1"), ("B", "r1i1p2f1"), ("B", "r3i1p1f1")},
        )

    def test_member_mask_patterns(self):
        pairs = [("A", "r1i1p1f1"), ("A", "r2i1p1f1"), ("B", "r1i1p1f1")]
        self.assertEqual(member_mask(pairs, patterns=["r1i.*"]), [True, False, True])
        self.assertEqual(member_mask(pairs, patterns=["r2i1p1f1"]), [False, True, False])

    def test_member_mask_max_members(self):
        pairs = [("A", "r1i1p1f1"), ("A", "r10i1p1f1"), ("A", "r2i1p1f1"), ("B", "r1i1p1f1")]
        self.assertEqual(member_mask(pairs, max_members=1), [True, False, False, True])
        self.assertEqual(member_mask(pairs, max_members=2), [True, False, True, True])

    def test_member_mask_noop(self):
        pairs = [("A", "r1i1p1f1"), ("B", "r1i1p1f1")]
        self.assertEqual(member_mask(pairs), [True, True])


class Cli(unittest.TestCase):
    def test_basic(self):
        a = parse_args([
            "--project", "cmip6", "--all-models", "--experiments", "historical",
            "--resolutions", "daily", "--dry-run",
        ])
        self.assertTrue(a.all_models)
        self.assertTrue(a.dry_run)
        with self.assertRaises(SystemExit):
            parse_args(["--project", "cmip6", "--experiments", "historical", "--resolutions", "daily"])

    def test_list_indices_runs_without_experiments(self):
        class FakeCatalog:
            indices = ["esgf-node.llnl.gov (globus)", "esgf2-discovery"]

        fake_mod = types.SimpleNamespace(ESGFCatalog=FakeCatalog)
        with mock.patch.dict(sys.modules, {"intake_esgf": fake_mod}):
            rc = main(["--project", "cmip6", "--list-indices"])
        self.assertEqual(rc, 0)

    def test_member_flags(self):
        a = parse_args([
            "--project", "cmip7", "--models", "UKESM1-3-LL",
            "--experiments", "high", "--resolutions", "daily",
            "--variants", "r1i.*",
        ])
        self.assertEqual(a.variants, ["r1i.*"])
        b = parse_args([
            "--project", "cmip7", "--models", "UKESM1-3-LL",
            "--experiments", "high", "--resolutions", "daily",
            "--max-members", "3",
        ])
        self.assertEqual(b.max_members, 3)
        for bad in (
            ["--variants", "r1.*", "--max-members", "2"],
            ["--max-members", "0"],
            ["--variants", "r[1-"],
            ["--indices", "east", "--all-indices"],
        ):
            with self.assertRaises(SystemExit):
                parse_args([
                    "--project", "cmip7", "--models", "M",
                    "--experiments", "high", "--resolutions", "daily", *bad,
                ])

    def test_index_and_streaming_flags(self):
        a = parse_args([
            "--project", "cmip7", "--all-models", "--experiments", "high",
            "--resolutions", "daily", "--indices", "east", "west",
            "--prefer-streaming", "--grid", "g115",
        ])
        self.assertEqual(a.indices, ["east", "west"])
        self.assertTrue(a.prefer_streaming)
        self.assertEqual(a.grid, "g115")

    def test_variable_group_flags(self):
        a = parse_args([
            "--project", "cmip7", "--all-models", "--experiments", "high",
            "--resolutions", "monthly", "--variable-groups", "water_balance",
            "--variables", "tas",
        ])
        self.assertEqual(a.variable_groups, ["water_balance"])
        self.assertEqual(a.variables, ["tas"])
        b = parse_args(["--project", "cmip7", "--list-variables"])
        self.assertTrue(b.list_variables)
        with self.assertRaises(SystemExit):
            parse_args([
                "--project", "cmip7", "--all-models", "--experiments", "high",
                "--resolutions", "daily", "--all-variables", "--variable-groups", "water_balance",
            ])

    def test_resolve_variables_dedup_and_validation(self):
        sample_cfg = {
            "default_variables": ["pr"],
            "variables": {"pr": {}, "tas": {}, "evspsbl": {}, "mrro": {}, "mrso": {}},
            "variable_groups": {
                "water_balance": ["pr", "evspsbl", "mrro", "mrso"],
            },
        }
        res = resolve_variables(sample_cfg, variables=["tas", "pr"], variable_groups=["water_balance"])
        self.assertEqual(res, ["pr", "evspsbl", "mrro", "mrso", "tas"])
        with self.assertRaises(SystemExit):
            resolve_variables(sample_cfg, variable_groups=["nonexistent_group"])
        with self.assertRaises(SystemExit):
            resolve_variables(sample_cfg, variables=["nonexistent_var"])


if __name__ == "__main__":
    unittest.main()
