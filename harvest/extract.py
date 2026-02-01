"""Metadata extraction from AASX files using BaSyx Python SDK."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ShellInfo:
    """Information about an Asset Administration Shell."""

    id_short: str | None
    id: str
    global_asset_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {"id": self.id}
        if self.id_short:
            result["id_short"] = self.id_short
        if self.global_asset_id:
            result["global_asset_id"] = self.global_asset_id
        return result


@dataclass
class SubmodelInfo:
    """Information about a Submodel."""

    id_short: str | None
    id: str
    semantic_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {"id": self.id}
        if self.id_short:
            result["id_short"] = self.id_short
        if self.semantic_id:
            result["semantic_id"] = self.semantic_id
        return result


@dataclass
class ExtractionResult:
    """Result of metadata extraction from an AASX file."""

    success: bool
    shells: list[ShellInfo] = field(default_factory=list)
    submodels: list[SubmodelInfo] = field(default_factory=list)
    semantic_ids: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for catalog storage."""
        if not self.success:
            return {}

        result: dict[str, Any] = {}

        if self.shells:
            result["shells"] = [s.to_dict() for s in self.shells]

        if self.submodels:
            result["submodels"] = [s.to_dict() for s in self.submodels]

        if self.semantic_ids:
            result["semantic_ids"] = self.semantic_ids

        return result


def _get_reference_value(ref: Any) -> str | None:
    """Extract the value from a Reference object.

    BaSyx uses Reference objects with keys containing the actual identifiers.
    """
    if ref is None:
        return None

    try:
        # Reference has a 'key' attribute which is a tuple of Key objects
        if hasattr(ref, "key") and ref.key:
            # Get the last key's value (usually the most specific)
            for key in ref.key:
                if hasattr(key, "value"):
                    return str(key.value)
        # Fallback: try to convert to string
        return str(ref)
    except Exception:
        return None


def _collect_semantic_ids(element: Any, semantic_ids: set[str]) -> None:
    """Recursively collect semantic IDs from a submodel element.

    Args:
        element: A submodel element (may contain nested elements)
        semantic_ids: Set to collect semantic IDs into
    """
    # Get semantic_id from this element
    if hasattr(element, "semantic_id") and element.semantic_id:
        sem_id = _get_reference_value(element.semantic_id)
        if sem_id:
            semantic_ids.add(sem_id)

    # Recurse into SubmodelElementCollections
    if hasattr(element, "value") and hasattr(element.value, "__iter__"):
        try:
            for sub_element in element.value:
                _collect_semantic_ids(sub_element, semantic_ids)
        except TypeError:
            # value is not iterable
            pass

    # Handle SubmodelElementList
    if hasattr(element, "value") and isinstance(element.value, (list, tuple)):
        for sub_element in element.value:
            if hasattr(sub_element, "semantic_id"):
                _collect_semantic_ids(sub_element, semantic_ids)


def extract_metadata(file_path: Path) -> ExtractionResult:
    """Extract metadata from an AASX file.

    Args:
        file_path: Path to the AASX file

    Returns:
        ExtractionResult with extracted metadata or error
    """
    if not file_path.exists():
        return ExtractionResult(
            success=False,
            error=f"File not found: {file_path}",
        )

    try:
        from basyx.aas.adapter.aasx import AASXReader
        from basyx.aas import model
    except ImportError as e:
        return ExtractionResult(
            success=False,
            error=f"BaSyx SDK not available: {e}",
        )

    shells: list[ShellInfo] = []
    submodels: list[SubmodelInfo] = []
    semantic_ids: set[str] = set()

    try:
        with AASXReader(str(file_path)) as reader:
            # Create an object store to hold the loaded objects
            object_store = model.DictObjectStore()

            # Create a file store for supplementary files (thumbnails, docs, etc.)
            from basyx.aas.adapter.aasx import DictSupplementaryFileContainer

            file_store = DictSupplementaryFileContainer()

            # Read the AASX content into both stores
            reader.read_into(object_store, file_store)

            # Extract shells
            for obj in object_store:
                if isinstance(obj, model.AssetAdministrationShell):
                    global_asset_id = None
                    if obj.asset_information and obj.asset_information.global_asset_id:
                        global_asset_id = str(obj.asset_information.global_asset_id)

                    shells.append(
                        ShellInfo(
                            id_short=obj.id_short,
                            id=str(obj.id),
                            global_asset_id=global_asset_id,
                        )
                    )

                elif isinstance(obj, model.Submodel):
                    # Get submodel semantic ID
                    submodel_semantic_id = _get_reference_value(obj.semantic_id)
                    if submodel_semantic_id:
                        semantic_ids.add(submodel_semantic_id)

                    submodels.append(
                        SubmodelInfo(
                            id_short=obj.id_short,
                            id=str(obj.id),
                            semantic_id=submodel_semantic_id,
                        )
                    )

                    # Collect semantic IDs from submodel elements
                    if hasattr(obj, "submodel_element"):
                        for element in obj.submodel_element:
                            _collect_semantic_ids(element, semantic_ids)

        return ExtractionResult(
            success=True,
            shells=shells,
            submodels=submodels,
            semantic_ids=sorted(semantic_ids),
        )

    except Exception as e:
        logger.warning(f"Failed to extract metadata from {file_path}: {e}")
        return ExtractionResult(
            success=False,
            error=str(e)[:500],  # Limit error message length
        )


def extract_metadata_batch(
    files: list[tuple[Path, str]],
) -> list[tuple[str, ExtractionResult]]:
    """Extract metadata from multiple AASX files.

    Args:
        files: List of (file_path, identifier) tuples

    Returns:
        List of (identifier, ExtractionResult) tuples
    """
    results = []
    for file_path, identifier in files:
        result = extract_metadata(file_path)
        results.append((identifier, result))
    return results
