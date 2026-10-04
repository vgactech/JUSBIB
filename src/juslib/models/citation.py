"""
JUSLIB — Citation model.

Toute référence à un document JUSLIB depuis un texte (doctrine, décision, vulgarisation)
doit passer par ce modèle pour garantir la traçabilité.

Styles de citation supportés :
  - OSCOLA (UK/UE — European Legal Citation)
  - Dalloz (FR)
  - JORF (Journal Officiel)
  - APA légal
  - Akoma Ntoso / FRBRuri
  - Style libre (avec avertissement)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class CitationStyle(str, Enum):
    """Format de citation normalisé."""
    OSCOLA = "oscola"          # Oxford Standard for Citation of Legal Authorities
    DALLOZ = "dalloz"          # Style Dalloz (France)
    JORF = "jorf"              # Journal Officiel de la République Française
    EURLEX = "eurlex"          # Style EUR-Lex officiel
    ECLI = "ecli"              # European Case Law Identifier
    APA_LEGAL = "apa_legal"    # APA adapté au droit
    BLUEBOOK = "bluebook"      # The Bluebook (USA / international)
    FRBR = "frbr"              # FRBRuri (Akoma Ntoso)
    FREE = "free"              # Libre — avertissement de non-standard


@dataclass
class Citation:
    """
    Référence normalisée vers une entité juridique JUSLIB.

    Invariant : target_juslib_id jamais nul — toute citation doit pointer
    vers un document existant dans le corpus.
    """

    citation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # --- Cible (OBLIGATOIRE) ---
    target_juslib_id: str = ""              # FK → LegalDocument / JurisprudenceItem
    target_type: str = ""                   # "document" | "disposition" | "jurisprudence"

    # --- Format ---
    style: CitationStyle = CitationStyle.OSCOLA
    formatted_citation: str = ""            # Texte formaté selon le style choisi
    is_standard_compliant: bool = True      # False si style FREE ou non vérifié

    # --- Contexte de la citation ---
    cited_in_id: Optional[str] = None       # FK → entité qui cite (document, décision, explication)
    cited_in_type: Optional[str] = None     # "document" | "jurisprudence" | "explanation"
    pinpoint: Optional[str] = None          # Ex: "art. 17, §2" ou "§42"
    page: Optional[str] = None             # Numéro de page (si applicable)

    # --- Audit ---
    created_at: datetime = field(default_factory=datetime.utcnow)
    corpus_version: Optional[str] = None

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.target_juslib_id:
            errors.append("INVARIANT: target_juslib_id obligatoire — citation orpheline interdite")
        if not self.formatted_citation:
            errors.append("formatted_citation obligatoire")
        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        return {
            "citation_id": self.citation_id,
            "target_juslib_id": self.target_juslib_id,
            "target_type": self.target_type,
            "style": self.style.value,
            "formatted_citation": self.formatted_citation,
            "is_standard_compliant": self.is_standard_compliant,
            "cited_in_id": self.cited_in_id,
            "cited_in_type": self.cited_in_type,
            "pinpoint": self.pinpoint,
            "page": self.page,
            "created_at": self.created_at.isoformat(),
            "corpus_version": self.corpus_version,
        }
