"""
JUSLIB — LegalVersion model (R002-P0-02).

Hiérarchie temporelle complète :
  LegalDocument → LegalProvision → LegalVersion

LegalVersion représente le texte exact d'une disposition à une période précise.
C'est l'unité minimale versionnable du droit positif.

Invariants :
  - text_hash = SHA-256 du texte exact (raw_source_hash séparé du canonical_content_hash)
  - valid_from obligatoire
  - Toujours INSERT-only (jamais UPDATE/DELETE)
  - Une abrogation partielle crée une nouvelle LegalVersion, pas une modification

Architecture :
  LegalDocument   : le texte normatif global (ex: RGPD)
  LegalProvision  : une subdivision numérotée (ex: Article 17)
  LegalVersion    : le texte exact d'une provision à une période (ex: art. 17 RGPD au 25.05.2018)
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class VersionChangeType(str, Enum):
    """Nature de la modification ayant produit cette version."""
    INITIAL = "initial"            # Texte d'origine (entrée en vigueur)
    AMENDMENT = "amendment"        # Modification partielle (texte modificatif)
    CONSOLIDATION = "consolidation"  # Version consolidée officielle
    CORRECTION = "correction"      # Erratum / correction matérielle
    REPEAL = "repeal"              # Abrogation (texte vide / marqueur)
    PARTIAL_REPEAL = "partial_repeal"  # Abrogation partielle d'un alinéa
    SUSPENSION = "suspension"      # Suspension temporaire


@dataclass
class LegalVersion:
    """
    Texte exact d'une LegalProvision (ou d'un LegalDocument) pendant une période.

    Identifiant : JUSLIB-VER-{provision_id}-{YYYYMMDD}-{REV:03d}

    Champs de hash R002-P0-03 :
      - raw_source_hash     : SHA-256 du contenu brut récupéré depuis la source officielle
      - canonical_content_hash : SHA-256 du texte normalisé (espaces, unicode, ponctuation)

    Les deux doivent être présents et distincts pour une version certifiée.
    """

    version_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provision_id: str = ""            # FK → LegalProvision.provision_id (OBLIGATOIRE)
    document_id: str = ""             # FK → LegalDocument.juslib_id (dénormalisé pour audit)

    # --- Texte exact ---
    text: str = ""                    # Texte officiel de la provision à cette version
    language: str = "fr"              # BCP-47

    # --- Hashes R002-P0-03 (OBLIGATOIRES pour version certifiée) ---
    raw_source_hash: Optional[str] = None       # SHA-256 du contenu BRUT (avant parsing)
    canonical_content_hash: Optional[str] = None  # SHA-256 du texte normalisé

    # --- Temporalité ---
    valid_from: Optional[date] = None    # Date d'entrée en vigueur (OBLIGATOIRE)
    valid_until: Optional[date] = None   # Date de fin (None = toujours en vigueur)
    publication_date: Optional[date] = None
    adoption_date: Optional[date] = None

    # --- Nature de la modification ---
    change_type: VersionChangeType = VersionChangeType.INITIAL
    amending_document_id: Optional[str] = None  # ID du texte modificatif si AMENDMENT
    amending_provision: Optional[str] = None     # Disposition précise du texte modificatif

    # --- Provenance ---
    source_url: Optional[str] = None         # URL de la version officielle
    connector_id: Optional[str] = None       # Connecteur utilisé pour l'import

    # --- Versionnement (INSERT-only) ---
    revision: int = 1
    previous_version_id: Optional[str] = None
    corpus_version: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def compute_canonical_hash(self) -> str:
        """
        Calcule le canonical_content_hash.
        Normalisation : strip, lower, collapse whitespace, NFC unicode.
        """
        import unicodedata
        import re
        normalized = unicodedata.normalize("NFC", self.text)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        h = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        self.canonical_content_hash = h
        return h

    def verify_integrity(self) -> tuple[bool, list[str]]:
        """
        Vérifie la cohérence des hashes.
        canonical_content_hash doit correspondre au texte actuel.
        """
        errors: list[str] = []
        if not self.raw_source_hash:
            errors.append("R002-P0-03: raw_source_hash manquant")
        if not self.canonical_content_hash:
            errors.append("R002-P0-03: canonical_content_hash manquant")
        else:
            expected = self.compute_canonical_hash()
            if expected != self.canonical_content_hash:
                errors.append(
                    f"R002-P0-03: canonical_content_hash incohérent — "
                    f"stocké={self.canonical_content_hash[:12]}… "
                    f"calculé={expected[:12]}…"
                )
        return len(errors) == 0, errors

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.provision_id:
            errors.append("INVARIANT: provision_id obligatoire (FK LegalProvision)")
        if not self.text:
            errors.append("text obligatoire")
        if not self.valid_from:
            errors.append("valid_from obligatoire — sans date de début, une version est inutilisable")
        if not self.source_url:
            errors.append("INVARIANT-1: source_url obligatoire")
        ok_hash, hash_errors = self.verify_integrity()
        errors.extend(hash_errors)
        return len(errors) == 0, errors

    def is_in_force(self, on_date: Optional[date] = None) -> bool:
        """Retourne True si cette version est en vigueur à la date donnée."""
        check_date = on_date or date.today()
        if self.valid_from and check_date < self.valid_from:
            return False
        if self.valid_until and check_date >= self.valid_until:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "provision_id": self.provision_id,
            "document_id": self.document_id,
            "text": self.text,
            "language": self.language,
            "raw_source_hash": f"sha256:{self.raw_source_hash}" if self.raw_source_hash else None,
            "canonical_content_hash": f"sha256:{self.canonical_content_hash}" if self.canonical_content_hash else None,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "publication_date": self.publication_date.isoformat() if self.publication_date else None,
            "change_type": self.change_type.value,
            "amending_document_id": self.amending_document_id,
            "source_url": self.source_url,
            "connector_id": self.connector_id,
            "revision": self.revision,
            "previous_version_id": self.previous_version_id,
            "corpus_version": self.corpus_version,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class LegalProvision:
    """
    Subdivision identifiable d'un LegalDocument (article, paragraphe, titre, etc.)
    reliée à ses versions historiques (LegalVersion).

    Un LegalProvision n'a pas de texte direct — il pointe vers ses LegalVersion.
    Cela permet la reconstruction historique : « quel était l'article 17 au 1er jan 2016 ? »
    """

    provision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""             # FK → LegalDocument.juslib_id (OBLIGATOIRE)
    number: Optional[str] = None      # Ex: "17", "L.111-1"
    label: Optional[str] = None       # Ex: "Article 17"
    heading: Optional[str] = None     # Intitulé officiel
    language: str = "fr"
    order_index: int = 0

    # Liste des version_ids (FK → LegalVersion) — chronologique
    version_ids: list[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.utcnow)
    corpus_version: Optional[str] = None

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.document_id:
            errors.append("INVARIANT: document_id obligatoire (FK LegalDocument)")
        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        return {
            "provision_id": self.provision_id,
            "document_id": self.document_id,
            "number": self.number,
            "label": self.label,
            "heading": self.heading,
            "language": self.language,
            "order_index": self.order_index,
            "version_ids": self.version_ids,
            "created_at": self.created_at.isoformat(),
            "corpus_version": self.corpus_version,
        }
