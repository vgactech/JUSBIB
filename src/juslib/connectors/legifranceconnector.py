"""
JUSLIB — Légifrance connector.

Source : API Légifrance (PISTE — Plateforme d'Intermédiation des Services et Technologies de l'État)
Couverture :
  - Tous les textes législatifs et réglementaires français
  - Codes consolidés (Code civil, Pénal, Commerce, Travail, Administratif…)
  - Journal Officiel de la République Française (JORF)
  - Jurisprudence : Cour de cassation, Conseil d'État, Conseil constitutionnel
  - Circulaires, instructions

API officielle : https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/
Documentation : https://piste.gouv.fr/

⚠️  Légifrance API PISTE nécessite une clé API OAuth2 (client_credentials).
     Clé à configurer dans .env : LEGIFRANCE_CLIENT_ID + LEGIFRANCE_CLIENT_SECRET
     Accès gratuit : https://developer.aife.economie.gouv.fr/
"""

from __future__ import annotations

import logging
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Any, Optional

from .base_connector import BaseConnector, ConnectorResult

logger = logging.getLogger("juslib.connector.legifrance")

# Endpoint PISTE OAuth2 + API
PISTE_TOKEN_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
PISTE_API_BASE = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"

# Mapping types Légifrance → DocumentType JUSLIB
LEGIFRANCE_NATURE_MAP = {
    "LOI": "law",
    "ORDONNANCE": "ordinance",
    "DECRET": "decree",
    "ARRETE": "order",
    "CIRCULAIRE": "circular",
    "CONSTITUTION": "constitution",
    "CODE": "code",
}


class LegifranceConnector(BaseConnector):
    """
    Connecteur Légifrance (API PISTE) — source officielle droit français.

    Supporte :
      - Récupération par ID Légifrance (LEGITEXT*, JORFTEXT*, LEGIARTI*)
      - Recherche full-text dans les textes législatifs
      - Récupération des codes consolidés (dernière version en vigueur)

    Configuration requise (.env) :
      LEGIFRANCE_CLIENT_ID=...
      LEGIFRANCE_CLIENT_SECRET=...

    Exemple :
        connector = LegifranceConnector(
            client_id=os.getenv("LEGIFRANCE_CLIENT_ID"),
            client_secret=os.getenv("LEGIFRANCE_CLIENT_SECRET"),
        )
        result = connector.fetch("LEGITEXT000006070721")  # Code civil
    """

    CONNECTOR_ID = "legifrance"
    CONNECTOR_VERSION = "0.1.0"
    SOURCE_NAME = "Légifrance — Service public de la diffusion du droit"
    SOURCE_JURISDICTION = "FR"
    BASE_URL = "https://www.legifrance.gouv.fr"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        debug: bool = True,
    ):
        super().__init__(debug=debug)
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None
        if not client_id or not client_secret:
            self._log.warning(
                "[LEGIFRANCE] LEGIFRANCE_CLIENT_ID / CLIENT_SECRET non configurés — "
                "les appels API échoueront. "
                "Obtenir un accès gratuit : https://developer.aife.economie.gouv.fr/"
            )

    def _get_token(self) -> Optional[str]:
        """Authentification OAuth2 client_credentials sur PISTE."""
        if not self.client_id or not self.client_secret:
            self._log.error("[LEGIFRANCE] Clé API manquante — impossible d'obtenir un token")
            return None
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "openid",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                PISTE_TOKEN_URL,
                data=data,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                token_data = json.loads(response.read().decode("utf-8"))
                self._access_token = token_data.get("access_token")
                self._log.debug("[LEGIFRANCE] Token OAuth2 obtenu (expires_in=%s)", token_data.get("expires_in"))
                return self._access_token
        except Exception as e:
            self._log.error("[LEGIFRANCE] Erreur OAuth2: %s", e)
            return None

    def fetch(self, identifier: str, language: str = "fr") -> ConnectorResult:
        """
        Récupère un texte Légifrance par son identifiant.
        Supporte : LEGITEXT*, JORFTEXT*, LEGIARTI*, KALICONT* (conventions collectives)
        """
        # Note: seul le français est disponible sur Légifrance
        if language.lower() != "fr":
            self._log.info("[LEGIFRANCE] Seule la langue 'fr' est disponible — langue '%s' ignorée", language)

        token = self._access_token or self._get_token()
        if not token:
            url = f"{PISTE_API_BASE}/consult/getTexte"
            return self._make_result(
                success=False,
                source_url=url,
                error_message="Token OAuth2 non disponible — LEGIFRANCE_CLIENT_ID/SECRET requis",
            )

        url = f"{PISTE_API_BASE}/consult/getTexte"
        payload = json.dumps({"textId": identifier}).encode("utf-8")
        self._log.debug("[LEGIFRANCE] fetch id=%s", identifier)

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "JUSLIB/0.1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                parsed = json.loads(raw.decode("utf-8"))
                return self._make_result(
                    success=True,
                    source_url=f"{self.BASE_URL}/loda/id/{identifier}",
                    raw_content=raw,
                    parsed_data=parsed,
                    http_status=response.status,
                )
        except urllib.error.HTTPError as e:
            return self._make_result(
                success=False,
                source_url=url,
                error_message=f"HTTP {e.code}: {e.reason}",
                http_status=e.code,
            )
        except Exception as e:
            return self._make_result(success=False, source_url=url, error_message=str(e))

    def search(self, query: str, language: str = "fr", max_results: int = 20) -> list[ConnectorResult]:
        """Recherche full-text dans Légifrance via l'API PISTE."""
        token = self._access_token or self._get_token()
        if not token:
            return [self._make_result(
                success=False,
                source_url=f"{PISTE_API_BASE}/search",
                error_message="Token OAuth2 requis — configurer LEGIFRANCE_CLIENT_ID/SECRET",
            )]

        url = f"{PISTE_API_BASE}/search"
        payload = json.dumps({
            "recherche": {
                "champs": [{"typeChamp": "ALL", "criteres": [{"typeRecherche": "EGAL", "valeur": query}]}],
                "pageNumber": 1,
                "pageSize": max_results,
                "sort": "PERTINENCE",
                "typePagination": "DEFAUT",
            }
        }).encode("utf-8")

        self._log.debug("[LEGIFRANCE] search query='%s'", query[:50])
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "JUSLIB/0.1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                parsed = json.loads(raw.decode("utf-8"))
                hits = parsed.get("results", [])
                results = []
                for hit in hits:
                    text_id = hit.get("id", "")
                    result_url = f"{self.BASE_URL}/loda/id/{text_id}"
                    results.append(self._make_result(
                        success=True,
                        source_url=result_url,
                        raw_content=json.dumps(hit).encode("utf-8"),
                        parsed_data=hit,
                        http_status=200,
                    ))
                self._log.debug("[LEGIFRANCE] search returned %d results", len(results))
                return results
        except Exception as e:
            self._log.error("[LEGIFRANCE] search error: %s", e)
            return [self._make_result(success=False, source_url=url, error_message=str(e))]

    def get_metadata(self, identifier: str) -> dict[str, Any]:
        return {
            "legifrance_id": identifier,
            "source_url": f"{self.BASE_URL}/loda/id/{identifier}",
            "source": "legifrance",
            "jurisdiction": "FR",
            "languages_available": ["fr"],
            "connector_version": self.CONNECTOR_VERSION,
        }
