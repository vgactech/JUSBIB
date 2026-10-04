"""
JUSLIB — ECHR / CEDH connector (HUDOC).

Source : HUDOC — Human Rights Documentation (Cour Européenne des Droits de l'Homme)
Couverture :
  - Arrêts et décisions de la CEDH (depuis 1959)
  - Affaires communiquées
  - Avis consultatifs (depuis Protocole 16)
  - Grand Chambre
  - Langues : français + anglais (langues officielles CEDH)

API officielle : https://hudoc.echr.coe.int/
HUDOC Search API : https://hudoc.echr.coe.int/app/query/
Documentation : https://echr.coe.int/
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Any, Optional

from .base_connector import BaseConnector, ConnectorResult

logger = logging.getLogger("juslib.connector.echr")

HUDOC_SEARCH_URL = "https://hudoc.echr.coe.int/app/query/results"
HUDOC_DOCUMENT_URL = "https://hudoc.echr.coe.int/app/conversion/docx/html/body"


class ECHRConnector(BaseConnector):
    """
    Connecteur HUDOC — Cour Européenne des Droits de l'Homme.

    Accès public, pas d'authentification requise pour la recherche.
    Le texte complet des arrêts est disponible via l'API de conversion HUDOC.

    Identifiants supportés :
      - Application number (ex: "73552/16")
      - Case ID HUDOC (ex: "001-209306")
      - ECLI (ex: "ECLI:CE:ECHR:2021:0325JUD007355216")

    Exemple :
        connector = ECHRConnector()
        result = connector.fetch("001-209306")  # Big Brother Watch
    """

    CONNECTOR_ID = "echr"
    CONNECTOR_VERSION = "0.1.0"
    SOURCE_NAME = "HUDOC — Cour Européenne des Droits de l'Homme"
    SOURCE_JURISDICTION = "INT"  # International — Conseil de l'Europe
    BASE_URL = "https://hudoc.echr.coe.int"

    SUPPORTED_LANGUAGES = ["fr", "en"]  # Seules langues officielles CEDH

    def fetch(self, identifier: str, language: str = "fr") -> ConnectorResult:
        """
        Récupère un arrêt CEDH par son identifiant HUDOC.

        identifier : itemid HUDOC (ex: "001-209306") ou case number
        """
        lang = "fre" if language.lower() in ("fr", "fre") else "eng"
        # URL de récupération du texte HTML depuis HUDOC
        params = urllib.parse.urlencode({
            "library": "ECHR",
            "id": identifier,
            "format": "html",
        })
        url = f"{HUDOC_DOCUMENT_URL}?{params}"
        public_url = f"{self.BASE_URL}/eng/{{{identifier}}}"

        self._log.debug("[ECHR] fetch id=%s lang=%s", identifier, lang)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "JUSLIB/0.1.0 (legal research; contact@juslib.eu)",
                    "Accept": "text/html",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return self._make_result(
                    success=True,
                    source_url=public_url,
                    raw_content=raw,
                    parsed_data={"hudoc_id": identifier, "language": lang, "source": "hudoc"},
                    http_status=response.status,
                )
        except urllib.error.HTTPError as e:
            return self._make_result(success=False, source_url=url,
                                     error_message=f"HTTP {e.code}: {e.reason}", http_status=e.code)
        except Exception as e:
            return self._make_result(success=False, source_url=url, error_message=str(e))

    def search(self, query: str, language: str = "fr", max_results: int = 20) -> list[ConnectorResult]:
        """
        Recherche dans HUDOC via l'API de recherche publique.

        Paramètres de recherche HUDOC :
          - fulltext : recherche dans le texte
          - respondent : pays défendeur (ex: "FRA", "DEU", "GBR")
          - article : article de la Convention (ex: "8", "10")
        """
        lang_filter = "fre" if language.lower() in ("fr", "fre") else "eng"
        params = urllib.parse.urlencode({
            "query": (
                f'contentsitename:ECHR AND fulltext:"{query}" AND '
                f'(NOT (doctype:COMMUNICATEDCASES)) AND '
                f'languageisocode:"{lang_filter}"'
            ),
            "select": "itemid,applicability,appno,docname,doctype,importance,originatingbody,typedescription,doctypebranch,respondent,languageisocode,judgementdate",
            "sort": "kpimportance Ascending",
            "start": "0",
            "length": str(max_results),
        })
        search_url = f"{HUDOC_SEARCH_URL}?{params}"

        self._log.debug("[ECHR] search query='%s' lang=%s", query[:50], lang_filter)
        try:
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "JUSLIB/0.1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                data = json.loads(raw.decode("utf-8"))
                results = []
                for item in data.get("results", []):
                    columns = item.get("columns", {})
                    item_id = columns.get("itemid", "")
                    case_name = columns.get("docname", "")
                    result_url = f"{self.BASE_URL}/eng/{{{item_id}}}"
                    results.append(self._make_result(
                        success=True,
                        source_url=result_url,
                        raw_content=json.dumps(columns).encode("utf-8"),
                        parsed_data={"hudoc_id": item_id, "case_name": case_name, "language": lang_filter},
                        http_status=200,
                    ))
                self._log.debug("[ECHR] search returned %d results", len(results))
                return results
        except Exception as e:
            self._log.error("[ECHR] search error: %s", e)
            return [self._make_result(success=False, source_url=search_url, error_message=str(e))]

    def get_metadata(self, identifier: str) -> dict[str, Any]:
        return {
            "hudoc_id": identifier,
            "source_url": f"{self.BASE_URL}/eng/{{{identifier}}}",
            "source": "hudoc",
            "jurisdiction": "INT",
            "languages_available": self.SUPPORTED_LANGUAGES,
            "connector_version": self.CONNECTOR_VERSION,
        }
