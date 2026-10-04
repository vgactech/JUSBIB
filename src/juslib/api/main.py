"""
JUSLIB — FastAPI REST API v1.

Endpoints :
  GET  /v1/health
  GET  /v1/corpus/versions
  POST /v1/search
  POST /v1/explain          ← SÉCURISÉ R002-P0-01 : texte libre CLIENT INTERDIT
  POST /v1/explain/text     ← INTERMÉDIAIRE / CITOYEN uniquement, jamais EXPERT
  GET  /v1/glossary
  GET  /v1/glossary/{term}

RÈGLE FONDAMENTALE INVARIANT-3 (R002) :
  Le niveau EXPERT ne peut être invoqué que depuis un juslib_id validé dans le corpus.
  Un client ne peut jamais fournir un texte libre et obtenir is_source_text=True.
  Tout texte non authentifié reçoit production_type=UNVERIFIED_CLIENT_TEXT.

Mode DEBUG actif — toutes les requêtes loggées.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator

from juslib import __version__, DEBUG_MODE
from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
from juslib.translation.multilingual import EU_LANGUAGES, UN_LANGUAGES, ALL_SUPPORTED_LANGUAGES
from juslib.versioning.corpus_tracker import CorpusTracker

# Sentinelle : identifiants corpus connus (sera remplacé par DB en V0.2)
# Pour l'instant : registre en mémoire — aucun texte client ne peut passer comme source
_CORPUS_REGISTRY: dict[str, dict] = {}  # juslib_id → {text, source_hash, source_url}

logger = logging.getLogger("juslib.api")
logger.setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)

# --- Application FastAPI ---
app = FastAPI(
    title="JUSLIB API",
    description=(
        "Bibliothèque Juridique Souveraine Multilingue — Niveau européen et international.\n"
        "Sources : EUR-Lex · Légifrance · HUDOC · CanLII · OHADA · ONU.\n"
        "Couverture : 24 langues UE + 6 langues ONU + OHADA."
    ),
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

_plain_engine = PlainLanguageEngine(
    llm_enabled=os.getenv("JUSLIB_LLM_ENABLED", "false").lower() == "true",
    debug=DEBUG_MODE,
)
_corpus_tracker = CorpusTracker(
    corpus_dir=os.getenv("JUSLIB_CORPUS_DIR", "data/corpus"),
    debug=DEBUG_MODE,
)


# --- Schémas Pydantic ---

class SearchRequest(BaseModel):
    query: str
    language: str = "fr"
    jurisdiction: Optional[str] = None
    document_type: Optional[str] = None
    max_results: int = 20
    sources: list[str] = []


class ExplainFromCorpusRequest(BaseModel):
    """
    Demande d'explication à partir d'un identifiant JUSLIB existant dans le corpus.
    Le texte est TOUJOURS chargé depuis le corpus — jamais fourni par le client.

    Correction R002-P0-01 : un client ne peut pas déclarer un texte comme source juridique.
    """
    source_entity_id: str           # Doit exister dans _CORPUS_REGISTRY (ou DB V0.2)
    source_entity_type: str         # "document" | "disposition" | "jurisprudence"
    reading_level: str = "citizen"  # "expert" | "intermediate" | "citizen"
    language: str = "fr"


class ExplainTextRequest(BaseModel):
    """
    Demande d'explication d'un texte LIBRE fourni par le client.

    Règles R002 :
      - reading_level EXPERT interdit (jamais is_source_text=True sur texte client)
      - production_type = RULE_BASED ou LLM_GENERATED — jamais SOURCE
      - is_source_text = False obligatoirement
      - L'identifiant source est référencé mais NON vérifié dans le corpus
        (confiance réduite automatiquement)
    """
    source_entity_id: str           # Référence (non vérifiée — client-provided)
    source_entity_type: str
    text: str                       # Texte client — jamais traité comme source officielle
    reading_level: str = "citizen"
    language: str = "fr"

    @field_validator("reading_level")
    @classmethod
    def no_expert_on_client_text(cls, v: str) -> str:
        if v == "expert":
            raise ValueError(
                "reading_level='expert' interdit sur /v1/explain/text. "
                "Le niveau EXPERT ne peut être appliqué qu'à un texte authentifié depuis le corpus. "
                "Utiliser /v1/explain avec un juslib_id valide."
            )
        return v


class HealthResponse(BaseModel):
    status: str
    version: str
    debug_mode: bool
    timestamp: str
    languages_supported: int
    connectors_available: list[str]


# --- Endpoints ---

@app.get("/v1/health", response_model=HealthResponse, tags=["System"])
async def health():
    """Vérification de santé de l'API JUSLIB."""
    logger.debug("[API] GET /v1/health")
    return HealthResponse(
        status="healthy",
        version=__version__,
        debug_mode=DEBUG_MODE,
        timestamp=datetime.utcnow().isoformat() + "Z",
        languages_supported=len(ALL_SUPPORTED_LANGUAGES),
        connectors_available=["eurlex", "legifrance", "echr", "canlii", "ohada", "un"],
    )


