"""
Sample block mapper for ISAAC records.

Maps sample information from the data-assembler sample record
(derived from model layer stack) to the ISAAC sample block.
"""

from typing import Any, Optional

from ..constants import SampleForm
from .base import Mapper, MapperContext


class SampleMapper(Mapper):
    """
    Maps sample data from data-assembler to ISAAC sample block.

    Source fields:
    - sample.main_composition -> material.name, material.formula
    - sample.layers -> composition, geometry
    - sample.description -> material.notes

    ISAAC Schema:
    ```json
    "sample": {
        "material": {
            "name": "Copper",
            "formula": "Cu",
            "provenance": "model_fitted"
        },
        "sample_form": "thin_film",
        "composition": { ... },
        "geometry": { ... }
    }
    ```
    """

    @property
    def block_name(self) -> str:
        return "sample"

    def is_required(self) -> bool:
        return False  # Optional block

    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Map sample data from data-assembler sample record.

        Returns None if no sample data available.
        Falls back to reflectivity record for basic sample info if sample record missing.
        """
        # Try to get sample data from sample record first
        sample = context.sample

        # Fallback to reflectivity for basic sample info
        if not sample and context.reflectivity:
            sample = self._extract_sample_from_reflectivity(context.reflectivity)

        if not sample:
            return None

        # Build material block
        material = self._build_material(sample, context)

        # Determine sample form (default to thin_film for reflectometry)
        sample_form = self._determine_sample_form(sample, context)

        result: dict[str, Any] = {
            "sample_form": sample_form,
        }

        # Add material if we have useful data
        if material.get("material_name") != "Unknown" or material.get("notes"):
            result["material"] = material

        # Add sample description if available
        description = sample.get("sample_description") or sample.get("description")
        if description:
            result["sample_description"] = description

        # Add composition if we can extract it
        composition = self._build_composition(sample, context)
        if composition:
            result["composition"] = composition

        # Add geometry if we can extract it
        geometry = self._build_geometry(sample, context)
        if geometry:
            result["geometry"] = geometry

        # Return None if we only have default values
        if result == {"sample_form": "thin_film"}:
            return None

        return result

    def _extract_sample_from_reflectivity(
        self, reflectivity: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Extract sample info from reflectivity record as fallback."""
        sample: dict[str, Any] = {}

        sample_name = reflectivity.get("sample_name")
        if sample_name:
            sample["main_composition"] = sample_name

        sample_desc = reflectivity.get("sample_description")
        if sample_desc:
            sample["sample_description"] = sample_desc

        return sample if sample else None

    def _build_material(
        self, sample: dict[str, Any], context: MapperContext
    ) -> dict[str, Any]:
        """Build the material sub-block."""
        material: dict[str, Any] = {}

        # Get main composition as material name (schema uses 'name' and 'formula')
        main_comp = sample.get("main_composition")
        if main_comp:
            material["name"] = main_comp
            material["formula"] = main_comp  # Use same value if no specific formula
        else:
            material["name"] = "Unknown"
            material["formula"] = "Unknown"
            context.add_warning("Sample main_composition not found")

        # Provenance indicates this came from model fitting
        material["provenance"] = "model_fitted"

        # Add description as notes if available
        description = sample.get("description") or sample.get("sample_description")
        if description:
            material["notes"] = description

        return material

    def _determine_sample_form(
        self, sample: dict[str, Any], context: MapperContext
    ) -> str:
        """
        Determine the sample form.

        For neutron reflectometry, samples are typically thin films
        on substrates, so default to 'thin_film'.
        """
        # Check if geometry hint is provided
        geometry = sample.get("geometry")
        if geometry and isinstance(geometry, str):
            # Validate against known forms
            valid_forms = {f.value for f in SampleForm}
            if geometry in valid_forms:
                return geometry
            # Fall through to default if invalid

        # Check layers to infer sample type
        layers = sample.get("layers", [])
        if layers:
            # Multiple layers suggests thin film structure
            return SampleForm.THIN_FILM.value

        return SampleForm.THIN_FILM.value  # Default for reflectometry

    def _build_composition(
        self, sample: dict[str, Any], context: MapperContext
    ) -> Optional[dict[str, Any]]:
        """
        Build composition from layer information.

        Extracts material fractions from the layer stack.
        """
        layers = sample.get("layers", [])
        if not layers:
            return None

        composition: dict[str, Any] = {}

        # Count materials and their total thickness
        material_thickness: dict[str, float] = {}
        total_thickness = 0.0

        for layer in layers:
            material = layer.get("material", "unknown")
            thickness = layer.get("thickness", 0)

            # Skip ambient layers (zero thickness at top)
            if thickness == 0:
                continue

            total_thickness += thickness
            material_thickness[material] = material_thickness.get(material, 0) + thickness

        # Calculate fractions
        if total_thickness > 0:
            for material, thickness in material_thickness.items():
                key = f"{material}_thickness_fraction"
                composition[key] = round(thickness / total_thickness, 4)

        # Store total thickness in context for geometry
        if total_thickness > 0:
            context.metadata["total_thickness_A"] = total_thickness

        return composition if composition else None

    def _build_geometry(
        self, sample: dict[str, Any], context: MapperContext
    ) -> Optional[dict[str, Any]]:
        """
        Build geometry information from layer stack.
        """
        geometry: dict[str, Any] = {}

        # Get total thickness from context (calculated in composition)
        total_thickness = context.metadata.get("total_thickness_A")
        if total_thickness:
            geometry["total_thickness_angstrom"] = total_thickness

        # Count layers (excluding ambient/substrate with zero thickness)
        layers = sample.get("layers", [])
        film_layers = [l for l in layers if l.get("thickness", 0) > 0]
        if film_layers:
            geometry["layer_count"] = len(film_layers)

        return geometry if geometry else None

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """Validate sample block has required fields."""
        if "sample_form" not in block:
            context.add_error("sample.sample_form is required")
            return False

        return True
