"""
JUSLIB — OHADA connector.

Source : OHADA — Organisation pour l'Harmonisation en Afrique du Droit des Affaires
Couverture :
  - Actes Uniformes OHADA (droit des sociétés, procédures collectives, etc.)
  - Décisions CCJA (Cour Commune de Justice et d'Arbitrage)
  - Traité de Port-Louis et Traité de Québec

Source officielle : https://www.ohada.com/
CCJA : https://www.ccja-ohada.org/
Langue officielle : français uniquement
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.error
import json
from typing import Any, Optional

from .base_connector import BaseConnector, ConnectorResult

logger = logging.getLogger("juslib.connector.ohada")

# R002-P0-07 : URL institutionnelle correcte (ohada.org, pas ohada.com)
# Source : https://www.ohada.org/actes-uniformes/
# ohada.org = site officiel de l'OHADA institutionnel (Organisation)
# ohada.com = site tiers non institutionnel
OHADA_BASE_URL = "https://www.ohada.org"
OHADA_ACTES_BASE = "https://www.ohada.org/actes-uniformes"
OHADA_JO_BASE = "https://www.ohada.org/journal-officiel"  # Journal Officiel OHADA


class OHADAConnector(BaseConnector):
    """
    Connecteur OHADA — Actes Uniformes et jurisprudence CCJA.

    ⚠️  L'API OHADA est limitée — les données sont principalement
    disponibles sous forme de pages HTML ou PDF.
    Ce connecteur implémente le scraping structuré des pages officielles.

    Langues disponibles : fr uniquement
    """

    CONNECTOR_ID = "ohada"
    CONNECTOR_VERSION = "0.1.1"  # R002-P0-07 : URL corrigée → ohada.org institutionnel
    SOURCE_NAME = "OHADA — Organisation pour l'Harmonisation en Afrique du Droit des Affaires"
    SOURCE_JURISDICTION = "OHADA"
    # R002-P0-07 : source institutionnelle (17 États membres)
    # Ref : https://www.ohada.org/presentation-generale/
    BASE_URL = OHADA_BASE_URL
    SUPPORTED_LANGUAGES = ["fr"]

    # Catalogue des Actes Uniformes OHADA avec leurs URLs officielles
    ACTES_UNIFORMES = {
        "AUDCG": ("Acte Uniforme relatif au Droit Commercial Général", "/droit-commercial-general"),
        "AUSCGIE": ("Acte Uniforme relatif aux Sociétés Commerciales et GIE", "/societes-commerciales"),
        "AUS": ("Acte Uniforme relatif aux Sûretés", "/suretes"),
        "AUPSRVE": ("Acte Uniforme portant sur les Procédures Simplifiées de Recouvrement", "/recouvrement"),
        "AUPC": ("Acte Uniforme portant sur les Procédures Collectives", "/procedures-collectives"),
        "AUDAS": ("Acte Uniforme relatif au Droit de l'Arbitrage", "/arbitrage"),
        "AUDE": ("Acte Uniforme relatif au Droit des Sociétés Coopératives", "/cooperatives"),
        "AUDCF": ("Acte Uniforme relatif au Droit Comptable et à l'Information Financière", "/comptabilite"),
        "AUTDC": ("Acte Uniforme relatif aux Contrats de Transport de Marchandises par Route", "/transport"),
    }

    def fetch(self, identifier: str, language: str = "fr") -> ConnectorResult:
        """
        Récupère un Acte Uniforme OHADA ou une décision CCJA.
        identifier : code de l'Acte Uniforme (ex: "AUDCG") ou ID CCJA
        """
        if language.lower() != "fr":
            self._log.info("[OHADA] Seule la langue 'fr' est disponible")

        if identifier in self.ACTES_UNIFORMES:
            title, path = self.ACTES_UNIFORMES[identifier]
            url = f"{OHADA_ACTES_BASE}{path}"
            self._log.debug("[OHADA] fetch Acte Uniforme %s : %s", identifier, title)
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "JUSLIB/0.1.0", "Accept": "text/html"},
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw = response.read()
                    return self._make_result(
                        success=True,
                        source_url=url,
                        raw_content=raw,
                        parsed_data={"ohada_code": identifier, "title": title, "language": "fr"},
                        http_status=response.status,
                    )
            except urllib.error.HTTPError as e:
                return self._make_result(success=False, source_url=url,
                                         error_message=f"HTTP {e.code}: {e.reason}", http_status=e.code)
            except Exception as e:
                return self._make_result(success=False, source_url=url, error_message=str(e))
        else:
            return self._make_result(
                success=False,
                source_url=f"{OHADA_BASE_URL}/jurisprudence/{identifier}",
                error_message=f"Identifiant OHADA non reconnu: '{identifier}'. "
                              f"Codes valides: {list(self.ACTES_UNIFORMES.keys())}",
            )

    def search(self, query: str, language: str = "fr", max_results: int = 20) -> list[ConnectorResult]:
        """
        Recherche dans le catalogue OHADA.
        Retourne les Actes Uniformes dont le titre contient le terme de recherche.
        """
        results = []
        query_lower = query.lower()
        for code, (title, path) in self.ACTES_UNIFORMES.items():
            if query_lower in title.lower() or query_lower in code.lower():
                url = f"{OHADA_ACTES_BASE}{path}"
                results.append(self._make_result(
                    success=True,
                    source_url=url,
                    raw_content=json.dumps({"code": code, "title": title}).encode("utf-8"),
                    parsed_data={"ohada_code": code, "title": title, "language": "fr"},
                    http_status=200,
                ))
        self._log.debug("[OHADA] search '%s' → %d résultats", query[:50], len(results))
        return results[:max_results]

    def get_metadata(self, identifier: str) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "ohada_code": identifier,
            "source": "ohada",
            "jurisdiction": "OHADA",
            "languages_available": self.SUPPORTED_LANGUAGES,
            "connector_version": self.CONNECTOR_VERSION,
        }
        if identifier in self.ACTES_UNIFORMES:
            title, path = self.ACTES_UNIFORMES[identifier]
            meta["title"] = title
            meta["source_url"] = f"{OHADA_ACTES_BASE}{path}"
        return meta