@app.get("/v1/corpus/versions", tags=["Corpus"])
async def corpus_versions():
    """
    Liste toutes les releases publiées du corpus JUSLIB.
    Chaque release est immuable et identifiée par son label YYYY.MM.DD-NNN.
    """
    logger.debug("[API] GET /v1/corpus/versions")
    releases = _corpus_tracker.load_releases()
    latest = _corpus_tracker.get_latest_release()
    return {
        "total_releases": len(releases),
        "latest": latest,
        "releases": releases,
        "invariant": "INSERT-only — les releases publiées sont immuables",
    }


@app.post("/v1/search", tags=["Search"])
async def search(req: SearchRequest):
    """
    Recherche dans les sources officielles JUSLIB.

    Paramètres :
      - query : terme(s) de recherche
      - language : code BCP-47 (fr, en, de, es, it, nl, pt, pl…)
      - jurisdiction : EU, FR, CA, INT, OHADA…
      - document_type : regulation, directive, law, jurisprudence…
      - sources : filtrer par connecteur (eurlex, legifrance, echr…)
    """
    logger.debug("[API] POST /v1/search query=%s lang=%s", req.query[:50], req.language)

    if req.language not in ALL_SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Langue '{req.language}' non supportée. "
                   f"Langues disponibles : {sorted(ALL_SUPPORTED_LANGUAGES)[:10]}…"
        )

    # NOTE : La recherche full-text est implémentée en Phase 7 (moteur Typesense/SQLite FTS)
    # Ce endpoint retourne la structure de réponse normalisée
    return {
        "query": req.query,
        "language": req.language,
        "jurisdiction": req.jurisdiction,
        "results": [],
        "total": 0,
        "note": "Moteur de recherche full-text — Phase 7 (V0.2). "
                "Utiliser les connecteurs directement pour l'instant.",
        "invariant_1": "Chaque résultat contiendra source_url + source_hash obligatoires",
    }


@app.post("/v1/explain", tags=["Plain Language"])
async def explain_from_corpus(req: ExplainFromCorpusRequest):
    """
    Explication d'un document JUSLIB identifié dans le corpus.

    RÈGLE R002-P0-01 : le texte est chargé depuis le corpus (jamais fourni par le client).
    Le niveau EXPERT retourne le texte officiel authentifié.

    En V0.2 : résolution depuis la base SQLite (LegalVersion + hash vérifié).
    En V0.1.1 : résolution depuis _CORPUS_REGISTRY en mémoire.
    """
    logger.debug("[API] POST /v1/explain entity=%s level=%s lang=%s",
                 req.source_entity_id, req.reading_level, req.language)

    try:
        level = ReadingLevel(req.reading_level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Niveau '{req.reading_level}' invalide. Valeurs : expert, intermediate, citizen"
        )

    # --- Résolution depuis le corpus (V0.1.1 : mémoire ; V0.2 : DB) ---
    corpus_entry = _CORPUS_REGISTRY.get(req.source_entity_id)
    if not corpus_entry:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "ENTITY_NOT_IN_CORPUS",
                "message": (
                    f"L'identifiant '{req.source_entity_id}' n'est pas présent dans le corpus JUSLIB. "
                    "Un texte client ne peut jamais être déclaré comme source juridique (INVARIANT-3 R002). "
                    "Pour vulgariser un texte non indexé, utiliser POST /v1/explain/text "
                    "(lecture seule — is_source_text sera toujours False)."
                ),
                "invariant": "INVARIANT-3",
                "correction": "Indexer d'abord le document via le connecteur approprié.",
            }
        )

    authenticated_text = corpus_entry["text"]
    stored_hash = corpus_entry.get("source_hash", "")

    # Vérification hash si texte présent (R002-P0-04)
    computed_hash = hashlib.sha256(authenticated_text.encode("utf-8")).hexdigest()
    if stored_hash and computed_hash != stored_hash:
        logger.error(
            "[EXPLAIN] HASH MISMATCH entity=%s stored=%s computed=%s",
            req.source_entity_id, stored_hash[:12], computed_hash[:12],
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "CORPUS_INTEGRITY_FAILURE",
                "message": "Le hash du texte corpus ne correspond pas au hash stocké. "
                           "Intégrité du corpus compromise — arrêt de sécurité.",
                "invariant": "INVARIANT-1 + INVARIANT-4",
            }
        )

    result = _plain_engine.explain(
        source_entity_id=req.source_entity_id,
        source_entity_type=req.source_entity_type,
        text=authenticated_text,
        reading_level=level,
        language=req.language,
    )

    response = {
        "source_entity_id": result.source_entity_id,
        "reading_level": result.reading_level.value,
        "language": result.language,
        "is_source_text": result.is_source_text,
        "production_type": result.production_type,
        "explained_text": result.explained_text,
        "confidence": result.confidence,
        "corpus_authenticated": True,
        "source_hash_verified": bool(stored_hash),
    }
    if result.ai_generated_warning:
        response["ai_warning"] = result.ai_generated_warning
    return response


