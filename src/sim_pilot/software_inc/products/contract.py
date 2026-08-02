"""Version-pinned Prompt 7 Atlas contract for Software Inc. 1.8.41."""

from decimal import Decimal

ATLAS_NAME = "Atlas"
ATLAS_PRODUCT_TYPE = "2D Editor"
ATLAS_CATEGORY = "Default"
# Software Inc. 1.8.41 selects the non-interactable base feature "2D graphics"
# for every 2D Editor. "System" is the smallest additional unlocked feature.
ATLAS_FEATURES = ("2D graphics", "System")
ATLAS_TEAM = "Core"
ATLAS_DEFAULT_RESERVE = Decimal("50000")

__all__ = [
    "ATLAS_CATEGORY",
    "ATLAS_DEFAULT_RESERVE",
    "ATLAS_FEATURES",
    "ATLAS_NAME",
    "ATLAS_PRODUCT_TYPE",
    "ATLAS_TEAM",
]
