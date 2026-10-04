"""
JUSLIB — Base connector abstract class.

Tout connecteur de source officielle hérite de BaseConnector.
Invariants imposés à chaque connecteur :
  1. source_url obligatoire dans chaque ConnectorResult
  2. source_hash (SHA-256) calculé systématiquement
  3. Pas de donnée retournée sans vérification HTTP 200
  4. Chaque appel loggé (mode DEBUG)
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("juslib.connector")
logger.setLevel(logging.DEBUG)


@dataclass
class ConnectorResult:
    """
    Résultat standardisé d'un connecteur JUSLIB.
    Toujours produit par BaseConnector.fetch().
    """
    success: bool = False
    source_url: str = ""
    source_hash: Optional[str] = None       # SHA-256 du contenu brut
    raw_content: Optional[bytes] = None
    parsed_data: Optional[dict] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    connector_id: str = ""
    connector_version: str = "0.1.0"

    def compute_hash(self) -> Optional[str]:
        """Calcule le SHA-256 du contenu brut si disponible."""
        if self.raw_content:
            h = hashlib.sha256(self.raw_content).hexdigest()
            self.source_hash = h
            return h
        return None

    def to_provenance_dict(self) -> dict:
        """Produit un dict compatible Provenance pour enregistrement."""
        return {
            "source_url": self.source_url,
            "source_hash": self.source_hash or "",
            "connector_id": self.connector_id,
            "connector_version": self.connector_version,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


class BaseConnector(ABC):
    """
    Classe de base abstraite pour tous les connecteurs de sources officielles.

    Chaque connecteur concret implémente :
      - fetch(identifier) → ConnectorResult
      - search(query, **kwargs) → list[ConnectorResult]
      - get_metadata(identifier) → dict
    """

    CONNECTOR_ID: str = "base"
    CONNECTOR_VERSION: str = "0.1.0"
    SOURCE_NAME: str = "Unknown Source"
    SOURCE_JURISDICTION: str = "XX"
    BASE_URL: str = ""

    def __init__(self, api_key: Optional[str] = None, debug: bool = True):
        self.api_key = api_key
        self.debug = debug
        self._log = logging.getLogger(f"juslib.connector.{self.CONNECTOR_ID}")
        self._log.setLevel(logging.DEBUG if debug else logging.INFO)
        self._log.debug(
            "[INIT] Connector %s v%s | source=%s | jurisdiction=%s",
            self.CONNECTOR_ID, self.CONNECTOR_VERSION,
            self.SOURCE_NAME, self.SOURCE_JURISDICTION,
        )

    @abstractmethod
    def fetch(self, identifier: str, language: str = "fr") -> ConnectorResult:
        """
        Récupère un document par son identifiant officiel.
        Toujours retourne un ConnectorResult (jamais None).
        """

    @abstractmethod
    def search(self, query: str, language: str = "fr", max_results: int = 20) -> list[ConnectorResult]:
        """
        Recherche dans la source officielle.
        Retourne une liste de ConnectorResult (peut être vide).
        """

    @abstractmethod
    def get_metadata(self, identifier: str) -> dict[str, Any]:
        """
        Récupère les métadonnées d'un document sans le texte complet.
        Utile pour la vérification de disponibilité.
        """

    def _make_result(
        self,
        success: bool,
        source_url: str,
        raw_content: Optional[bytes] = None,
        parsed_data: Optional[dict] = None,
        error_message: Optional[str] = None,
        http_status: Optional[int] = None,
    ) -> ConnectorResult:
        """Helper : construit un ConnectorResult standardisé."""
        result = ConnectorResult(
            success=success,
            source_url=source_url,
            raw_content=raw_content,
            parsed_data=parsed_data,
            error_message=error_message,
            http_status=http_status,
            connector_id=self.CONNECTOR_ID,
            connector_version=self.CONNECTOR_VERSION,
        )
        if raw_content:
            result.compute_hash()
        if self.debug:
            self._log.debug(
                "[RESULT] url=%s | success=%s | status=%s | hash=%s",
                source_url, success, http_status,
                result.source_hash[:16] + "…" if result.source_hash else "None",
            )
        return result
