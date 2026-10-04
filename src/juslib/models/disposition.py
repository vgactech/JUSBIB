"""
JUSLIB — Disposition model (article, paragraph, alinea).

Une disposition est l'unité minimale de droit positif :
  - un article de loi
  - un paragraphe d'un règlement UE
  - un alinéa d'un code
  - une clause d'un traité

Invariant : toujours reliée à son document parent (FK non nullable).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class DispositionStatus(str, Enum):
    """État juridique de la disposition à un instant t."""
    IN_FORCE = "in_force"
    REPEALED = "repealed"
    AMENDED = "amended"
    SUSPENDED = "suspended"
    NOT_YET_IN_FORCE = "not_yet_in_force"


class DispositionType(str, Enum):
    """Granularité de la disposition."""
    TITLE = "title"            # Titre (division d'un code)
    CHAPTER = "chapter"        # Chapitre
    SECTION = "section"        # Section
    SUBSECTION = "subsection"  # Sous-section
    ARTICLE = "article"        # Article (unité standard)
    PARAGRAPH = "paragraph"    # Paragraphe / point numéroté
    ALINEA = "alinea"          # Alinéa
    SUBPOINT = "subpoint"      # Sous-point / lettre
    ANNEX = "annex"            # Annexe
    PREAMBLE = "preamble"      # Préambule / considérants


@dataclass
class Disposition:
    """
    Unité minimale de droit positif dans JUSLIB.

    Identifiant : JUSLIB-DISP-{document_id}-{number}-{REV:03d}
    Exemple : JUSLIB-DISP-32016R0679-ART5-001

    Invariant fondamental : document_id jamais nul.
    """

    # --- Identité ---
    disposition_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""                         # FK → LegalDocument.juslib_id (OBLIGATOIRE)
    disposition_type: DispositionType = DispositionType.ARTICLE

    # --- Numérotation officielle ---
    number: Optional[str] = None                  # Ex: "5", "17bis", "L.111-1"
    label: Optional[str] = None                   # Ex: "Article 5", "Section 3"
    heading: Optional[str] = None                 # Intitulé/rubrique officiel

    # --- Contenu ---
    text: str = ""                                # Texte intégral de la disposition
    language: str = "fr"                          # BCP-47

    # --- État et temporalité ---
    status: DispositionStatus = DispositionStatus.IN_FORCE
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None

    # --- Hiérarchie interne ---
    parent_disposition_id: Optional[str] = None  # FK → disposition parente
    order_index: int = 0                          # Position dans le document

    # --- Versionnement (INSERT-only) ---
    revision: int = 1
    previous_revision_id: Optional[str] = None
    corpus_version: Optional[str] = None

    # --- Audit ---
    created_at: datetime = field(default_factory=datetime.utcnow)

    def validate(self) -> tuple[bool, list[str]]:
        """Valide les invariants de la disposition."""
        errors: list[str] = []
        if not self.document_id:
            errors.append("INVARIANT: document_id (FK) obligatoire — une disposition orpheline est interdite")
        if not self.text:
            errors.append("text obligatoire")
        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        return {
            "disposition_id": self.disposition_id,
            "document_id": self.document_id,
            "disposition_type": self.disposition_type.value,
            "number": self.number,
            "label": self.label,
            "heading": self.heading,
            "text": self.text,
            "language": self.language,
            "status": self.status.value,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "parent_disposition_id": self.parent_disposition_id,
            "order_index": self.order_index,
            "revision": self.revision,
            "previous_revision_id": self.previous_revision_id,
            "corpus_version": self.corpus_version,
            "created_at": self.created_at.isoformat(),
        }
