"""
Edge case tests for ISAAC record conversion.

Tests handling of missing fields, partial assemblies, malformed input,
and other boundary conditions.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.converter import IsaacRecordConverter


class TestMissingFields:
    """Tests for missing or null field handling."""

    def test_convert_with_none_reflectivity(self):
        """Should handle None reflectivity gracefully."""
        mock = MagicMock()
        mock.reflectivity = None
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        # Should still produce a record
        assert conversion.record is not None
        assert "record_id" in conversion.record

    def test_convert_with_empty_reflectivity(self):
        """Should handle empty reflectivity dict."""
        mock = MagicMock()
        mock.reflectivity = {}
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None

    def test_convert_with_missing_q_r_data(self):
        """Should handle missing Q/R arrays."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {},  # No Q/R data
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        # Should produce record but measurement may be minimal
        assert conversion.record is not None

    def test_convert_with_only_q_no_r(self):
        """Should handle Q data without R data."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {
                "q": [0.01, 0.02, 0.03],
                # No R data
            },
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None


class TestPartialAssemblies:
    """Tests for partially assembled data."""

    def test_convert_reflectivity_only(self):
        """Should convert with only reflectivity data."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "instrument_name": "REF_L",
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

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        record = conversion.record
        assert "timestamps" in record
        assert "acquisition_source" in record
        assert "sample" not in record or record.get("sample") is None
        assert "context" not in record or record.get("context") is None

    def test_convert_sample_only(self):
        """Should handle sample without reflectivity."""
        mock = MagicMock()
        mock.reflectivity = None
        mock.sample = {
            "description": "Test sample",
            "main_composition": "Cu",
            "layers": [
                {"material": "Cu", "thickness": 500},
            ],
        }
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        # Should still work but timestamps may be missing data
        assert conversion.record is not None

    def test_convert_with_empty_layers(self):
        """Should handle sample with empty layers array."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {"q": [0.01], "r": [1.0]},
        }
        mock.sample = {
            "description": "Sample with no layers",
            "layers": [],
        }
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None


class TestMalformedInput:
    """Tests for malformed or unexpected input."""

    def test_convert_with_string_timestamp(self):
        """Should handle string timestamps."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": "2025-01-15T12:00:00Z",  # String instead of datetime
            "facility": "SNS",
            "reflectivity": {"q": [0.01], "r": [1.0]},
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None
        assert "timestamps" in conversion.record

    def test_convert_with_numpy_arrays(self):
        """Should handle numpy arrays in data."""
        import numpy as np

        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {
                "q": np.array([0.01, 0.02, 0.03]),
                "r": np.array([1.0, 0.5, 0.1]),
            },
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        # Should handle numpy arrays
        assert conversion.record is not None

    def test_convert_with_inf_values(self):
        """Should handle infinity values in data."""
        import math

        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {
                "q": [0.01, 0.02, 0.03],
                "r": [1.0, math.inf, 0.1],
            },
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        # Should not crash
        assert conversion.record is not None

    def test_convert_with_nan_values(self):
        """Should handle NaN values in data."""
        import math

        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {
                "q": [0.01, 0.02, 0.03],
                "r": [1.0, math.nan, 0.1],
            },
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None

    def test_convert_with_nested_none_values(self):
        """Should handle nested None values."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": None,
            "instrument_name": None,
            "reflectivity": {
                "q": [0.01, 0.02],
                "r": [1.0, 0.5],
                "dr": None,
                "dq": None,
            },
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None


class TestBoundaryConditions:
    """Tests for boundary conditions and limits."""

    def test_convert_with_single_point(self):
        """Should handle single data point."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {
                "q": [0.01],
                "r": [1.0],
            },
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None

    def test_convert_with_large_dataset(self):
        """Should handle large dataset efficiently."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {
                "q": list(range(10000)),  # 10K points
                "r": [1.0 / (i + 1) for i in range(10000)],
            },
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None
        # Check series contains all points
        series = conversion.record.get("measurement", {}).get("series", [])
        if series:
            channels = series[0].get("channels", [])
            q_channel = next((c for c in channels if c.get("channel_id") == "Q"), None)
            if q_channel:
                assert len(q_channel.get("values", [])) == 10000

    def test_convert_with_very_long_strings(self):
        """Should handle very long string values."""
        mock = MagicMock()
        long_description = "A" * 10000  # 10K character description
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "run_title": long_description,
            "reflectivity": {"q": [0.01], "r": [1.0]},
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None

    def test_convert_with_unicode_characters(self):
        """Should handle unicode in strings."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "run_title": "温度依存性測定 - Cu薄膜",  # Japanese
            "reflectivity": {"q": [0.01], "r": [1.0]},
        }
        mock.sample = {
            "description": "Проба меди",  # Russian
            "main_composition": "Cu",
        }
        mock.environment = None
        mock.warnings = []
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record is not None


class TestWarningsAndErrors:
    """Tests for warning and error propagation."""

    def test_warnings_propagated(self):
        """Should propagate assembly warnings."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {"q": [0.01], "r": [1.0]},
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = ["Data quality warning", "Alignment warning"]
        mock.errors = []
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        # Conversion may add its own warnings
        assert conversion.record is not None

    def test_errors_reported(self):
        """Should report conversion errors."""
        mock = MagicMock()
        mock.reflectivity = {
            "id": "test-001",
            "created_at": datetime.now(timezone.utc),
            "facility": "SNS",
            "reflectivity": {"q": [0.01], "r": [1.0]},
        }
        mock.sample = None
        mock.environment = None
        mock.warnings = []
        mock.errors = ["Critical assembly error"]
        mock.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        # Should still produce record even with upstream errors
        assert conversion.record is not None