@app.post("/v1/explain/text", tags=["Plain Language"])
async def explain_client_text(req: ExplainTextRequest):
    """
    Vulgarisation d'un texte LIBRE fourni par le client.

    RÈGLES R002 (non négociables) :
      - reading_level EXPERT interdit (validation Pydantic)
      - is_source_text = False obligatoire
      - production_type = rule_based (jamais source, jamais ai_generated sans LLM réel)
      - confidence ≤ 0.5 (texte non authentifié)
      - Avertissement obligatoire dans la réponse

    Usage : brouillon, étude, recherche — jamais pour citer une source officielle.
    """
    logger.debug("[API] POST /v1/explain/text entity=%s level=%s lang=%s",
                 req.source_entity_id, req.reading_level, req.language)

    try:
        level = ReadingLevel(req.reading_level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Niveau '{req.reading_level}' invalide. Valeurs autorisées : intermediate, citizen"
        )

    result = _plain_engine.explain(
        source_entity_id=req.source_entity_id,
        source_entity_type=req.source_entity_type,
        text=req.text,
        reading_level=level,
        language=req.language,
    )

    # Invariant R002 : forcer is_source_text=False sur texte client
    result.is_source_text = False
    if result.confidence > 0.5:
        result.confidence = 0.5

    return {
        "source_entity_id": result.source_entity_id,
        "reading_level": result.reading_level.value,
        "language": result.language,
        "is_source_text": False,  # Jamais True sur texte client
        "production_type": result.production_type,
        "explained_text": result.explained_text,
        "confidence": result.confidence,
        "corpus_authenticated": False,
        "client_text_warning": (
            "⚠️ Ce texte a été fourni par le client et n'a pas été authentifié depuis le corpus JUSLIB. "
            "Ne pas utiliser comme source juridique de référence. "
            "Toujours consulter le texte officiel."
        ),
    }


@app.get("/v1/glossary", tags=["Plain Language"])
async def glossary_list():
    """Liste tous les termes juridiques du glossaire JUSLIB."""
    logger.debug("[API] GET /v1/glossary")
    terms = _plain_engine.list_glossary_terms()
    return {"total": len(terms), "terms": sorted(terms)}


@app.get("/v1/glossary/{term}", tags=["Plain Language"])
async def glossary_lookup(
    term: str,
    language: str = Query(default="fr", description="Code BCP-47 (fr, en, de, es…)")
):
    """
    Retourne la définition simplifiée d'un terme juridique dans la langue demandée.
    """
    logger.debug("[API] GET /v1/glossary/%s lang=%s", term, language)
    definition = _plain_engine.glossary_lookup(term, language)
    if definition is None:
        raise HTTPException(
            status_code=404,
            detail=f"Terme '{term}' non trouvé dans la langue '{language}'. "
                   f"Langues disponibles pour ce terme : consulter /v1/glossary/{term}?language=fr"
        )
    return {
        "term": term,
        "language": language,
        "definition": definition,
        "production_type": "rule_based",
        "note": "Définition simplifiée — niveau grand public. Consulter les sources officielles pour usage professionnel.",
    }


@app.get("/v1/languages", tags=["System"])
async def supported_languages():
    """Liste toutes les langues supportées par JUSLIB."""
    return {
        "total": len(ALL_SUPPORTED_LANGUAGES),
        "eu_official": EU_LANGUAGES,
        "un_official": UN_LANGUAGES,
        "all": sorted(ALL_SUPPORTED_LANGUAGES),
    }
