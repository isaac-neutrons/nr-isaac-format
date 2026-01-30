"""
Mock AssemblyResult fixtures for testing.

Provides realistic data patterns based on SNS neutron reflectometry.
"""

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import numpy as np


def create_minimal_assembly() -> MagicMock:
    """Create minimal AssemblyResult with only required fields."""
    mock = MagicMock()
    mock.reflectivity = {
        "id": "test-001",
        "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "facility": "unknown",
        "instrument_name": "unknown",
        "reflectivity": {
            "q": [0.01, 0.02, 0.03],
            "r": [1.0, 0.5, 0.1],
        },
    }
    mock.sample = None
    mock.environment = None
    mock.warnings = []
    mock.errors = []
    mock.needs_review = {}
    mock.reduced_file = None
    mock.model_file = None
    return mock


def create_full_assembly() -> MagicMock:
    """Create fully-populated AssemblyResult with all fields."""
    mock = MagicMock()

    # Generate realistic Q/R data
    q_values = np.logspace(-2.5, -0.5, 100).tolist()
    r_values = [_fresnel_reflectivity(q) for q in q_values]
    dr_values = [r * 0.02 for r in r_values]  # 2% error
    dq_values = [q * 0.05 for q in q_values]  # 5% resolution

    mock.reflectivity = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "facility": "SNS",
        "laboratory": "ORNL",
        "instrument_name": "REF_L",
        "run_number": "218386",
        "run_title": "Cu/Si thin film - temperature series",
        "run_start": datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        "run_end": datetime(2025, 1, 15, 11, 45, 0, tzinfo=timezone.utc),
        "probe": "neutrons",
        "technique": "reflectivity",
        "ipts_number": "IPTS-12345",
        "proposal_id": "BL-4B-12345",
        "experiment_title": "Cu thin film characterization",
        "raw_file_path": "/SNS/REF_L/IPTS-12345/nexus/REF_L_218386.nxs.h5",
        "measurement_scheme": "specular",
        "polarization": "unpolarized",
        "sample_angle": 0.5,
        "detector_angle": 1.0,
        "wavelength_min": 2.5,
        "wavelength_max": 6.0,
        "reflectivity": {
            "q": q_values,
            "r": r_values,
            "dr": dr_values,
            "dq": dq_values,
            "q_unit": "1/angstrom",
            "measurement_geometry": "front reflection",
            "reduction_version": "quicknxs 4.2.1",
            "reduction_time": datetime(2025, 1, 15, 11, 50, 0, tzinfo=timezone.utc),
            "reduction_parameters": {
                "background_roi": [0, 50],
                "signal_roi": [100, 150],
                "normalize_to_one": True,
            },
        },
    }

    mock.sample = {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "description": "Cu film on Si substrate, magnetron sputtered",
        "sample_name": "Cu_Si_001",
        "main_composition": "Cu",
        "sample_type": "thin_film",
        "preparation_method": "magnetron sputtering",
        "preparation_date": datetime(2025, 1, 10, tzinfo=timezone.utc),
        "layers": [
            {
                "layer_number": 1,
                "material": "air",
                "thickness": 0,
                "thickness_unit": "angstrom",
                "sld": 0,
                "sld_unit": "1e-6/angstrom^2",
                "roughness": 0,
            },
            {
                "layer_number": 2,
                "material": "Cu",
                "thickness": 487.3,
                "thickness_unit": "angstrom",
                "sld": 6.554,
                "sld_unit": "1e-6/angstrom^2",
                "roughness": 8.5,
                "roughness_unit": "angstrom",
            },
            {
                "layer_number": 3,
                "material": "SiO2",
                "thickness": 15.2,
                "thickness_unit": "angstrom",
                "sld": 3.47,
                "sld_unit": "1e-6/angstrom^2",
                "roughness": 3.0,
            },
            {
                "layer_number": 4,
                "material": "Si",
                "thickness": 0,
                "thickness_unit": "angstrom",
                "sld": 2.073,
                "sld_unit": "1e-6/angstrom^2",
                "roughness": 2.0,
            },
        ],
    }

    mock.environment = {
        "id": "770e8400-e29b-41d4-a716-446655440002",
        "description": "Room temperature measurement in air",
        "temperature": 298.15,
        "temperature_unit": "K",
        "ambient_medium": "air",
        "pressure": 101325.0,
        "pressure_unit": "Pa",
        "humidity": 45.0,
        "humidity_unit": "percent",
    }

    mock.warnings = ["Sample alignment may require verification"]
    mock.errors = []
    mock.needs_review = {"sample_alignment": "Check sample centering"}
    mock.reduced_file = "/data/REFL_218386_combined_data_auto.txt"
    mock.model_file = "/data/model_218386.json"

    return mock


