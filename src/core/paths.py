"""
Project path detection and management.
No configuration files needed - paths are discovered from this file's location.
"""
import os
from pathlib import Path


def get_project_root() -> Path:
    """
    Detect the project root directory.

    Resolution order:
      1. $AISQL_PROJECT_ROOT if set.
      2. Inferred from this file's location: paths.py lives at
         <root>/src/core/paths.py, so the root is two levels up from src/.

    This does not require optional directories (e.g. `resources/`, which is
    fetched separately) to exist, so imports never fail on a fresh clone.

    Returns:
        Path: The project root directory
    """
    env_root = os.getenv("AISQL_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parents[2]


# Auto-detect project root on module import
PROJECT_ROOT = get_project_root()

# Define all standard paths
DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"

RESOURCES_DIR = PROJECT_ROOT / "resources"
DATABASES_DIR = RESOURCES_DIR / "databases"
KNOWLEDGE_DIR = RESOURCES_DIR / "knowledge"

OUTPUTS_DIR = PROJECT_ROOT / "outputs"


# Convenience function for getting data files
def get_spider2_data_file() -> Path:
    """Get the path to the main Spider2 data file."""
    return DATA_RAW_DIR / "spider2-snow-gold-full.jsonl"


def get_gold_tables_file() -> Path:
    """Get the path to the gold tables mapping file."""
    return DATA_RAW_DIR / "spider2-snow-gold-tables.jsonl"


if __name__ == "__main__":
    # Test path detection
    print("🔍 Project Path Detection")
    print("=" * 60)
    print(f"PROJECT_ROOT:    {PROJECT_ROOT}")
    print(f"DATA_DIR:        {DATA_DIR}")
    print(f"RESOURCES_DIR:   {RESOURCES_DIR}")
    print(f"DATABASES_DIR:   {DATABASES_DIR}")
    print(f"KNOWLEDGE_DIR:   {KNOWLEDGE_DIR}")
    print(f"OUTPUTS_DIR:     {OUTPUTS_DIR}")
    print()
    print("✅ All paths detected successfully!")

