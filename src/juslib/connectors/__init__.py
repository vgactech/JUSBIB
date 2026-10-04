"""JUSLIB — Official source connectors package."""
from .base_connector import BaseConnector, ConnectorResult
from .legifranceconnector import LegifranceConnector
from .eurlex_connector import EurLexConnector
from .echr_connector import ECHRConnector
from .canlii_connector import CanLIIConnector
from .ohada_connector import OHADAConnector
from .un_connector import UNConnector

__all__ = [
    "BaseConnector", "ConnectorResult",
    "LegifranceConnector",
    "EurLexConnector",
    "ECHRConnector",
    "CanLIIConnector",
    "OHADAConnector",
    "UNConnector",
]