def create_sns_refl_assembly(
    run_number: str = "218386",
    facility: str = "SNS",
    instrument: str = "REF_L",
) -> MagicMock:
    """Create SNS REF_L style AssemblyResult."""
    mock = create_full_assembly()
    mock.reflectivity["run_number"] = run_number
    mock.reflectivity["facility"] = facility
    mock.reflectivity["instrument_name"] = instrument
    mock.reflectivity["raw_file_path"] = f"/{facility}/{instrument}/IPTS-12345/nexus/{instrument}_{run_number}.nxs.h5"
    return mock


def create_simulated_assembly() -> MagicMock:
    """Create AssemblyResult for simulated data (no facility)."""
    mock = MagicMock()

    q_values = np.logspace(-2.5, -0.5, 50).tolist()
    r_values = [_fresnel_reflectivity(q) for q in q_values]

    mock.reflectivity = {
        "id": "sim-001",
        "created_at": datetime(2025, 1, 20, 10, 0, 0, tzinfo=timezone.utc),
        "facility": None,
        "instrument_name": None,
        "is_simulated": True,
        "simulation_tool": "refl1d 0.8.15",
        "probe": "neutrons",
        "reflectivity": {
            "q": q_values,
            "r": r_values,
            "measurement_geometry": "simulated",
        },
    }

    mock.sample = {
        "description": "Simulated Cu/Si interface",
        "layers": [
            {"layer_number": 1, "material": "air", "thickness": 0, "sld": 0},
            {"layer_number": 2, "material": "Cu", "thickness": 500, "sld": 6.5},
            {"layer_number": 3, "material": "Si", "thickness": 0, "sld": 2.07},
        ],
    }

    mock.environment = None
    mock.warnings = []
    mock.errors = []
    mock.needs_review = {}
    mock.reduced_file = None
    mock.model_file = "/simulations/cu_si_model.json"

    return mock


def create_partial_assembly(
    include_reflectivity: bool = True,
    include_sample: bool = False,
    include_environment: bool = False,
) -> MagicMock:
    """Create AssemblyResult with selective field population."""
    mock = MagicMock()

    if include_reflectivity:
        mock.reflectivity = {
            "id": "partial-001",
            "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            "facility": "SNS",
            "instrument_name": "REF_L",
            "reflectivity": {
                "q": [0.01, 0.02, 0.03],
                "r": [1.0, 0.5, 0.1],
            },
        }
    else:
        mock.reflectivity = None

    if include_sample:
        mock.sample = {
            "description": "Test sample",
            "main_composition": "Cu",
        }
    else:
        mock.sample = None

    if include_environment:
        mock.environment = {
            "temperature": 298.0,
            "ambient_medium": "air",
        }
    else:
        mock.environment = None

    mock.warnings = []
    mock.errors = []
    mock.needs_review = {}
    mock.reduced_file = None
    mock.model_file = None

    return mock


def _fresnel_reflectivity(q: float, sld_substrate: float = 2.07e-6) -> float:
    """Calculate approximate Fresnel reflectivity for testing."""
    import math

    qc = math.sqrt(16 * math.pi * sld_substrate)  # Critical Q
    if q < qc:
        return 1.0
    return (qc / (2 * q)) ** 4
