"""
JUSLIB — FastAPI REST API v1.

Endpoints :
  GET  /v1/health
  GET  /v1/corpus/versions
  GET  /v1/document/{juslib_id}
  POST /v1/search
  POST /v1/explain
  GET  /v1/glossary
  GET  /v1/glossary/{term}

Mode DEBUG actif — toutes les requêtes loggées.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from juslib import __version__, DEBUG_MODE
from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
from juslib.translation.multilingual import EU_LANGUAGES, UN_LANGUAGES, ALL_SUPPORTED_LANGUAGES
from juslib.versioning.corpus_tracker import CorpusTracker

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


class ExplainRequest(BaseModel):
    source_entity_id: str
    source_entity_type: str  # "document" | "disposition" | "jurisprudence"
    text: str
    reading_level: str = "citizen"  # "expert" | "intermediate" | "citizen"
    language: str = "fr"


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
async def explain(req: ExplainRequest):
    """
    Traduit un texte juridique en langage accessible.

    Niveaux :
      - expert       : texte original — jamais modifié
      - intermediate : simplification + glossaire
      - citizen      : langage courant accessible à tous

    ⚠️  Les niveaux intermediate et citizen NE sont PAS des sources juridiques.
    Toujours consulter le texte officiel pour les décisions importantes.
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

    result = _plain_engine.explain(
        source_entity_id=req.source_entity_id,
        source_entity_type=req.source_entity_type,
        text=req.text,
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
    }
    if result.ai_generated_warning:
        response["ai_warning"] = result.ai_generated_warning

    return response


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
