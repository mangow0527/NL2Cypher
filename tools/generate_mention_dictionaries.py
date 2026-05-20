from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.offline.asset_generation.generate_mention_dictionaries import (
    generate_dictionaries,
    main,
)

__all__ = ["generate_dictionaries", "main"]


if __name__ == "__main__":
    main()
