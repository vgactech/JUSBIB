"""
JUSLIB — Provenance model.

Enregistre la chaîne complète de traçabilité d'un document JUSLIB :
  source officielle → récupération → indexation → version corpus

Invariants :
  - Toute entrée de provenance est immuable (INSERT-only)
  - source_hash (SHA-256) obligatoire
  - connector_id identifie quel connecteur a récupéré la donnée
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Provenance:
    """
    Enregistrement de provenance pour une entité JUSLIB.

    Chaque fois qu'un document est récupéré depuis une source officielle,
    une entrée Provenance est créée et JAMAIS modifiée.
    """

    provenance_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # --- Entité liée ---
    entity_id: str = ""              # FK → LegalDocument.juslib_id ou JurisprudenceItem.juslib_id
    entity_type: str = ""            # "document" | "disposition" | "jurisprudence"

    # --- Source officielle ---
    source_url: str = ""             # URL complète de la source (OBLIGATOIRE)
    source_name: str = ""            # Nom de la source (ex: "EUR-Lex", "Légifrance", "HUDOC")
    source_jurisdiction: str = ""   # Juridiction de la source (ISO ou "EU" / "INT")

    # --- Intégrité ---
    source_hash: str = ""           # SHA-256 du contenu récupéré (OBLIGATOIRE)
    hash_algorithm: str = "sha256"  # Algorithme utilisé

    # --- Connecteur ---
    connector_id: str = ""          # Identifiant du connecteur JUSLIB utilisé
    connector_version: str = ""     # Version du connecteur

    # --- Temporalité ---
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    source_last_modified: Optional[datetime] = None  # Dernière modification côté source

    # --- Droits ---
    license: Optional[str] = None               # Ex: "Open Data Licence v2", "CC-BY 4.0"
    license_url: Optional[str] = None
    terms_of_use: Optional[str] = None
    attribution_required: bool = False
    attribution_text: Optional[str] = None

    # --- Corpus ---
    corpus_version: Optional[str] = None

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.entity_id:
            errors.append("entity_id obligatoire")
        if not self.source_url:
            errors.append("INVARIANT_1: source_url obligatoire")
        if not self.source_hash:
            errors.append("INVARIANT_1: source_hash (SHA-256) obligatoire")
        if not self.connector_id:
            errors.append("connector_id obligatoire")
        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        return {
            "provenance_id": self.provenance_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "source_jurisdiction": self.source_jurisdiction,
            "source_hash": f"{self.hash_algorithm}:{self.source_hash}",
            "hash_algorithm": self.hash_algorithm,
            "connector_id": self.connector_id,
            "connector_version": self.connector_version,
            "retrieved_at": self.retrieved_at.isoformat(),
            "source_last_modified": self.source_last_modified.isoformat() if self.source_last_modified else None,
            "license": self.license,
            "license_url": self.license_url,
            "attribution_required": self.attribution_required,
            "attribution_text": self.attribution_text,
            "corpus_version": self.corpus_version,
        }
