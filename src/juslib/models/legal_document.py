"""
JUSLIB — Core legal document model.

Invariants :
  1. source_url + source_hash obligatoires (pas de document sans provenance)
  2. Les versions ne sont jamais écrasées (INSERT-only)
  3. production_type distingue SOURCE / ANALYSIS / AI_GENERATED / AI_VALIDATED
  4. certainty_level distingue CERTAIN / INTERPRETED / CONTESTED / UNVERIFIED
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class DocumentType(str, Enum):
    """Types de documents juridiques couverts par JUSLIB."""
    # Sources primaires
    CONSTITUTION = "constitution"
    TREATY = "treaty"                        # Traité international
    REGULATION = "regulation"                # Règlement UE (directement applicable)
    DIRECTIVE = "directive"                  # Directive UE (transposition requise)
    DECISION = "decision"                    # Décision UE / acte individuel
    LAW = "law"                              # Loi nationale (acte législatif)
    ORDINANCE = "ordinance"                  # Ordonnance
    DECREE = "decree"                        # Décret
    ORDER = "order"                          # Arrêté / ordonnance infra-règlementaire
    CIRCULAR = "circular"                    # Circulaire (doctrine administrative)
    CHARTER = "charter"                      # Charte (ex : Charte des droits fondamentaux UE)
    CONVENTION = "convention"                # Convention internationale (CEDH, etc.)
    PROTOCOL = "protocol"                    # Protocole additionnel
    CODE = "code"                            # Code juridique (Civil, Pénal, etc.)
    # Sources secondaires
    JURISPRUDENCE = "jurisprudence"          # Décision de justice
    DOCTRINE = "doctrine"                    # Article / ouvrage doctrinal
    OPINION = "opinion"                      # Avis consultatif / AG conclusions
    REPORT = "report"                        # Rapport officiel (Parlement, Cour des comptes…)
    # Sources de soft law
    RECOMMENDATION = "recommendation"       # Recommandation UE / ONU
    RESOLUTION = "resolution"               # Résolution ONU / Parlement européen
    GUIDELINE = "guideline"                 # Lignes directrices


class ProductionType(str, Enum):
    """
    Origine de la production — jamais effaçable pour l'audit.

    R002-P0-04 : séparation stricte RULE_BASED / LLM_GENERATED / SOURCE.
    AI_GENERATED ne doit jamais être utilisé sans appel LLM réel.
    """
    SOURCE = "source"                    # Texte officiel authentifié (domaine public ou open data)
    ANALYSIS = "analysis"                # Analyse humaine validée
    RULE_BASED = "rule_based"            # Traitement algorithmique local (glossaire, règles)
    LLM_GENERATED = "llm_generated"     # Produit par un LLM réel (modèle + version enregistrés)
    LLM_VALIDATED = "llm_validated"     # Produit par LLM + validé par juriste humain
    HUMAN_AUTHORED = "human_authored"   # Rédigé directement par un juriste humain
    HUMAN_VALIDATED = "human_validated" # Toute origine + validation humaine formelle
    # Legacy — conservé pour compatibilité ascendante V0.1.0 uniquement
    AI_GENERATED = "ai_generated"        # DÉPRÉCIÉ — utiliser LLM_GENERATED + modèle explicite
    AI_VALIDATED = "ai_validated"        # DÉPRÉCIÉ — utiliser LLM_VALIDATED


class CertaintyLevel(str, Enum):
    """
    Niveau de certitude de l'information juridique.
    Règle fondamentale JUSLIB §6 : ne jamais transformer l'incertitude en certitude.
    """
    CERTAIN = "certain"            # Texte officiel en vigueur, source identifiée
    INTERPRETED = "interpreted"   # Interprétation doctrinale ou jurisprudentielle dominante
    CONTESTED = "contested"       # Jurisprudence contradictoire ou doctrine divisée
    UNVERIFIED = "unverified"      # Non encore vérifiée sur source primaire


class DocumentStatus(str, Enum):
    """État juridique du document dans le temps."""
    IN_FORCE = "in_force"              # En vigueur
    REPEALED = "repealed"              # Abrogé
    AMENDED = "amended"               # Modifié (version consolidée disponible)
    SUPERSEDED = "superseded"         # Remplacé par un autre texte
    PENDING = "pending"               # Adopté mais pas encore en vigueur
    DRAFT = "draft"                   # Projet — pas encore adopté
    EXPIRED = "expired"               # Caduc (durée limitée écoulée)
    SUSPENDED = "suspended"           # Suspendu (décision de justice ou politique)


@dataclass
class LegalDocument:
    """
    Unité documentaire centrale de JUSLIB.

    Chaque instance représente UNE VERSION d'un document juridique.
    Plusieurs versions du même texte coexistent (immuabilité).

    Identifiant : JUSLIB-{TYPE}-{JURISDICTION}-{CODE}-{YYYYMMDD}-{REV:03d}
    Exemple : JUSLIB-REGULATION-EU-2016/679-20160504-001

    Champs obligatoires pour validation :
      - juslib_id (auto-généré)
      - title (en langue originale)
      - document_type
      - jurisdiction
      - source_url
      - source_hash (SHA-256 du texte source)
      - production_type
      - certainty_level
    """

    # --- Identité ---
    juslib_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""                                    # Titre officiel (langue originale)
    short_title: Optional[str] = None                 # Titre court / alias
    document_type: DocumentType = DocumentType.LAW
    document_status: DocumentStatus = DocumentStatus.IN_FORCE

    # --- Juridiction et langue ---
    jurisdiction: str = ""                            # ISO 3166-1 alpha-2 ou "EU" / "UN" / "OHADA"
    language: str = "fr"                              # BCP-47 (ex: "fr", "en", "de", "es", "nl")
    available_languages: list[str] = field(default_factory=list)

    # --- Référence officielle ---
    official_reference: Optional[str] = None         # Ex: "JOUE L 119 du 4.5.2016"
    eurlex_celex: Optional[str] = None               # Ex: "32016R0679"
    legifrance_id: Optional[str] = None              # Ex: "LEGITEXT000006070721"
    echr_appno: Optional[str] = None                 # Numéro de requête CEDH
    un_symbol: Optional[str] = None                  # Ex: "A/RES/217(III)"
    ohada_reference: Optional[str] = None

    # --- Temporalité ---
    adoption_date: Optional[date] = None             # Date d'adoption / signature
    publication_date: Optional[date] = None          # Date de publication officielle
    entry_into_force: Optional[date] = None          # Date d'entrée en vigueur
    expiry_date: Optional[date] = None               # Date d'expiration (si limitée)
    repeal_date: Optional[date] = None               # Date d'abrogation

    # --- Contenu ---
    full_text: Optional[str] = None                  # Texte complet (optionnel en mémoire)
    summary: Optional[str] = None                    # Résumé officiel ou généré
    keywords: list[str] = field(default_factory=list)
    legal_domains: list[str] = field(default_factory=list)  # Ex: ["droit_privacy", "droit_UE"]

    # --- Provenance et intégrité (OBLIGATOIRES pour validation) ---
    source_url: Optional[str] = None                 # URL source officielle
    source_hash: Optional[str] = None               # SHA-256 hex du texte source
    source_retrieved_at: Optional[datetime] = None  # Horodatage de récupération

    # --- Production et certitude (INVARIANTS JUSLIB §4, §5, §6) ---
    production_type: ProductionType = ProductionType.SOURCE
    certainty_level: CertaintyLevel = CertaintyLevel.UNVERIFIED
    ai_warning: Optional[str] = None                # Si AI_GENERATED : avertissement explicite

    # --- Versionnement ---
    corpus_version: Optional[str] = None            # Ex: "2026.10.04-001"
    revision: int = 1
    previous_version_id: Optional[str] = None       # FK vers version précédente
    superseded_by_id: Optional[str] = None          # FK vers document successeur

    # --- Audit ---
    created_at: datetime = field(default_factory=datetime.utcnow)
    indexed_at: Optional[datetime] = None

    def compute_source_hash(self) -> Optional[str]:
        """Calcule le SHA-256 du texte source si disponible."""
        if self.full_text:
            return hashlib.sha256(self.full_text.encode("utf-8")).hexdigest()
        return None

    def generate_juslib_id(self) -> str:
        """
        Génère l'identifiant canonique JUSLIB.
        Format : JUSLIB-{TYPE}-{JURISDICTION}-{CODE}-{YYYYMMDD}-{REV:03d}
        """
        date_str = (
            self.publication_date.strftime("%Y%m%d")
            if self.publication_date
            else "00000000"
        )
        code = (
            self.official_reference.replace("/", "_").replace(" ", "_")[:40]
            if self.official_reference
            else self.juslib_id[:8]
        )
        return (
            f"JUSLIB-{self.document_type.value.upper()}"
            f"-{self.jurisdiction.upper()}"
            f"-{code}"
            f"-{date_str}"
            f"-{self.revision:03d}"
        )

    def validate(self) -> tuple[bool, list[str]]:
        """
        Valide les invariants fondamentaux JUSLIB.
        Retourne (is_valid, liste_erreurs).
        """
        errors: list[str] = []

        # Invariant 1 : source identifiable
        if not self.source_url:
            errors.append("INVARIANT_1: source_url obligatoire")
        if not self.source_hash:
            errors.append("INVARIANT_1: source_hash (SHA-256) obligatoire")

        # Invariant 5 : production_type explicite
        if self.production_type in (
            ProductionType.AI_GENERATED,
            ProductionType.AI_VALIDATED,
        ) and not self.ai_warning:
            errors.append(
                "INVARIANT_5: ai_warning obligatoire pour production IA"
                " — '[GÉNÉRÉ PAR IA — NON VALIDÉ]' minimum"
            )

        # Invariant 6 : certitude explicite
        if self.certainty_level == CertaintyLevel.UNVERIFIED and self.production_type == ProductionType.SOURCE:
            errors.append(
                "INVARIANT_6: certainty_level=UNVERIFIED sur un SOURCE — "
                "vérifier la source primaire avant de promouvoir à CERTAIN"
            )

        # Champs obligatoires
        if not self.title:
            errors.append("title obligatoire")
        if not self.jurisdiction:
            errors.append("jurisdiction obligatoire (ISO 3166-1 ou EU/UN/OHADA)")
        if not self.language:
            errors.append("language obligatoire (BCP-47)")

        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        """Sérialisation complète pour stockage et export JSON-LD."""
        return {
            "juslib_id": self.juslib_id,
            "title": self.title,
            "short_title": self.short_title,
            "document_type": self.document_type.value,
            "document_status": self.document_status.value,
            "jurisdiction": self.jurisdiction,
            "language": self.language,
            "available_languages": self.available_languages,
            "official_reference": self.official_reference,
            "eurlex_celex": self.eurlex_celex,
            "legifrance_id": self.legifrance_id,
            "echr_appno": self.echr_appno,
            "un_symbol": self.un_symbol,
            "ohada_reference": self.ohada_reference,
            "adoption_date": self.adoption_date.isoformat() if self.adoption_date else None,
            "publication_date": self.publication_date.isoformat() if self.publication_date else None,
            "entry_into_force": self.entry_into_force.isoformat() if self.entry_into_force else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "repeal_date": self.repeal_date.isoformat() if self.repeal_date else None,
            "summary": self.summary,
            "keywords": self.keywords,
            "legal_domains": self.legal_domains,
            "source_url": self.source_url,
            "source_hash": f"sha256:{self.source_hash}" if self.source_hash else None,
            "source_retrieved_at": self.source_retrieved_at.isoformat() if self.source_retrieved_at else None,
            "production_type": self.production_type.value,
            "certainty_level": self.certainty_level.value,
            "ai_warning": self.ai_warning,
            "corpus_version": self.corpus_version,
            "revision": self.revision,
            "previous_version_id": self.previous_version_id,
            "superseded_by_id": self.superseded_by_id,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"LegalDocument("
            f"type={self.document_type.value}, "
            f"jurisdiction={self.jurisdiction}, "
            f"title={self.title[:60]!r}, "
            f"status={self.document_status.value}, "
            f"certainty={self.certainty_level.value}"
            f")"
        )
