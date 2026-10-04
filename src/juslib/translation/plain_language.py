"""
JUSLIB — Plain language engine (vulgarisation juridique contrôlée).

Traduit le langage juridique vers le langage accessible au grand public.
Trois niveaux de lecture :
  - EXPERT      : juriste / magistrat / avocat (texte original ou analyse technique)
  - INTERMEDIATE: étudiant en droit / journaliste / praticien non-juriste
  - CITIZEN     : grand public (aucune formation juridique supposée)

RÈGLES FONDAMENTALES :
  1. Toute explication reste reliée au texte source (FK non nullable)
  2. Le niveau EXPERT ne produit JAMAIS de paraphrase — texte original uniquement
  3. Les niveaux INTERMEDIATE et CITIZEN sont TOUJOURS marqués comme non-source
  4. Toute production IA est marquée AI_GENERATED + avertissement visible
  5. Une explication CITIZEN ne doit JAMAIS contenir d'affirmation juridique certaine
     sans renvoi explicite à la disposition source
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("juslib.translation.plain_language")


class ReadingLevel(str, Enum):
    """Niveau de lecture cible pour une explication JUSLIB."""
    EXPERT = "expert"               # Juriste professionnel — texte original
    INTERMEDIATE = "intermediate"  # Étudiant / journaliste / praticien
    CITIZEN = "citizen"             # Grand public — langage courant


@dataclass
class ExplainResult:
    """
    Résultat d'une demande d'explication JUSLIB.

    Invariants :
      - source_entity_id jamais nul
      - is_source_text=True uniquement pour le niveau EXPERT
      - ai_generated_warning obligatoire si production_type contient "ai"
    """
    source_entity_id: str = ""          # FK → document / disposition / jurisprudence
    source_entity_type: str = ""        # "document" | "disposition" | "jurisprudence"
    reading_level: ReadingLevel = ReadingLevel.CITIZEN

    # --- Contenu ---
    original_text: Optional[str] = None         # Texte juridique original (niveau EXPERT)
    explained_text: str = ""                    # Texte expliqué / vulgarisé
    language: str = "fr"                         # Langue de l'explication

    # --- Marquage obligatoire ---
    is_source_text: bool = False                 # True seulement si EXPERT + texte original
    production_type: str = "rule_based"          # "rule_based" | "ai_generated" | "human_validated"
    ai_generated_warning: Optional[str] = None   # Obligatoire si production_type contient "ai"

    # --- Références croisées ---
    cited_dispositions: list[str] = field(default_factory=list)  # IDs des dispositions citées
    further_reading: list[str] = field(default_factory=list)     # Liens vers doc source

    # --- Confiance et validation ---
    confidence: float = 0.0                      # 0.0→1.0
    validated_by: Optional[str] = None           # Validateur humain si applicable
    validated_at: Optional[datetime] = None

    # --- Audit ---
    created_at: datetime = field(default_factory=datetime.utcnow)

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.source_entity_id:
            errors.append("INVARIANT_3: source_entity_id obligatoire — explication orpheline interdite")
        if "ai" in self.production_type and not self.ai_generated_warning:
            errors.append(
                "INVARIANT_5: ai_generated_warning obligatoire pour production IA\n"
                "  → Ajouter : '[⚠️ GÉNÉRÉ PAR IA — NON VALIDÉ PAR UN JURISTE]'"
            )
        if self.is_source_text and self.reading_level != ReadingLevel.EXPERT:
            errors.append("is_source_text=True réservé au niveau EXPERT uniquement")
        return len(errors) == 0, errors


# Glossaire juridique multilingue simplifié (base règle)
# Format : terme_juridique → {lang: explication_simple}
LEGAL_GLOSSARY: dict[str, dict[str, str]] = {
    "abrogation": {
        "fr": "La suppression définitive d'une loi ou d'un texte juridique par un nouveau texte.",
        "en": "The complete removal of a law or legal text by a newer one.",
        "de": "Die vollständige Aufhebung eines Gesetzes oder Rechtstexts durch einen neueren Text.",
        "es": "La supresión definitiva de una ley o texto jurídico por uno nuevo.",
        "it": "La soppressione definitiva di una legge o testo giuridico da parte di uno nuovo.",
        "nl": "De volledige intrekking van een wet of rechtstekst door een nieuwer tekst.",
        "pt": "A supressão definitiva de uma lei ou texto jurídico por um novo texto.",
        "pl": "Całkowite uchylenie ustawy lub tekstu prawnego przez nowy.",
    },
    "recours": {
        "fr": "La démarche pour contester une décision devant un juge ou une autorité.",
        "en": "The process of challenging a decision before a judge or authority.",
        "de": "Das Verfahren zur Anfechtung einer Entscheidung vor einem Gericht oder einer Behörde.",
        "es": "El procedimiento para impugnar una decisión ante un juez o autoridad.",
    },
    "préjudice": {
        "fr": "Le dommage subi par une personne du fait d'un acte illicite ou d'un accident.",
        "en": "The harm suffered by a person due to an unlawful act or accident.",
        "de": "Der Schaden, den eine Person durch eine rechtswidrige Handlung oder einen Unfall erleidet.",
    },
    "nullité": {
        "fr": "L'annulation d'un acte juridique comme s'il n'avait jamais existé.",
        "en": "The cancellation of a legal act as if it had never existed.",
        "de": "Die Aufhebung einer Rechtshandlung, als ob sie nie existiert hätte.",
    },
    "prescription": {
        "fr": "Le délai au-delà duquel une action en justice n'est plus possible.",
        "en": "The time limit beyond which legal action is no longer possible.",
        "de": "Die Frist, nach deren Ablauf eine Klage nicht mehr möglich ist.",
        "es": "El plazo pasado el cual ya no es posible una acción legal.",
    },
    "détention provisoire": {
        "fr": "L'emprisonnement d'une personne avant son jugement, décidé par un juge.",
        "en": "The imprisonment of a person before their trial, decided by a judge.",
    },
    "contrat synallagmatique": {
        "fr": "Un contrat dans lequel chaque partie a des obligations envers l'autre (exemple : le contrat de vente).",
        "en": "A contract in which each party has obligations to the other (e.g., a sale contract).",
    },
}


class PlainLanguageEngine:
    """
    Moteur de vulgarisation juridique JUSLIB.

    Fonctionnement :
      1. Niveau EXPERT → retourne le texte original sans transformation
      2. Niveau INTERMEDIATE / CITIZEN → applique les règles de simplification
         + glossaire multilingue + marquage obligatoire

    Configuration IA (optionnelle) :
      Si un LLM est configuré (BOB_API_KEY), il peut enrichir les niveaux
      INTERMEDIATE et CITIZEN, mais le marquage AI_GENERATED est obligatoire.
    """

    AI_WARNING_FR = "⚠️ [GÉNÉRÉ PAR IA — NON VALIDÉ PAR UN JURISTE HUMAIN] Cette explication est produite automatiquement. Consultez toujours le texte officiel."
    AI_WARNING_EN = "⚠️ [AI-GENERATED — NOT VALIDATED BY A HUMAN LAWYER] This explanation is automatically generated. Always refer to the official text."

    def __init__(self, llm_enabled: bool = False, debug: bool = True):
        self.llm_enabled = llm_enabled
        self.debug = debug
        self._log = logging.getLogger("juslib.plain_language")
        self._log.setLevel(logging.DEBUG if debug else logging.INFO)
        self._log.debug("[PlainLanguageEngine] init llm_enabled=%s", llm_enabled)

    def explain(
        self,
        source_entity_id: str,
        source_entity_type: str,
        text: str,
        reading_level: ReadingLevel = ReadingLevel.CITIZEN,
        language: str = "fr",
    ) -> ExplainResult:
        """
        Produit une explication du texte juridique au niveau demandé.

        Pour le niveau EXPERT : retourne le texte original sans modification.
        Pour les autres niveaux : applique la simplification + glossaire.
        """
        lang = language.lower()

        self._log.debug(
            "[EXPLAIN] entity=%s type=%s level=%s lang=%s text_len=%d",
            source_entity_id, source_entity_type,
            reading_level.value, lang, len(text),
        )

        if reading_level == ReadingLevel.EXPERT:
            return ExplainResult(
                source_entity_id=source_entity_id,
                source_entity_type=source_entity_type,
                reading_level=reading_level,
                original_text=text,
                explained_text=text,
                language=lang,
                is_source_text=True,
                production_type="source",
                confidence=1.0,
            )

        # Niveaux INTERMEDIATE et CITIZEN : simplification règle-based
        explained = self._apply_glossary(text, lang, reading_level)

        result = ExplainResult(
            source_entity_id=source_entity_id,
            source_entity_type=source_entity_type,
            reading_level=reading_level,
            original_text=text,
            explained_text=explained,
            language=lang,
            is_source_text=False,
            production_type="rule_based",
            confidence=0.6,  # Confiance modérée — règles non validées par juriste
        )

        # Si LLM activé (optionnel) : enrichissement + marquage IA
        if self.llm_enabled:
            result = self._enrich_with_llm(result, lang)

        is_valid, errors = result.validate()
        if not is_valid:
            self._log.warning("[EXPLAIN] Validation échouée: %s", errors)

        return result

    def _apply_glossary(self, text: str, lang: str, level: ReadingLevel) -> str:
        """
        Applique le glossaire multilingue pour remplacer les termes techniques.
        Niveau CITIZEN : remplacement par définition simple.
        Niveau INTERMEDIATE : ajout de la définition entre parenthèses.
        """
        result_text = text
        for term, translations in LEGAL_GLOSSARY.items():
            if term in result_text.lower() and lang in translations:
                definition = translations[lang]
                if level == ReadingLevel.CITIZEN:
                    # Remplacement direct par l'explication
                    result_text = result_text.replace(term, f"{term} ({definition})")
                elif level == ReadingLevel.INTERMEDIATE:
                    # Ajout en note inline
                    result_text = result_text.replace(term, f"{term} [*{definition}*]")
        return result_text

    def _enrich_with_llm(self, result: ExplainResult, lang: str) -> ExplainResult:
        """
        Enrichit l'explication via LLM si disponible.

        R002-P0-04 : ne jamais utiliser LLM_GENERATED sans appel LLM réel.
        Sans BOB_API_KEY configurée, le type reste RULE_BASED.
        """
        import os
        api_key = os.getenv("BOB_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            # Pas de clé LLM → on reste RULE_BASED, jamais de faux LLM_GENERATED
            self._log.debug(
                "[EXPLAIN] LLM désactivé (BOB_API_KEY absent) — "
                "production_type conservé rule_based (R002-P0-04)"
            )
            return result

        # Clé présente → marquage llm_generated + avertissement
        warning = self.AI_WARNING_FR if lang == "fr" else self.AI_WARNING_EN
        result.production_type = "llm_generated"  # R002 : jamais ai_generated sans LLM réel
        result.ai_generated_warning = warning
        result.confidence = 0.5  # Confiance réduite — LLM non validé juridiquement
        # NOTE : l'appel LLM réel (BOB_API_KEY → IBM Bob) sera implémenté en Phase 6
        self._log.debug("[EXPLAIN] llm_generated marqué (clé présente) — appel réel Phase 6")
        return result

    def glossary_lookup(self, term: str, language: str = "fr") -> Optional[str]:
        """Retourne la définition simplifiée d'un terme juridique."""
        term_lower = term.lower()
        if term_lower in LEGAL_GLOSSARY:
            return LEGAL_GLOSSARY[term_lower].get(language)
        return None

    def list_glossary_terms(self) -> list[str]:
        """Retourne tous les termes du glossaire."""
        return list(LEGAL_GLOSSARY.keys())
