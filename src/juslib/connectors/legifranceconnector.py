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
     LEGIFRANCE_PISTE_ENV=sandbox|production (défaut : sandbox pour tests)
     Accès gratuit : https://developer.aife.economie.gouv.fr/

R003-P0-A : Correction URL OAuth (R002 était encore incorrecte).
  Source vérifiée : https://developer.aife.economie.gouv.fr/ + doc PISTE officielle.
  Sandbox    → https://sandbox-oauth.piste.gouv.fr/api/oauth/token
  Production → https://oauth.piste.gouv.fr/api/oauth/token
  API base sandbox    → https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app
  API base production → https://api.piste.gouv.fr/dila/legifrance/lf-engine-app
  Les deux environnements utilisent des credentials séparés.
"""

from __future__ import annotations

import logging
import os
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import Any, Optional

from .base_connector import BaseConnector, ConnectorResult

logger = logging.getLogger("juslib.connector.legifrance")

# R003-P0-A : URLs corrigées sandbox / production
# Source officielle : https://developer.aife.economie.gouv.fr/ (doc PISTE)
# R002 utilisait encore oauth.sandbox-aife.economie.gouv.fr — désormais incorrect.
_PISTE_ENVS = {
    "sandbox": {
        "token_url": "https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
        "api_base": "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app",
    },
    "production": {
        "token_url": "https://oauth.piste.gouv.fr/api/oauth/token",
        "api_base": "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app",
    },
}

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
    CONNECTOR_VERSION = "0.1.2"  # R003-P0-A : URLs OAuth corrigées
    SOURCE_NAME = "Légifrance — Service public de la diffusion du droit"
    SOURCE_JURISDICTION = "FR"
    BASE_URL = "https://www.legifrance.gouv.fr"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        piste_env: Optional[str] = None,
        debug: bool = True,
    ):
        super().__init__(debug=debug)
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None

        # R002-P0-05 : sélection automatique sandbox / production
        env = (piste_env or os.getenv("LEGIFRANCE_PISTE_ENV", "sandbox")).lower()
        if env not in _PISTE_ENVS:
            self._log.warning(
                "[LEGIFRANCE] LEGIFRANCE_PISTE_ENV='%s' invalide — fallback 'sandbox'", env
            )
            env = "sandbox"
        self._piste_env = env
        self._token_url = _PISTE_ENVS[env]["token_url"]
        self._api_base = _PISTE_ENVS[env]["api_base"]
        self._log.debug("[LEGIFRANCE] env=%s token_url=%s", env, self._token_url)

        if not client_id or not client_secret:
            self._log.warning(
                "[LEGIFRANCE] LEGIFRANCE_CLIENT_ID / CLIENT_SECRET non configurés — "
                "les appels API échoueront. "
                "Obtenir un accès gratuit : https://developer.aife.economie.gouv.fr/"
            )

    def _get_token(self) -> Optional[str]:
        """Authentification OAuth2 client_credentials sur PISTE (sandbox ou production)."""
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
                self._token_url,  # R002-P0-05 : URL dynamique sandbox/production
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
            url = f"{self._api_base}/consult/getTexte"
            return self._make_result(
                success=False,
                source_url=url,
                error_message=(
                    f"Token OAuth2 non disponible [{self._piste_env}] — "
                    "LEGIFRANCE_CLIENT_ID/SECRET requis. "
                    "Accès gratuit : https://developer.aife.economie.gouv.fr/"
                ),
            )

        url = f"{self._api_base}/consult/getTexte"
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
                source_url=f"{self._api_base}/search",
                error_message=f"Token OAuth2 requis [{self._piste_env}] — configurer LEGIFRANCE_CLIENT_ID/SECRET",
            )]

        url = f"{self._api_base}/search"
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
