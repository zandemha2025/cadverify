"""Tests for the YAML-based structured material database."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import mock

import pytest

from src.analysis.models import ProcessType
from src.profiles.models import MaterialProfile


# ---------------------------------------------------------------------------
# YAML file parsing
# ---------------------------------------------------------------------------

class TestYamlFilesLoad:
    """Verify every YAML file in materials/ parses without error."""

    def _yaml_files(self) -> list[Path]:
        materials_dir = Path(__file__).resolve().parent.parent / "src" / "profiles" / "materials"
        return sorted(materials_dir.glob("*.yaml"))

    def test_yaml_directory_has_15_files(self):
        files = self._yaml_files()
        assert len(files) == 15, f"Expected 15 YAML files, found {len(files)}: {[f.name for f in files]}"

    def test_all_yaml_files_parse(self):
        import yaml

        for filepath in self._yaml_files():
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{filepath.name} did not parse to a dict"
            assert "name" in data, f"{filepath.name} missing 'name' key"
            assert "processes" in data, f"{filepath.name} missing 'processes' key"
            assert "mechanical" in data, f"{filepath.name} missing 'mechanical' key"
            assert "dfm" in data, f"{filepath.name} missing 'dfm' key"


# ---------------------------------------------------------------------------
# Loader produces MaterialProfile objects
# ---------------------------------------------------------------------------

class TestLoaderProducesMaterialProfiles:
    """All 15 YAML materials load into MaterialProfile objects."""

    def test_yaml_materials_count(self):
        from src.profiles.loader import MATERIALS_STRUCTURED

        assert len(MATERIALS_STRUCTURED) >= 15

    def test_yaml_materials_are_material_profile(self):
        from src.profiles.loader import MATERIALS_STRUCTURED

        for m in MATERIALS_STRUCTURED:
            assert isinstance(m, MaterialProfile), f"{m} is not a MaterialProfile"

    def test_yaml_material_has_enhanced_fields(self):
        from src.profiles.loader import MATERIALS_STRUCTURED

        ti = next((m for m in MATERIALS_STRUCTURED if "Ti-6Al-4V" in m.name), None)
        assert ti is not None, "Ti-6Al-4V not found in MATERIALS_STRUCTURED"
        assert ti.alloy_designation == "AMS 4928"
        assert len(ti.standards) >= 3
        assert "nace_mr0175" in ti.compliance
        assert len(ti.min_wall_by_process) > 0
        assert ti.machinability_index == 25
        assert ti.thermal_conductivity == 6.7
        assert ti.hardness_hrc == 36


# ---------------------------------------------------------------------------
# get_material_by_name
# ---------------------------------------------------------------------------

class TestGetMaterialByName:
    def test_exact_name(self):
        from src.profiles.database import get_material_by_name

        mat = get_material_by_name("Ti-6Al-4V Grade 5")
        assert mat is not None
        assert mat.name == "Ti-6Al-4V Grade 5"

    def test_case_insensitive(self):
        from src.profiles.database import get_material_by_name

        mat = get_material_by_name("ti-6al-4v grade 5")
        assert mat is not None

    def test_not_found(self):
        from src.profiles.database import get_material_by_name

        assert get_material_by_name("Unobtanium") is None


# ---------------------------------------------------------------------------
# get_compliant_materials
# ---------------------------------------------------------------------------

class TestGetCompliantMaterials:
    def test_nace_mr0175_includes_duplex_and_inconel_625(self):
        from src.profiles.database import get_compliant_materials

        nace = get_compliant_materials("nace_mr0175")
        names = [m.name for m in nace]
        assert any("Duplex" in n for n in names), f"Duplex 2205 not in NACE list: {names}"
        assert any("625" in n for n in names), f"Inconel 625 not in NACE list: {names}"

    def test_biocompatible(self):
        from src.profiles.database import get_compliant_materials

        bio = get_compliant_materials("biocompatible")
        names = [m.name for m in bio]
        assert any("CoCr" in n for n in names), f"CoCr not in biocompatible list: {names}"

    def test_unknown_standard_returns_empty(self):
        from src.profiles.database import get_compliant_materials

        assert get_compliant_materials("nonexistent_standard") == []


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_materials_list_exists_and_nonempty(self):
        from src.profiles.database import MATERIALS

        assert len(MATERIALS) >= 41  # at least the original 41

    def test_machines_list_exists(self):
        from src.profiles.database import MACHINES

        assert len(MACHINES) == 19

    def test_get_materials_for_process_fdm(self):
        from src.profiles.database import get_materials_for_process

        fdm_mats = get_materials_for_process(ProcessType.FDM)
        assert len(fdm_mats) >= 7  # original 7 FDM materials
        names = [m.name for m in fdm_mats]
        assert "PLA" in names or any("PLA" in n for n in names)

    def test_get_machines_for_process(self):
        from src.profiles.database import get_machines_for_process

        fdm_machines = get_machines_for_process(ProcessType.FDM)
        assert len(fdm_machines) >= 4

    def test_get_all_processes(self):
        from src.profiles.database import get_all_processes

        procs = get_all_processes()
        assert len(procs) == len(ProcessType)
        for p in procs:
            assert "process" in p
            assert "material_count" in p

    def test_material_profile_backward_compat_construction(self):
        """Existing code that constructs MaterialProfile without new fields still works."""
        m = MaterialProfile(
            "TestMat",
            [ProcessType.FDM],
            1.0,
            100,
            50,
            10,
            1.0,
            5,
            "test",
        )
        assert m.alloy_designation is None
        assert m.standards == []
        assert m.compliance == {}
        assert m.min_wall_by_process == {}
        assert m.machinability_index is None
        assert m.thermal_conductivity is None
        assert m.hardness_hrc is None


# ---------------------------------------------------------------------------
# PyYAML fallback
# ---------------------------------------------------------------------------

class TestPyYamlFallback:
    def test_graceful_fallback_without_pyyaml(self):
        """If PyYAML is not importable, load_yaml_materials returns []."""
        from src.profiles import loader

        # Temporarily make yaml un-importable
        with mock.patch.dict(sys.modules, {"yaml": None}):
            result = loader.load_yaml_materials()
        assert result == []


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

class TestMerge:
    def test_yaml_overrides_hardcoded_by_name(self):
        """YAML materials with matching names replace hardcoded entries."""
        from src.profiles.loader import merge_materials

        hc = [MaterialProfile("PLA", [ProcessType.FDM], 0.8, 60, 50, 6, 1.24, 25)]
        yaml_m = [MaterialProfile("PLA", [ProcessType.FDM], 0.8, 60, 50, 6, 1.24, 25, "from yaml",
                                  standards=["ISO 527"])]
        merged = merge_materials(hc, yaml_m)
        assert len(merged) == 1
        assert merged[0].notes == "from yaml"
        assert merged[0].standards == ["ISO 527"]

    def test_yaml_only_materials_appended(self):
        from src.profiles.loader import merge_materials

        hc = [MaterialProfile("PLA", [ProcessType.FDM], 0.8, 60, 50, 6, 1.24, 25)]
        yaml_m = [MaterialProfile("NewMat", [ProcessType.SLS], 0.5, 200, 80, 10, 1.1, 50)]
        merged = merge_materials(hc, yaml_m)
        assert len(merged) == 2
        assert merged[1].name == "NewMat"
