"""
JUSLIB — CanLII connector (Canada / Québec).

CLASSIFICATION R002-P0-06 : SOURCE SECONDAIRE (agrégateur juridique de haute qualité).
CanLII n'est PAS une source normative officielle.
CanLII indique que ses copies ne sont pas nécessairement dotées d'une valeur officielle.
Ref : https://www.canlii.org/databases + https://www.canlii.org/info/terms.html

Sources officielles canadiennes :
  Lois du Canada      : https://laws-lois.justice.gc.ca/
  LégisQuébec (QC)    : https://www.legisquebec.gouv.qc.ca/

Les documents récupérés via CanLII sont marqués source_classification=SECONDARY_AGGREGATOR.
Ne jamais présenter un document CanLII comme source normative officielle.

API officielle : https://api.canlii.org/
Documentation : https://law.canlii.org/
Clé API requise : https://developer.canlii.org/
Configurer dans .env : CANLII_API_KEY
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Any, Optional

from .base_connector import BaseConnector, ConnectorResult

logger = logging.getLogger("juslib.connector.canlii")

CANLII_API_BASE = "https://api.canlii.org/v1"


class CanLIIConnector(BaseConnector):
    """
    Connecteur CanLII — Institut canadien d'information juridique.

    Supporte les juridictions CA (fédéral), QC, ON, BC, etc.

    Exemple :
        connector = CanLIIConnector(api_key=os.getenv("CANLII_API_KEY"))
        result = connector.fetch("qcca/2023canlii12345", language="fr")
    """

    CONNECTOR_ID = "canlii"
    CONNECTOR_VERSION = "0.1.1"  # R002-P0-06
    SOURCE_NAME = "CanLII — Institut canadien d'information juridique"
    SOURCE_JURISDICTION = "CA"
    # R002-P0-06 : CanLII = SOURCE SECONDAIRE (agrégateur) — pas source normative officielle
    SOURCE_CLASSIFICATION = "SECONDARY_AGGREGATOR"
    BASE_URL = "https://www.canlii.org"

    SUPPORTED_LANGUAGES = ["fr", "en"]

    def fetch(self, identifier: str, language: str = "fr") -> ConnectorResult:
        """
        Récupère un document CanLII.
        identifier : ex "qcca/2023canlii12345" (database_id/case_id)
        """
        lang = language.lower() if language.lower() in self.SUPPORTED_LANGUAGES else "en"
        parts = identifier.split("/")
        if len(parts) < 2:
            return self._make_result(
                success=False,
                source_url=f"{CANLII_API_BASE}/caseBrowse/{lang}/{identifier}/",
                error_message=f"Format identifiant invalide: '{identifier}' — attendu: 'databaseId/caseId'",
            )
        db_id, case_id = parts[0], "/".join(parts[1:])
        url = f"{CANLII_API_BASE}/caseBrowse/{lang}/{db_id}/{case_id}/"
        if self.api_key:
            url += f"?api_key={self.api_key}"
        public_url = f"{self.BASE_URL}/{lang}/{db_id}/{case_id}"

        self._log.debug("[CANLII] fetch db=%s case=%s lang=%s", db_id, case_id, lang)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "JUSLIB/0.1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                parsed = json.loads(raw.decode("utf-8"))
                return self._make_result(
                    success=True,
                    source_url=public_url,
                    raw_content=raw,
                    parsed_data=parsed,
                    http_status=response.status,
                )
        except urllib.error.HTTPError as e:
            return self._make_result(success=False, source_url=url,
                                     error_message=f"HTTP {e.code}: {e.reason}", http_status=e.code)
        except Exception as e:
            return self._make_result(success=False, source_url=url, error_message=str(e))

    def search(self, query: str, language: str = "fr", max_results: int = 20) -> list[ConnectorResult]:
        """Recherche dans CanLII — supporte FR et EN."""
        lang = language.lower() if language.lower() in self.SUPPORTED_LANGUAGES else "en"
        params = {"fullText": query, "resultCount": max_results}
        if self.api_key:
            params["api_key"] = self.api_key
        encoded = urllib.parse.urlencode(params)
        url = f"{CANLII_API_BASE}/caseBrowse/{lang}/search?{encoded}"

        self._log.debug("[CANLII] search query='%s' lang=%s", query[:50], lang)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JUSLIB/0.1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                data = json.loads(raw.decode("utf-8"))
                results = []
                for case in data.get("cases", []):
                    case_url = f"{self.BASE_URL}/{lang}/{case.get('databaseId', '')}/{case.get('caseId', '')}"
                    results.append(self._make_result(
                        success=True,
                        source_url=case_url,
                        raw_content=json.dumps(case).encode("utf-8"),
                        parsed_data=case,
                        http_status=200,
                    ))
                return results
        except Exception as e:
            self._log.error("[CANLII] search error: %s", e)
            return [self._make_result(success=False, source_url=url, error_message=str(e))]

    def get_metadata(self, identifier: str) -> dict[str, Any]:
        return {
            "canlii_id": identifier,
            "source": "canlii",
            "jurisdiction": "CA",
            "languages_available": self.SUPPORTED_LANGUAGES,
            "connector_version": self.CONNECTOR_VERSION,
        }
