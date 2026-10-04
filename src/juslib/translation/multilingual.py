"""
JUSLIB — Multilingual index and supported languages.

JUSLIB est une bibliothèque multilingue de niveau européen et international.
Couverture linguistique :
  - 24 langues officielles de l'UE
  - 6 langues officielles ONU
  - Langues du Conseil de l'Europe (46 États membres)
  - Langues OHADA (français)
  - Langues additionnelles : arabe, chinois, japonais, coréen, hindi

Règles JUSLIB sur les langues :
  1. Le code langue suit le standard BCP-47 / ISO 639-1
  2. La langue d'origine est toujours conservée
  3. Une traduction ne remplace jamais l'original
  4. Toute traduction produite par IA est marquée AI_GENERATED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SupportedLanguage(str, Enum):
    """
    Langues supportées par JUSLIB.
    Format : BCP-47 / ISO 639-1 deux lettres.
    """
    # 24 langues officielles de l'Union Européenne
    BG = "bg"   # Bulgare
    CS = "cs"   # Tchèque
    DA = "da"   # Danois
    DE = "de"   # Allemand
    EL = "el"   # Grec
    EN = "en"   # Anglais
    ES = "es"   # Espagnol
    ET = "et"   # Estonien
    FI = "fi"   # Finnois
    FR = "fr"   # Français
    GA = "ga"   # Irlandais
    HR = "hr"   # Croate
    HU = "hu"   # Hongrois
    IT = "it"   # Italien
    LT = "lt"   # Lituanien
    LV = "lv"   # Letton
    MT = "mt"   # Maltais
    NL = "nl"   # Néerlandais
    PL = "pl"   # Polonais
    PT = "pt"   # Portugais
    RO = "ro"   # Roumain
    SK = "sk"   # Slovaque
    SL = "sl"   # Slovène
    SV = "sv"   # Suédois
    # Langues officielles ONU (hors UE)
    AR = "ar"   # Arabe
    ZH = "zh"   # Chinois (mandarin)
    RU = "ru"   # Russe
    # Autres langues majeures
    TR = "tr"   # Turc
    NO = "no"   # Norvégien
    IS = "is"   # Islandais
    MK = "mk"   # Macédonien
    SQ = "sq"   # Albanais
    SR = "sr"   # Serbe
    BS = "bs"   # Bosnien
    UK = "uk"   # Ukrainien
    KA = "ka"   # Géorgien
    HY = "hy"   # Arménien
    # Langues additionnelles couverture internationale
    JA = "ja"   # Japonais
    KO = "ko"   # Coréen
    HI = "hi"   # Hindi


# Toutes les langues officielles UE
EU_LANGUAGES: list[str] = [
    "bg", "cs", "da", "de", "el", "en", "es", "et",
    "fi", "fr", "ga", "hr", "hu", "it", "lt", "lv",
    "mt", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
]

# Toutes les langues officielles ONU
UN_LANGUAGES: list[str] = ["ar", "zh", "en", "fr", "ru", "es"]

# Langues CEDH (officielles + langues des États membres CoE)
ECHR_LANGUAGES: list[str] = ["fr", "en"]

# Langues OHADA
OHADA_LANGUAGES: list[str] = ["fr"]

# Toutes les langues supportées par JUSLIB
ALL_SUPPORTED_LANGUAGES: list[str] = list(set(
    EU_LANGUAGES + UN_LANGUAGES + [
        "tr", "no", "is", "mk", "sq", "sr", "bs", "uk", "ka", "hy",
        "ja", "ko", "hi",
    ]
))


@dataclass
class LanguageLabel:
    """Étiquette multilingue pour un terme juridique."""
    lang: str                       # BCP-47
    text: str                       # Texte dans cette langue
    is_official: bool = True        # Traduction officielle vs générée
    is_ai_generated: bool = False   # Marquage IA obligatoire


@dataclass
class MultilingualLabel:
    """Collection de traductions pour un terme ou un titre."""
    original_lang: str
    original_text: str
    translations: list[LanguageLabel] = field(default_factory=list)

    def get(self, lang: str, fallback_lang: str = "en") -> Optional[str]:
        """Retourne le texte dans la langue demandée, avec fallback."""
        if lang == self.original_lang:
            return self.original_text
        for t in self.translations:
            if t.lang == lang:
                return t.text
        # Fallback
        for t in self.translations:
            if t.lang == fallback_lang:
                return t.text
        return self.original_text  # Dernier recours : original

    def add_translation(self, lang: str, text: str, is_official: bool = True, is_ai: bool = False) -> None:
        """Ajoute une traduction."""
        self.translations.append(LanguageLabel(
            lang=lang,
            text=text,
            is_official=is_official,
            is_ai_generated=is_ai,
        ))

    def to_dict(self) -> dict:
        return {
            "original_lang": self.original_lang,
            "original_text": self.original_text,
            "translations": [
                {
                    "lang": t.lang,
                    "text": t.text,
                    "is_official": t.is_official,
                    "is_ai_generated": t.is_ai_generated,
                }
                for t in self.translations
            ],
        }


@dataclass
class MultilingualIndex:
    """
    Index multilingue pour une entité JUSLIB.
    Associe les titres, mots-clés et résumés dans toutes les langues disponibles.
    """
    entity_id: str
    entity_type: str  # "document" | "disposition" | "jurisprudence"

    title: Optional[MultilingualLabel] = None
    summary: Optional[MultilingualLabel] = None
    keywords_by_lang: dict[str, list[str]] = field(default_factory=dict)

    def add_title(self, lang: str, text: str, original_lang: str = "fr") -> None:
        if self.title is None:
            self.title = MultilingualLabel(original_lang=original_lang, original_text=text)
        else:
            self.title.add_translation(lang, text)

    def get_title(self, lang: str) -> Optional[str]:
        if self.title:
            return self.title.get(lang)
        return None

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "title": self.title.to_dict() if self.title else None,
            "summary": self.summary.to_dict() if self.summary else None,
            "keywords_by_lang": self.keywords_by_lang,
        }
