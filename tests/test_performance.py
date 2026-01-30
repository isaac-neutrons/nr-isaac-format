"""Performance benchmarks for ISAAC record conversion.

These tests verify that conversion performance meets acceptable thresholds.
Run with: pytest tests/test_performance.py -v
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from nr_isaac_format import IsaacRecordConverter


def _fresnel_reflectivity(q: float, qc: float = 0.0217) -> float:
    """Calculate Fresnel reflectivity for silicon."""
    if q < qc:
        return 1.0
    r = ((q - np.sqrt(q**2 - qc**2)) / (q + np.sqrt(q**2 - qc**2))) ** 2
    return float(r)


def create_assembly_result(n_points: int = 100):
    """Create a mock AssemblyResult with specified data size."""
    q_values = np.logspace(-3, 0, n_points).tolist()
    r_values = [_fresnel_reflectivity(q) * (1 + 0.01 * np.random.randn()) for q in q_values]
    dr_values = [abs(r) * 0.05 for r in r_values]
    dq_values = [q * 0.05 for q in q_values]
    
    mock = MagicMock()
    mock.reflectivity = {
        "id": "test-perf-001",
        "created_at": datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        "facility": "SNS",
        "laboratory": "ORNL",
        "instrument_name": "REF_L",
        "run_number": "218386",
        "probe": "neutrons",
        "technique": "reflectivity",
        "reflectivity": {
            "q": q_values,
            "r": r_values,
            "dr": dr_values,
            "dq": dq_values,
            "q_unit": "1/angstrom",
            "measurement_geometry": "front reflection",
        },
    }
    mock.sample = {
        "name": "Cu/Si Thin Film",
        "formula": "Cu",
        "substrate": {"name": "Si", "formula": "Si"},
        "layers": [{"name": "Cu", "thickness": 500, "roughness": 5}],
        "geometry": {"form": "thin_film", "area_cm2": 4.0},
    }
    mock.environment = {
        "temperature": {"value": 295.0, "unit": "K"},
    }
    mock.warnings = []
    mock.errors = []
    mock.needs_review = {}
    mock.reduced_file = None
    mock.model_file = None
    
    return mock


class TestConversionPerformance:
    """Benchmark tests for single record conversion."""
    
    def test_single_conversion_without_validation(self):
        """Single conversion without validation should be fast (<50ms)."""
        assembly = create_assembly_result(n_points=200)
        converter = IsaacRecordConverter(validate_output=False)
        
        start = time.perf_counter()
        result = converter.convert(assembly)
        elapsed = time.perf_counter() - start
        
        assert result.is_valid, f"Conversion errors: {result.errors}"
        assert elapsed < 0.050, f"Conversion took {elapsed*1000:.1f}ms, expected <50ms"
    
    def test_single_conversion_with_validation(self):
        """Single conversion with validation should complete in <100ms."""
        assembly = create_assembly_result(n_points=200)
        converter = IsaacRecordConverter(validate_output=True)
        
        start = time.perf_counter()
        result = converter.convert(assembly)
        elapsed = time.perf_counter() - start
        
        assert result.is_valid, f"Conversion errors: {result.errors}"
        assert elapsed < 0.100, f"Conversion took {elapsed*1000:.1f}ms, expected <100ms"
    
    def test_large_dataset_conversion(self):
        """Large dataset (10K points) should convert in <500ms."""
        assembly = create_assembly_result(n_points=10000)
        converter = IsaacRecordConverter(validate_output=False)
        
        start = time.perf_counter()
        result = converter.convert(assembly)
        elapsed = time.perf_counter() - start
        
        assert result.is_valid, f"Conversion errors: {result.errors}"
        
        # Verify data size
        record = result.record
        measurement = record.get("measurement", {})
        series = measurement.get("series", [])
        if series:
            # Check for data in independent_variables or channels
            ivars = series[0].get("independent_variables", [])
            if ivars:
                data_points = len(ivars[0].get("values", []))
                assert data_points == 10000, f"Expected 10000 points, got {data_points}"
        
        assert elapsed < 0.500, f"Conversion took {elapsed*1000:.1f}ms, expected <500ms"
    
    def test_repeated_conversions(self):
        """Multiple conversions should not accumulate state."""
        assembly = create_assembly_result(n_points=100)
        converter = IsaacRecordConverter(validate_output=False)
        
        # Warm up
        result = converter.convert(assembly)
        assert result.is_valid, f"Warmup failed: {result.errors}"
        
        times = []
        for _ in range(10):
            start = time.perf_counter()
            result = converter.convert(assembly)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert result.is_valid, f"Conversion failed: {result.errors}"
        
        avg_time = sum(times) / len(times)
        max_time = max(times)
        
        # No significant degradation
        assert max_time < avg_time * 10 or max_time < 0.001, f"Max time {max_time*1000:.1f}ms >> avg {avg_time*1000:.1f}ms"


class TestBatchPerformance:
    """Benchmark tests for batch conversion."""
    
    def test_batch_conversion_10_records(self):
        """Batch of 10 records should complete in <1s."""
        assemblies = [create_assembly_result(n_points=100) for _ in range(10)]
        converter = IsaacRecordConverter(validate_output=True)
        
        start = time.perf_counter()
        results = [converter.convert(a) for a in assemblies]
        elapsed = time.perf_counter() - start
        
        for i, r in enumerate(results):
            assert r.is_valid, f"Record {i} failed: {r.errors}"
        assert elapsed < 1.0, f"Batch took {elapsed:.2f}s, expected <1s"
    
    def test_batch_conversion_100_records(self):
        """Batch of 100 records should complete in <10s."""
        assemblies = [create_assembly_result(n_points=100) for _ in range(100)]
        converter = IsaacRecordConverter(validate_output=True)
        
        start = time.perf_counter()
        results = [converter.convert(a) for a in assemblies]
        elapsed = time.perf_counter() - start
        
        for i, r in enumerate(results):
            assert r.is_valid, f"Record {i} failed: {r.errors}"
        assert elapsed < 10.0, f"Batch took {elapsed:.2f}s, expected <10s"
        
        avg_per_record = elapsed / 100
        print(f"\nAverage time per record: {avg_per_record*1000:.1f}ms")


class TestJsonSerializationPerformance:
    """Benchmark tests for JSON serialization."""
    
    def test_json_serialization_speed(self):
        """JSON serialization should be fast."""
        assembly = create_assembly_result(n_points=1000)
        converter = IsaacRecordConverter(validate_output=False)
        result = converter.convert(assembly)
        assert result.is_valid, f"Conversion failed: {result.errors}"
        
        start = time.perf_counter()
        json_str = result.to_json(indent=2)
        elapsed = time.perf_counter() - start
        
        assert len(json_str) > 0
        assert elapsed < 0.100, f"Serialization took {elapsed*1000:.1f}ms, expected <100ms"
    
    def test_large_record_serialization(self):
        """Large record JSON serialization."""
        assembly = create_assembly_result(n_points=10000)
        converter = IsaacRecordConverter(validate_output=False)
        result = converter.convert(assembly)
        assert result.is_valid, f"Conversion failed: {result.errors}"
        
        start = time.perf_counter()
        json_str = result.to_json(indent=None)  # Compact
        elapsed = time.perf_counter() - start
        
        # Large dataset should produce substantial output (at least 500KB)
        assert len(json_str) > 500000, f"Expected >500KB, got {len(json_str)/1000:.1f}KB"
        assert elapsed < 0.500, f"Serialization took {elapsed*1000:.1f}ms, expected <500ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
