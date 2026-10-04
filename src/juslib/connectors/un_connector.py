"""
JUSLIB — UN connector (Nations Unies / ONU).

Source : ODS (Official Document System) + UN Treaty Collection + UNTERM
Couverture :
  - Résolutions Assemblée générale, Conseil de sécurité
  - Traités multilatéraux (MTDSG — Treaty Collection)
  - Déclarations universelles (DUDH, etc.)
  - Conventions internationales (CVIM, CNUDCI, CNUDM…)
  - Langues officielles ONU : arabe, chinois, anglais, français, russe, espagnol

ODS : https://documents.un.org/
Treaty Collection : https://treaties.un.org/
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Any, Optional

from .base_connector import BaseConnector, ConnectorResult

logger = logging.getLogger("juslib.connector.un")

UN_ODS_SEARCH = "https://documents.un.org/api/symbol"
UN_TREATY_BASE = "https://treaties.un.org/Pages/ViewDetails.aspx"

# Langues officielles ONU (ISO 639-1)
UN_OFFICIAL_LANGUAGES = ["ar", "zh", "en", "fr", "ru", "es"]


class UNConnector(BaseConnector):
    """
    Connecteur Nations Unies — documents officiels et traités.

    Identifiants supportés :
      - Symbole ONU (ex: "A/RES/217(III)" pour la DUDH)
      - MTDSG ID (ex: "IV-2" pour le Pacte international relatif aux droits civils)

    Exemple :
        connector = UNConnector()
        result = connector.fetch("A/RES/217(III)", language="fr")
    """

    CONNECTOR_ID = "un"
    CONNECTOR_VERSION = "0.1.0"
    SOURCE_NAME = "Nations Unies — Système de diffusion des documents officiels"
    SOURCE_JURISDICTION = "INT"
    BASE_URL = "https://documents.un.org"

    SUPPORTED_LANGUAGES = UN_OFFICIAL_LANGUAGES

    # Catalogue des documents fondamentaux ONU (disponibles sans API)
    FUNDAMENTAL_DOCS = {
        "A/RES/217(III)": {
            "title_fr": "Déclaration universelle des droits de l'homme",
            "title_en": "Universal Declaration of Human Rights",
            "date": "1948-12-10",
            "url_fr": "https://www.un.org/fr/about-us/universal-declaration-of-human-rights",
        },
        "A/RES/2200A(XXI)": {
            "title_fr": "Pacte international relatif aux droits civils et politiques",
            "title_en": "International Covenant on Civil and Political Rights",
            "date": "1966-12-16",
            "url_fr": "https://www.ohchr.org/fr/instruments-mechanisms/instruments/international-covenant-civil-and-political-rights",
        },
        "A/RES/2200A(XXI)-SOCIAL": {
            "title_fr": "Pacte international relatif aux droits économiques, sociaux et culturels",
            "title_en": "International Covenant on Economic, Social and Cultural Rights",
            "date": "1966-12-16",
            "url_fr": "https://www.ohchr.org/fr/instruments-mechanisms/instruments/international-covenant-economic-social-and-cultural-rights",
        },
    }

    def fetch(self, identifier: str, language: str = "fr") -> ConnectorResult:
        """Récupère un document ONU par son symbole."""
        lang = language.lower() if language.lower() in self.SUPPORTED_LANGUAGES else "en"

        # Vérification catalogue fondamental d'abord
        if identifier in self.FUNDAMENTAL_DOCS:
            doc = self.FUNDAMENTAL_DOCS[identifier]
            url = doc.get(f"url_{lang}", doc.get("url_en", ""))
            self._log.debug("[UN] fetch fundamental doc %s lang=%s", identifier, lang)
            if url:
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
                            parsed_data={"un_symbol": identifier, "language": lang, **doc},
                            http_status=response.status,
                        )
                except Exception as e:
                    return self._make_result(success=False, source_url=url, error_message=str(e))

        # ODS API pour les autres documents
        params = urllib.parse.urlencode({"symbol": identifier, "lang": lang})
        ods_url = f"{UN_ODS_SEARCH}?{params}"
        self._log.debug("[UN] fetch ODS symbol=%s lang=%s", identifier, lang)
        try:
            req = urllib.request.Request(
                ods_url,
                headers={"User-Agent": "JUSLIB/0.1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return self._make_result(
                    success=True,
                    source_url=ods_url,
                    raw_content=raw,
                    parsed_data={"un_symbol": identifier, "language": lang},
                    http_status=response.status,
                )
        except urllib.error.HTTPError as e:
            return self._make_result(success=False, source_url=ods_url,
                                     error_message=f"HTTP {e.code}: {e.reason}", http_status=e.code)
        except Exception as e:
            return self._make_result(success=False, source_url=ods_url, error_message=str(e))

    def search(self, query: str, language: str = "fr", max_results: int = 20) -> list[ConnectorResult]:
        """Recherche dans le catalogue ONU (documents fondamentaux d'abord)."""
        lang = language.lower() if language.lower() in self.SUPPORTED_LANGUAGES else "en"
        results = []
        query_lower = query.lower()

        title_key = f"title_{lang}" if lang in ("fr", "en") else "title_en"
        for symbol, doc in self.FUNDAMENTAL_DOCS.items():
            title = doc.get(title_key, doc.get("title_en", ""))
            if query_lower in title.lower() or query_lower in symbol.lower():
                url = doc.get(f"url_{lang}", doc.get("url_en", f"{self.BASE_URL}"))
                results.append(self._make_result(
                    success=True,
                    source_url=url,
                    raw_content=json.dumps(doc).encode("utf-8"),
                    parsed_data={"un_symbol": symbol, "title": title, "language": lang},
                    http_status=200,
                ))
        self._log.debug("[UN] search '%s' → %d résultats catalogue fondamental", query[:50], len(results))
        return results[:max_results]

    def get_metadata(self, identifier: str) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "un_symbol": identifier,
            "source": "un_ods",
            "jurisdiction": "INT",
            "languages_available": self.SUPPORTED_LANGUAGES,
            "connector_version": self.CONNECTOR_VERSION,
        }
        if identifier in self.FUNDAMENTAL_DOCS:
            meta.update(self.FUNDAMENTAL_DOCS[identifier])
        return meta
