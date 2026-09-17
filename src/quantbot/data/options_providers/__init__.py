"""Options data provider adapters.

Each provider module registers itself with the loader registry on import.
Import any adapter you need explicitly (registration is a side effect of
import; this keeps the package free of network dependencies until needed).
"""

from . import synthetic  # noqa: F401  (registers 'synthetic' loader)
from . import thetadata  # noqa: F401  (registers 'thetadata' loader; dry-run by default)
