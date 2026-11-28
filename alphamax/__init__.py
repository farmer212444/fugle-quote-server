"""Independent AlphaMax research baseline. No V8 model imports or score reuse."""
from .core import (FEATURES, ContractError, TradingCosts, load_bundle,
                   fit_asof, rank_asof, walk_forward)
