"""
JUSLIB — Legal relations model.

Les relations forment le graphe juridique de JUSLIB :
  - une loi AMENDS une autre loi
  - une directive REQUIRES_TRANSPOSITION
  - un arrêt INTERPRETS un article
  - une disposition CONTRADICTS une autre
  - etc.

Invariant : source_id et target_id jamais nuls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RelationType(str, Enum):
    """Catalogue des types de relations juridiques."""
    # Relations normatives
    AMENDS = "amends"                          # Modifie (partiellement)
    REPEALS = "repeals"                        # Abroge totalement
    SUPERSEDES = "supersedes"                  # Remplace
    IMPLEMENTS = "implements"                  # Transpose / met en œuvre
    REQUIRES_TRANSPOSITION = "requires_transposition"
    CODIFIES = "codifies"                      # Codifie dans un code

    # Relations interprétatives (jurisprudence ↔ texte)
    INTERPRETS = "interprets"                  # Interprète une disposition
    APPLIES = "applies"                        # Applique un texte à un cas
    EXTENDS_SCOPE = "extends_scope"            # Élargit la portée d'un texte
    RESTRICTS_SCOPE = "restricts_scope"        # Restreint la portée
    INVALIDATES = "invalidates"                # Invalide (inconstitutionnalité, non-conformité)

    # Relations jurisprudentielles
    CONFIRMS = "confirms"                      # Confirme une décision antérieure
    OVERRULES = "overrules"                    # Renverse (revirement)
    DISTINGUISHES = "distinguishes"            # Distingue (écarte la précédente)
    FOLLOWS = "follows"                        # Suit / applique la précédente
    QUESTIONS = "questions"                    # Renvoie une question préjudicielle

    # Relations logiques
    CONTRADICTS = "contradicts"               # Contredit (à vérifier)
    COMPLEMENTS = "complements"               # Complète / précise
    REFERS_TO = "refers_to"                    # Renvoie à (citation simple)
    DEROGATES = "derogates"                    # Déroge à (lex specialis)

    # Relations hiérarchiques (hiérarchie des normes)
    SUPERIOR_TO = "superior_to"               # Hiérarchiquement supérieur à
    SUBORDINATE_TO = "subordinate_to"         # Hiérarchiquement inférieur à


@dataclass
class LegalRelation:
    """
    Relation orientée entre deux entités juridiques dans le graphe JUSLIB.

    source → [relation_type] → target

    Exemples :
      RGPD_ART17 --INTERPRETS--> CJUE_C-131/12 (Google Spain)
      DIR_95_46_CE --SUPERSEDES--> RGPD
      LOI_2018-493 --IMPLEMENTS--> DIR_2016_680
    """

    relation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # --- Entités liées (OBLIGATOIRES — jamais nuls) ---
    source_id: str = ""                        # juslib_id de l'entité source
    source_type: str = ""                      # "document" | "disposition" | "jurisprudence"
    target_id: str = ""                        # juslib_id de l'entité cible
    target_type: str = ""                      # "document" | "disposition" | "jurisprudence"

    # --- Type de relation ---
    relation_type: RelationType = RelationType.REFERS_TO

    # --- Contexte ---
    description: Optional[str] = None          # Description libre de la relation
    legal_basis: Optional[str] = None          # Fondement juridique de la relation
    confidence: float = 1.0                    # 0.0→1.0 (1.0 = relation officielle établie)
    is_contested: bool = False                 # La relation est-elle contestée ?

    # --- Validité temporelle ---
    valid_from: Optional[str] = None           # ISO date
    valid_until: Optional[str] = None          # ISO date (None = toujours valide)

    # --- Audit ---
    created_at: datetime = field(default_factory=datetime.utcnow)
    corpus_version: Optional[str] = None

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.source_id:
            errors.append("INVARIANT: source_id obligatoire")
        if not self.target_id:
            errors.append("INVARIANT: target_id obligatoire")
        if self.source_id == self.target_id:
            errors.append("source_id == target_id — relation réflexive interdite")
        if not 0.0 <= self.confidence <= 1.0:
            errors.append("confidence doit être dans [0.0, 1.0]")
        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        return {
            "relation_id": self.relation_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "relation_type": self.relation_type.value,
            "description": self.description,
            "legal_basis": self.legal_basis,
            "confidence": self.confidence,
            "is_contested": self.is_contested,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "created_at": self.created_at.isoformat(),
            "corpus_version": self.corpus_version,
        }
