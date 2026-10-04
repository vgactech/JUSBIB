"""
JUSLIB — Jurisprudence model.

Couvre :
  - CJUE (Cour de Justice de l'Union Européenne)
  - CEDH (Cour Européenne des Droits de l'Homme / HUDOC)
  - Cours nationales : Cour de cassation FR, Conseil d'État FR,
    Bundesverfassungsgericht DE, Tribunal Supremo ES, etc.
  - Tribunaux internationaux : CIJ, TPI, etc.
  - Juridictions arbitrales : CIRDI, CCI, etc.

Invariants :
  - source_url + source_hash obligatoires
  - Les décisions ne sont jamais modifiées (INSERT-only)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class CourtLevel(str, Enum):
    """Niveau hiérarchique de la juridiction."""
    INTERNATIONAL = "international"         # CIJ, CPI, TPI
    SUPRANATIONAL_EU = "supranational_eu"   # CJUE, TGUE
    HUMAN_RIGHTS = "human_rights"           # CEDH
    CONSTITUTIONAL = "constitutional"       # Cours constitutionnelles nationales
    SUPREME = "supreme"                     # Cours suprêmes nationales
    APPELLATE = "appellate"                # Cours d'appel
    FIRST_INSTANCE = "first_instance"       # Tribunaux de première instance
    ADMINISTRATIVE = "administrative"       # Juridictions administratives
    ARBITRAL = "arbitral"                   # Tribunaux arbitraux


class DecisionType(str, Enum):
    """Type de décision jurisprudentielle."""
    JUDGMENT = "judgment"                   # Arrêt / jugement
    OPINION = "opinion"                     # Avis consultatif
    ORDER = "order"                         # Ordonnance
    RULING = "ruling"                       # Décision préjudicielle (CJUE)
    DECISION_ADMISSIBILITY = "decision_admissibility"  # Décision de recevabilité (CEDH)
    GRAND_CHAMBER = "grand_chamber"         # Grande Chambre
    PLENARY = "plenary"                     # Assemblée plénière
    INTERIM_MEASURE = "interim_measure"     # Mesure conservatoire


class JurisprudenceStatus(str, Enum):
    """Statut de la décision dans la jurisprudence."""
    FINAL = "final"             # Définitive
    PENDING = "pending"         # Sous réserve / pourvoi possible
    OVERRULED = "overruled"     # Renversée par une décision ultérieure
    DISTINGUISHED = "distinguished"  # Distinguée (portée limitée)
    CONFIRMED = "confirmed"     # Confirmée par une juridiction supérieure


@dataclass
class JurisprudenceItem:
    """
    Décision de justice dans JUSLIB.

    Identifiant : JUSLIB-JURIS-{COURT_CODE}-{CASE_NUMBER}-{YYYYMMDD}-{REV:03d}
    Exemples :
      JUSLIB-JURIS-CJUE-C-311-18-20201016-001  (Schrems II)
      JUSLIB-JURIS-CEDH-73552-16-20210325-001  (Big Brother Watch)
    """

    # --- Identité ---
    juslib_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    case_number: Optional[str] = None            # Numéro d'affaire officiel
    case_name: Optional[str] = None              # Nom de l'affaire
    decision_type: DecisionType = DecisionType.JUDGMENT
    status: JurisprudenceStatus = JurisprudenceStatus.FINAL

    # --- Juridiction ---
    court_name: str = ""                         # Nom complet de la juridiction
    court_code: str = ""                         # Code court (ex: "CJUE", "CEDH", "CCASS", "CE")
    court_level: CourtLevel = CourtLevel.SUPREME
    jurisdiction: str = ""                       # ISO 3166-1 ou "EU" / "INT"
    language: str = "fr"                         # Langue de la décision
    available_languages: list[str] = field(default_factory=list)

    # --- Temporalité ---
    decision_date: Optional[date] = None
    publication_date: Optional[date] = None

    # --- Références externes ---
    ecli: Optional[str] = None                   # ECLI (European Case Law Identifier)
    hudoc_id: Optional[str] = None               # HUDOC (CEDH)
    eurlex_celex: Optional[str] = None
    national_reference: Optional[str] = None     # Référence nationale (bulletin Cass., Rec. CE…)
    doi: Optional[str] = None

    # --- Parties ---
    applicant: Optional[str] = None              # Requérant / demandeur
    respondent: Optional[str] = None             # Défendeur / État

    # --- Contenu ---
    full_text: Optional[str] = None
    headnotes: Optional[str] = None              # Points de droit (syllabus)
    operative_part: Optional[str] = None         # Dispositif
    keywords: list[str] = field(default_factory=list)
    legal_domains: list[str] = field(default_factory=list)

    # --- Relations jurisprudentielles ---
    overruled_by_id: Optional[str] = None        # FK → décision qui la renverse
    confirmed_by_ids: list[str] = field(default_factory=list)
    references_case_ids: list[str] = field(default_factory=list)  # Décisions citées

    # --- Provenance et intégrité ---
    source_url: Optional[str] = None
    source_hash: Optional[str] = None
    source_retrieved_at: Optional[datetime] = None

    # --- Versionnement ---
    revision: int = 1
    corpus_version: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.source_url:
            errors.append("INVARIANT_1: source_url obligatoire")
        if not self.source_hash:
            errors.append("INVARIANT_1: source_hash obligatoire")
        if not self.court_name:
            errors.append("court_name obligatoire")
        if not self.decision_date:
            errors.append("decision_date obligatoire")
        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        return {
            "juslib_id": self.juslib_id,
            "case_number": self.case_number,
            "case_name": self.case_name,
            "decision_type": self.decision_type.value,
            "status": self.status.value,
            "court_name": self.court_name,
            "court_code": self.court_code,
            "court_level": self.court_level.value,
            "jurisdiction": self.jurisdiction,
            "language": self.language,
            "available_languages": self.available_languages,
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "publication_date": self.publication_date.isoformat() if self.publication_date else None,
            "ecli": self.ecli,
            "hudoc_id": self.hudoc_id,
            "eurlex_celex": self.eurlex_celex,
            "national_reference": self.national_reference,
            "applicant": self.applicant,
            "respondent": self.respondent,
            "headnotes": self.headnotes,
            "operative_part": self.operative_part,
            "keywords": self.keywords,
            "legal_domains": self.legal_domains,
            "overruled_by_id": self.overruled_by_id,
            "confirmed_by_ids": self.confirmed_by_ids,
            "references_case_ids": self.references_case_ids,
            "source_url": self.source_url,
            "source_hash": f"sha256:{self.source_hash}" if self.source_hash else None,
            "source_retrieved_at": self.source_retrieved_at.isoformat() if self.source_retrieved_at else None,
            "revision": self.revision,
            "corpus_version": self.corpus_version,
            "created_at": self.created_at.isoformat(),
        }
