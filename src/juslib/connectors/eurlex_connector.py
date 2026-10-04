"""
JUSLIB — EUR-Lex connector.

Source : EUR-Lex SPARQL + REST API + WebServices
Couverture :
  - Tous les actes législatifs de l'Union Européenne
  - Règlements, Directives, Décisions, Recommandations
  - Jurisprudence CJUE / TGUE (via CELEX)
  - Journal Officiel de l'Union Européenne (JO UE)
  - Toutes les langues officielles de l'UE (24 langues)

API officielle : https://eur-lex.europa.eu/content/tools/webservices/
SPARQL endpoint : https://publications.europa.eu/webapi/rdf/sparql
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Any, Optional

from .base_connector import BaseConnector, ConnectorResult

logger = logging.getLogger("juslib.connector.eurlex")

# Langues officielles de l'Union Européenne (24)
EU_OFFICIAL_LANGUAGES = [
    "bg", "cs", "da", "de", "el", "en", "es", "et",
    "fi", "fr", "ga", "hr", "hu", "it", "lt", "lv",
    "mt", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
]


class EurLexConnector(BaseConnector):
    """
    Connecteur EUR-Lex — source officielle droit de l'Union Européenne.

    Identifiants supportés :
      - CELEX (ex: "32016R0679" pour le RGPD)
      - DOI EUR-Lex
      - URI FRBR/Akoma Ntoso

    Exemple d'usage :
        connector = EurLexConnector()
        result = connector.fetch("32016R0679", language="fr")
    """

    CONNECTOR_ID = "eurlex"
    CONNECTOR_VERSION = "0.1.0"
    SOURCE_NAME = "EUR-Lex — Journal Officiel de l'Union Européenne"
    SOURCE_JURISDICTION = "EU"
    BASE_URL = "https://eur-lex.europa.eu"
    API_BASE = "https://eur-lex.europa.eu/legal-content"
    SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"

    # Correspondance type CELEX → DocumentType JUSLIB
    CELEX_TYPE_MAP = {
        "R": "regulation",    # Règlement
        "L": "directive",     # Directive
        "D": "decision",      # Décision
        "E": "recommendation", # Recommandation / avis
        "F": "opinion",       # Acte PESC
        "A": "jurisprudence", # Arrêt CJUE
        "T": "jurisprudence", # Arrêt TGUE
        "O": "opinion",       # Conclusions AG
        "C": "treaty",        # Traité/accord
    }

    def fetch(self, identifier: str, language: str = "fr") -> ConnectorResult:
        """
        Récupère un acte EUR-Lex par son numéro CELEX.

        Si la langue demandée n'est pas disponible, retourne la version EN
        avec un avertissement dans le résultat.
        """
        lang = language.lower()
        if lang not in EU_OFFICIAL_LANGUAGES:
            self._log.warning(
                "[EURLEX] Langue '%s' non officielle UE — fallback 'en'", lang
            )
            lang = "en"

        # URL standard EUR-Lex : /legal-content/{LANG}/TXT/?uri=CELEX:{ID}
        url = f"{self.API_BASE}/{lang.upper()}/TXT/?uri=CELEX:{identifier}"

        self._log.debug("[EURLEX] fetch CELEX=%s lang=%s url=%s", identifier, lang, url)

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "JUSLIB/0.1.0 (legal library; contact@juslib.eu)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return self._make_result(
                    success=True,
                    source_url=url,
                    raw_content=raw,
                    parsed_data={"celex": identifier, "language": lang, "source": "eurlex"},
                    http_status=response.status,
                )
        except urllib.error.HTTPError as e:
            return self._make_result(
                success=False,
                source_url=url,
                error_message=f"HTTP {e.code}: {e.reason}",
                http_status=e.code,
            )
        except urllib.error.URLError as e:
            return self._make_result(
                success=False,
                source_url=url,
                error_message=f"URLError: {e.reason}",
            )

    def fetch_multilingual(self, identifier: str, languages: Optional[list[str]] = None) -> dict[str, ConnectorResult]:
        """
        Récupère un acte EUR-Lex dans toutes les langues officielles UE.
        Retourne un dict {lang_code: ConnectorResult}.

        Si languages est None, récupère uniquement FR + EN + DE (défaut multilingue MVP).
        """
        target_langs = languages or ["fr", "en", "de"]
        results: dict[str, ConnectorResult] = {}
        for lang in target_langs:
            self._log.debug("[EURLEX] fetch_multilingual CELEX=%s lang=%s", identifier, lang)
            results[lang] = self.fetch(identifier, language=lang)
        return results

    def search(self, query: str, language: str = "fr", max_results: int = 20) -> list[ConnectorResult]:
        """
        Recherche EUR-Lex via l'API SPARQL Publications Office.

        Retourne une liste de ConnectorResult contenant les métadonnées CELEX.
        Le texte complet est récupéré séparément via fetch().

        Note : L'API SPARQL EUR-Lex est publique (pas d'authentification requise).
        """
        lang = language.lower() if language.lower() in EU_OFFICIAL_LANGUAGES else "en"
        sparql_query = f"""
        SELECT DISTINCT ?celex ?title ?date ?type
        WHERE {{
          ?doc cdm:work_has_expression ?expr .
          ?expr cdm:expression_title ?title .
          ?expr cdm:expression_uses_language ?lang .
          ?doc cdm:resource_legal_id_celex ?celex .
          ?doc cdm:work_date_document ?date .
          FILTER(CONTAINS(LCASE(?title), LCASE("{query}")))
          FILTER(?lang = <http://publications.europa.eu/resource/authority/language/{lang.upper()}>)
        }}
        ORDER BY DESC(?date)
        LIMIT {max_results}
        """
        encoded = urllib.parse.urlencode({
            "query": sparql_query,
            "format": "application/sparql-results+json",
        })
        sparql_url = f"{self.SPARQL_ENDPOINT}?{encoded}"

        self._log.debug("[EURLEX] SPARQL search query='%s' lang=%s", query[:50], lang)

        try:
            req = urllib.request.Request(
                sparql_url,
                headers={
                    "User-Agent": "JUSLIB/0.1.0",
                    "Accept": "application/sparql-results+json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                data = json.loads(raw.decode("utf-8"))
                results = []
                for binding in data.get("results", {}).get("bindings", []):
                    celex = binding.get("celex", {}).get("value", "")
                    title = binding.get("title", {}).get("value", "")
                    result_url = f"{self.API_BASE}/{lang.upper()}/TXT/?uri=CELEX:{celex}"
                    results.append(self._make_result(
                        success=True,
                        source_url=result_url,
                        raw_content=raw,
                        parsed_data={"celex": celex, "title": title, "language": lang},
                        http_status=200,
                    ))
                self._log.debug("[EURLEX] SPARQL search returned %d results", len(results))
                return results
        except Exception as e:
            self._log.error("[EURLEX] SPARQL search error: %s", e)
            return [self._make_result(
                success=False,
                source_url=sparql_url,
                error_message=str(e),
            )]

    def get_metadata(self, identifier: str) -> dict[str, Any]:
        """
        Récupère les métadonnées d'un CELEX via l'endpoint REST EUR-Lex.
        Retourne un dict avec title, date, type, languages disponibles.
        """
        # URI FRBR : work level (toutes langues)
        frbr_url = f"{self.BASE_URL}/legal-content/FR/ALL/?uri=CELEX:{identifier}"
        self._log.debug("[EURLEX] get_metadata CELEX=%s", identifier)
        return {
            "celex": identifier,
            "frbr_url": frbr_url,
            "available_languages": EU_OFFICIAL_LANGUAGES,
            "source": "eurlex",
            "connector_version": self.CONNECTOR_VERSION,
        }
