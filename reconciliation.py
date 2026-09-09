import logging
from typing import Dict


logger = logging.getLogger(__name__)


class Reconciler:
    """Disabled legacy account reconciler.

    The project now runs in read-only analysis mode. Account balances, open
    orders, fills, margin, futures, and live stop checks are intentionally not
    queried from Binance.
    """

    def __init__(self, *args, **kwargs):
        logger.info("[RECON] reconciliador privado desativado em modo analysis_only")

    def reconcile(self) -> Dict[str, int]:
        return {"positions": 0, "orders": 0, "incidents": 0}
