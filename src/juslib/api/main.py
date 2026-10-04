"""
JUSLIB — FastAPI REST API v1.

J004 :
  P0-01 : /v1/corpus/ingest séparé de /v1/corpus/import/unverified.
  P0-02 : import hashlib ajouté.

J006 (P0 MVP) :
  P0-C : /v1/search — FTS5 SQLite réel (plus de stub vide).
  P0-D : DB persistante par défaut data/juslib.db (JUSLIB_DB_PATH=:memory: pour les tests).
  P0-E : Ingestion transactionnelle atomique (BEGIN → document+capture+corpus → COMMIT/ROLLBACK).
  P0-F : Endpoints CRUD :
           POST /v1/document            — créer un document
           GET  /v1/document/{id}       — consulter un document
           POST /v1/provision           — créer une disposition
           POST /v1/version             — créer une version temporelle
           POST /v1/relation            — créer une relation entre documents
           GET  /v1/diff/{from}/{to}    — diff déterministe entre deux versions
           GET  /v1/releases            — liste des releases corpus
           POST /v1/releases            — créer une release
           GET  /v1/authority           — liste des autorités
           POST /v1/authority           — créer une autorité

RÈGLES FONDAMENTALES :
  INVARIANT-3 : Le niveau EXPERT requiert un juslib_id authentifié par connecteur.
  INVARIANT-P0-01 : ingestion_method=client_provided → jamais EXPERT/CERTAIN.
  INVARIANT-P0-03 : corpus_entries INSERT strict — jamais REPLACE.
  INVARIANT-P0-E : Toute ingestion officielle est atomique — pas de document sans capture.

Mode DEBUG actif — toutes les requêtes loggées.
CERTIFIED_100=false | unique_human_proven=false
"""

from __future__ import annotations

import hashlib  # P0-02 : import manquant ajouté
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator

from juslib import __version__, DEBUG_MODE
from juslib.db import JuslibDB
from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
from juslib.translation.multilingual import EU_LANGUAGES, UN_LANGUAGES, ALL_SUPPORTED_LANGUAGES
from juslib.versioning.corpus_tracker import CorpusTracker

# P0-D J006 : DB persistante par défaut data/juslib.db
# Tests : passer JUSLIB_DB_PATH=:memory: dans l'environnement
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "juslib.db"
)
_db_path_env = os.getenv("JUSLIB_DB_PATH")
_db_path = _db_path_env if _db_path_env is not None else _DEFAULT_DB_PATH
_db = JuslibDB(
    db_path=_db_path,
    debug=(os.getenv("JUSLIB_DEBUG", "true").lower() != "false"),
)

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
    Recherche full-text dans le corpus JUSLIB via SQLite FTS5.

    J006-P0-C : moteur FTS5 réel — plus de stub vide.

    Paramètres :
      - query : terme(s) de recherche (AND, OR, NOT, "phrase exacte" supportés)
      - language : code BCP-47 (fr, en, de, es, it, nl, pt, pl…)
      - jurisdiction : EU, FR, CA, INT, OHADA…
      - max_results : 1–100 (défaut 20)
    """
    logger.debug("[API] POST /v1/search query=%s lang=%s juris=%s",
                 req.query[:50], req.language, req.jurisdiction)

    if req.language not in ALL_SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Langue '{req.language}' non supportée. "
                   f"Langues disponibles : {sorted(ALL_SUPPORTED_LANGUAGES)[:10]}…"
        )

    limit = min(max(1, req.max_results), 100)
    results = _db.search_versions_fts(
        query=req.query,
        language=req.language if req.language != "all" else None,
        jurisdiction=req.jurisdiction,
        limit=limit,
    )

    return {
        "query": req.query,
        "language": req.language,
        "jurisdiction": req.jurisdiction,
        "results": results,
        "total": len(results),
        "engine": "sqlite_fts5",
        "invariant_1": "Chaque résultat contient source identifiable via version_id",
        "certified_100": False,
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

    # --- Résolution depuis le corpus (SQLite) ---
    corpus_entry = _db.get_corpus_entry(req.source_entity_id)
    if not corpus_entry:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "ENTITY_NOT_IN_CORPUS",
                "message": (
                    f"L'identifiant '{req.source_entity_id}' n'est pas présent dans le corpus JUSLIB. "
                    "Pour vulgariser un texte non indexé, utiliser POST /v1/explain/text. "
                    "Pour ingérer un document officiel, utiliser POST /v1/corpus/ingest."
                ),
                "invariant": "INVARIANT-3",
            }
        )

    # J004-P0-01 : EXPERT interdit si le document a été importé par un client
    ingestion_method = corpus_entry.get("ingestion_method", "client_provided")
    if level == ReadingLevel.EXPERT and ingestion_method == "client_provided":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "EXPERT_LEVEL_FORBIDDEN_ON_CLIENT_PROVIDED",
                "message": (
                    f"Le niveau EXPERT est interdit pour le document '{req.source_entity_id}' "
                    "car il a été importé par un client (ingestion_method=client_provided). "
                    "Un texte client non authentifié ne peut jamais être déclaré source juridique. "
                    "Pour obtenir le niveau EXPERT, ingérer le document via /v1/corpus/ingest "
                    "avec un connecteur officiel (ingestion_method=connector_fetched)."
                ),
                "invariant": "INVARIANT-3 + J004-P0-01",
                "ingestion_method": ingestion_method,
            }
        )

    authenticated_text = corpus_entry["text_excerpt"]
    # R003-P0-C : utiliser canonical_content_hash (texte normalisé) séparé de raw_source_hash
    stored_canonical_hash = corpus_entry.get("canonical_content_hash") or ""
    stored_raw_hash = corpus_entry.get("raw_source_hash") or ""

    # Vérification hash canonique si présent (R003-P0-C)
    import unicodedata
    import re as _re
    _normalized = unicodedata.normalize("NFC", authenticated_text)
    _normalized = _re.sub(r"\s+", " ", _normalized).strip()
    computed_canonical = hashlib.sha256(_normalized.encode("utf-8")).hexdigest()
    if stored_canonical_hash and computed_canonical != stored_canonical_hash:
        logger.error(
            "[EXPLAIN] CANONICAL HASH MISMATCH entity=%s stored=%s computed=%s",
            req.source_entity_id, stored_canonical_hash[:12], computed_canonical[:12],
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "CORPUS_INTEGRITY_FAILURE",
                "message": "Le canonical_content_hash du texte corpus ne correspond pas au hash stocké. "
                           "Intégrité du corpus compromise — arrêt de sécurité.",
                "invariant": "INVARIANT-1 + INVARIANT-4",
                "hash_field": "canonical_content_hash",
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
        "raw_source_hash_present": bool(stored_raw_hash),
        "canonical_hash_verified": bool(stored_canonical_hash),
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


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints corpus J004 — P0-01 : séparation authentifiée vs client
# ─────────────────────────────────────────────────────────────────────────────

class IngestConnectorRequest(BaseModel):
    """
    J004-P0-01 : Ingestion d'un document via connecteur officiel.
    Le serveur stocke le document avec ingestion_method='connector_fetched'.
    Le texte fourni ici représente le contenu extrait par le connecteur —
    il doit être accompagné d'une SourceCapture (raw_bytes_hash obligatoire).
    certainty_level peut être 'unverified', 'interpreted', 'contested', 'certain'.
    Il ne peut PAS être 'client_provided' (réservé aux imports non authentifiés).
    """
    title: str
    document_type: str
    jurisdiction: str
    source_url: str
    connector_id: str
    connector_version: str
    text_excerpt: str
    raw_bytes_hash: str          # SHA-256 du contenu brut récupéré par le connecteur
    http_status: int = 200
    language: str = "fr"
    eli_id: Optional[str] = None
    celex_id: Optional[str] = None
    ecli_id: Optional[str] = None
    native_id: Optional[str] = None
    entry_into_force: Optional[str] = None
    corpus_version: Optional[str] = None
    certainty_level: str = "unverified"  # jamais "client_provided" sur ce endpoint
    content_type: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None


class ImportClientRequest(BaseModel):
    """
    J004-P0-01 : Import d'un texte fourni par le CLIENT.
    ingestion_method = 'client_provided' — jamais modifiable.
    certainty_level forcé à 'unverified' — jamais élevé à 'certain'.
    Le niveau EXPERT est interdit depuis ce chemin.
    La source_url est déclarative uniquement — non vérifiée par le serveur.
    """
    title: str
    document_type: str
    jurisdiction: str
    source_url: str           # déclaratif — non vérifié
    connector_id: str = "client_import"
    text_excerpt: str
    language: str = "fr"
    native_id: Optional[str] = None
    corpus_version: Optional[str] = None


@app.post("/v1/corpus/ingest", tags=["Corpus"])
async def ingest_connector_document(req: IngestConnectorRequest):
    """
    J004-P0-01 + J006-P0-E : Ingestion officielle via connecteur — ATOMIQUE.

    Transaction unique : document + capture + corpus_entry dans un seul BEGIN/COMMIT.
    Si l'une des 3 opérations échoue → ROLLBACK complet.
    Aucun document ne peut exister sans sa SourceCapture associée.
    """
    logger.debug("[API] POST /v1/corpus/ingest connector=%s url=%s",
                 req.connector_id, req.source_url[:60])

    if req.certainty_level == "client_provided":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_CERTAINTY_FOR_CONNECTOR_INGEST",
                "message": "certainty_level='client_provided' est réservé à /v1/corpus/import/unverified. "
                           "Un connecteur officiel utilise 'unverified', 'interpreted', 'contested' ou 'certain'.",
            }
        )

    # P0-E J006 : transaction atomique — document + capture + corpus en un seul COMMIT
    import uuid as _uuid_mod
    import unicodedata as _uni_mod
    import re as _re_mod
    doc_id = f"doc:{_uuid_mod.uuid4().hex[:16]}"
    capture_id = f"cap:{_uuid_mod.uuid4().hex[:16]}"
    try:
        with _db.conn() as con:
            _norm = _uni_mod.normalize("NFC", req.text_excerpt)
            _norm = _re_mod.sub(r"\s+", " ", _norm).strip()
            canonical_hash = hashlib.sha256(_norm.encode("utf-8")).hexdigest()

            con.execute(
                """INSERT INTO legal_documents
                    (juslib_id, title, document_type, jurisdiction, language,
                     eli_id, celex_id, ecli_id, native_id, entry_into_force,
                     source_url, connector_id, raw_source_hash, canonical_content_hash,
                     corpus_version, certainty_level, production_type)
                   VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?)""",
                (doc_id, req.title, req.document_type, req.jurisdiction, req.language,
                 req.eli_id, req.celex_id, req.ecli_id, req.native_id, req.entry_into_force,
                 req.source_url, req.connector_id, req.raw_bytes_hash, canonical_hash,
                 req.corpus_version, req.certainty_level, "connector_fetched"),
            )
            con.execute(
                """INSERT INTO source_captures
                    (capture_id, juslib_id, source_url, http_status, content_type,
                     raw_bytes_hash, connector_id, connector_version,
                     etag, last_modified, corpus_version, retrieval_timestamp)
                   VALUES (?,?,?,?,?, ?,?,?, ?,?,?,datetime('now'))""",
                (capture_id, doc_id, req.source_url, req.http_status, req.content_type,
                 req.raw_bytes_hash, req.connector_id, req.connector_version,
                 req.etag, req.last_modified, req.corpus_version),
            )
            con.execute(
                """INSERT INTO corpus_entries
                    (juslib_id, text_excerpt, raw_source_hash, canonical_content_hash,
                     source_url, ingestion_method, corpus_version)
                   VALUES (?,?,?,?, ?,?,?)""",
                (doc_id, req.text_excerpt, req.raw_bytes_hash, canonical_hash,
                 req.source_url, "connector_fetched", req.corpus_version),
            )
        logger.debug("[API] ingest atomic OK doc=%s cap=%s", doc_id, capture_id)
    except Exception as e:
        logger.error("[API] ingest_connector_document ROLLBACK: %s", e)
        raise HTTPException(status_code=500, detail={"error": str(e), "rollback": True})

    return {
        "status": "ingested",
        "juslib_id": doc_id,
        "capture_id": capture_id,
        "ingestion_method": "connector_fetched",
        "canonical_hash_computed": True,
        "atomic_transaction": True,
        "expert_level_accessible": True,
        "invariant_2": "INSERT-only — enregistrement immuable",
        "invariant_p0_01": "Provenance authentifiée par connecteur + SourceCapture",
    }


@app.post("/v1/corpus/import/unverified", tags=["Corpus"])
async def import_client_document(req: ImportClientRequest):
    """
    J004-P0-01 : Import d'un texte CLIENT (non authentifié).
    ingestion_method = 'client_provided' — immuable.
    certainty_level = 'unverified' — jamais élevé.
    Niveau EXPERT interdit depuis ce chemin — /v1/explain retournera 403 sur ce document.
    La source_url est déclarative et n'est PAS vérifiée par le serveur.
    """
    logger.debug("[API] POST /v1/corpus/import/unverified connector=%s", req.connector_id)
    try:
        doc_id = _db.insert_document(
            title=req.title,
            document_type=req.document_type,
            jurisdiction=req.jurisdiction,
            source_url=req.source_url,
            connector_id=req.connector_id,
            language=req.language,
            native_id=req.native_id,
            corpus_version=req.corpus_version,
            certainty_level="client_provided",   # immuable
            production_type="rule_based",
        )
        _db.index_corpus_entry(
            juslib_id=doc_id,
            text_excerpt=req.text_excerpt,
            source_url=req.source_url,
            corpus_version=req.corpus_version,
            ingestion_method="client_provided",
        )
    except Exception as e:
        logger.error("[API] import_client_document error: %s", e)
        raise HTTPException(status_code=500, detail={"error": str(e)})

    return {
        "status": "imported",
        "juslib_id": doc_id,
        "ingestion_method": "client_provided",
        "certainty_level": "client_provided",
        "expert_level_accessible": False,
        "warning": (
            "⚠️ Ce document a été importé par le client et n'a pas été authentifié "
            "depuis une source officielle. Le niveau EXPERT est interdit. "
            "Utiliser /v1/corpus/ingest avec un connecteur officiel pour une source authentifiée."
        ),
    }


@app.get("/v1/corpus/snapshot/{document_id}", tags=["Corpus"])
async def corpus_snapshot(
    document_id: str,
    on_date: str = Query(description="Date ISO 8601 (YYYY-MM-DD) — droit applicable à cette date"),
):
    """
    Retourne le snapshot d'un document à une date donnée.
    Implémente la requête : « Quel était le texte de l'article X au 25 mai 2018 ? »

    Chaque provision retourne la version en vigueur à cette date.
    Enregistre le snapshot dans legal_snapshots pour audit.
    """
    logger.debug("[API] GET /v1/corpus/snapshot/%s on_date=%s", document_id, on_date)

    doc = _db.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' non trouvé dans le corpus."
        )

    try:
        snapshot = _db.compute_snapshot(document_id, on_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})

    return {
        "document_id": document_id,
        "snapshot_date": on_date,
        "title": doc.get("title"),
        "jurisdiction": doc.get("jurisdiction"),
        "provisions_total": len(snapshot),
        "provisions_in_force": sum(1 for s in snapshot if s["is_in_force"]),
        # P1-02 : inclut le version_status dans chaque provision
        "snapshot": snapshot,
    }


@app.get("/v1/db/stats", tags=["System"])
async def db_stats():
    """Statistiques de la base de données JUSLIB."""
    logger.debug("[API] GET /v1/db/stats")
    return _db.stats()


# ─────────────────────────────────────────────────────────────────────────────
# J006 P0-F : Endpoints CRUD — document / provision / version / relation / diff
# ─────────────────────────────────────────────────────────────────────────────

class DocumentCreateRequest(BaseModel):
    """Création d'un document juridique (ingestion non-officielle ou opérateur)."""
    title: str
    document_type: str
    jurisdiction: str
    source_url: str
    connector_id: str
    language: str = "fr"
    eli_id: Optional[str] = None
    celex_id: Optional[str] = None
    ecli_id: Optional[str] = None
    native_id: Optional[str] = None
    entry_into_force: Optional[str] = None
    corpus_version: Optional[str] = None
    certainty_level: str = "unverified"
    production_type: str = "rule_based"


@app.post("/v1/document", status_code=201, tags=["Document"])
async def create_document(req: DocumentCreateRequest):
    """
    J006-P0-F : Créer un document juridique dans le corpus.
    Pour une ingestion authentifiée avec SourceCapture, utiliser /v1/corpus/ingest.
    """
    logger.debug("[API] POST /v1/document title=%s juris=%s", req.title[:40], req.jurisdiction)
    try:
        doc_id = _db.insert_document(
            title=req.title,
            document_type=req.document_type,
            jurisdiction=req.jurisdiction,
            source_url=req.source_url,
            connector_id=req.connector_id,
            language=req.language,
            eli_id=req.eli_id,
            celex_id=req.celex_id,
            ecli_id=req.ecli_id,
            native_id=req.native_id,
            entry_into_force=req.entry_into_force,
            corpus_version=req.corpus_version,
            certainty_level=req.certainty_level,
            production_type=req.production_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})
    return {"juslib_id": doc_id, "status": "created"}


@app.get("/v1/document/{document_id}", tags=["Document"])
async def get_document(document_id: str):
    """J006-P0-F : Consulter un document juridique par son ID JUSLIB."""
    logger.debug("[API] GET /v1/document/%s", document_id)
    doc = _db.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' non trouvé.")
    return doc


class ProvisionCreateRequest(BaseModel):
    """Création d'une disposition (article, alinéa…)."""
    document_id: str
    number: Optional[str] = None
    label: Optional[str] = None
    heading: Optional[str] = None
    language: str = "fr"
    order_index: int = 0
    corpus_version: Optional[str] = None


@app.post("/v1/provision", status_code=201, tags=["Document"])
async def create_provision(req: ProvisionCreateRequest):
    """J006-P0-F : Créer une disposition dans un document existant."""
    logger.debug("[API] POST /v1/provision doc=%s num=%s", req.document_id, req.number)
    if not _db.get_document(req.document_id):
        raise HTTPException(
            status_code=404,
            detail=f"Document '{req.document_id}' non trouvé — créer le document d'abord."
        )
    try:
        prov_id = _db.insert_provision(
            document_id=req.document_id,
            number=req.number,
            label=req.label,
            heading=req.heading,
            language=req.language,
            order_index=req.order_index,
            corpus_version=req.corpus_version,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})
    return {"provision_id": prov_id, "status": "created"}


class VersionCreateRequest(BaseModel):
    """Création d'une version temporelle d'une disposition."""
    provision_id: str
    document_id: str
    text: str
    source_url: str
    valid_from: str
    valid_until: Optional[str] = None
    language: str = "fr"
    version_status: str = "in_force"
    change_type: str = "initial"
    connector_id: Optional[str] = None
    certainty_level: str = "unverified"
    production_type: str = "rule_based"
    allow_overlap: bool = False


@app.post("/v1/version", status_code=201, tags=["Document"])
async def create_version(req: VersionCreateRequest):
    """
    J006-P0-F : Créer une version temporelle d'une disposition.
    Le chevauchement temporel est rejeté sauf si allow_overlap=True.
    La version est indexée automatiquement dans FTS5.
    """
    logger.debug("[API] POST /v1/version prov=%s from=%s", req.provision_id, req.valid_from)
    try:
        ver_id = _db.insert_version(
            provision_id=req.provision_id,
            document_id=req.document_id,
            text=req.text,
            source_url=req.source_url,
            valid_from=req.valid_from,
            valid_until=req.valid_until,
            language=req.language,
            version_status=req.version_status,
            change_type=req.change_type,
            connector_id=req.connector_id,
            certainty_level=req.certainty_level,
            production_type=req.production_type,
            allow_overlap=req.allow_overlap,
        )
    except Exception as e:
        status = 409 if "chevauchement" in str(e).lower() or "overlap" in str(e).lower() else 500
        raise HTTPException(status_code=status, detail={"error": str(e)})
    return {"version_id": ver_id, "status": "created", "fts5_indexed": True}


class RelationCreateRequest(BaseModel):
    """Création d'une relation juridique entre deux documents."""
    relation_type: str          # AMENDS, REPEALS, IMPLEMENTS, INTERPRETS, OVERRULES, CITES…
    source_id: str              # ID du document source
    target_id: str              # ID du document cible
    evidence_url: str           # URL de la preuve
    evidence_text: Optional[str] = None
    confidence: float = 0.0
    certainty_level: str = "unverified"
    production_type: str = "rule_based"


@app.post("/v1/relation", status_code=201, tags=["Graph"])
async def create_relation(req: RelationCreateRequest):
    """
    J006-P0-F : Créer une relation juridique entre deux documents.
    Types supportés : AMENDS, REPEALS, IMPLEMENTS, INTERPRETS, OVERRULES, CITES,
                      TRANSPOSES, SUPPLEMENTS, ANNULS, CONFIRMS.
    """
    logger.debug("[API] POST /v1/relation type=%s src=%s tgt=%s",
                 req.relation_type, req.source_id[:12], req.target_id[:12])
    try:
        ev_id = _db.insert_relation_evidence(
            relation_type=req.relation_type,
            source_id=req.source_id,
            target_id=req.target_id,
            evidence_url=req.evidence_url,
            evidence_text=req.evidence_text,
            confidence=req.confidence,
            certainty_level=req.certainty_level,
            production_type=req.production_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})
    return {"evidence_id": ev_id, "status": "created"}


@app.get("/v1/diff/{from_version_id}/{to_version_id}", tags=["Document"])
async def diff_versions(from_version_id: str, to_version_id: str):
    """
    J006-P0-F : Diff déterministe entre deux versions d'une disposition.

    Retourne :
      - texte supprimé (marqué -)
      - texte ajouté (marqué +)
      - hash avant / hash après
      - dates de validité
      - source de chaque version

    Le diff est basé sur difflib (ligne par ligne) — déterministe et reproductible.
    Chaque diff est auditable via les hashes canoniques.
    """
    import difflib as _diff
    logger.debug("[API] GET /v1/diff/%s → %s", from_version_id[:12], to_version_id[:12])

    with _db.conn() as con:
        v_from = con.execute(
            "SELECT * FROM legal_versions WHERE version_id = ?", (from_version_id,)
        ).fetchone()
        v_to = con.execute(
            "SELECT * FROM legal_versions WHERE version_id = ?", (to_version_id,)
        ).fetchone()

    if not v_from:
        raise HTTPException(status_code=404,
                            detail=f"Version '{from_version_id}' non trouvée.")
    if not v_to:
        raise HTTPException(status_code=404,
                            detail=f"Version '{to_version_id}' non trouvée.")

    v_from = dict(v_from)
    v_to = dict(v_to)

    text_from = v_from["text"]
    text_to = v_to["text"]

    lines_from = text_from.splitlines(keepends=True)
    lines_to = text_to.splitlines(keepends=True)

    unified = list(_diff.unified_diff(
        lines_from, lines_to,
        fromfile=f"v={from_version_id} ({v_from.get('valid_from','?')})",
        tofile=f"v={to_version_id} ({v_to.get('valid_from','?')})",
        lineterm="",
    ))

    added = sum(1 for l in unified if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in unified if l.startswith("-") and not l.startswith("---"))

    return {
        "from_version_id": from_version_id,
        "to_version_id": to_version_id,
        "from_valid_from": v_from.get("valid_from"),
        "to_valid_from": v_to.get("valid_from"),
        "from_canonical_hash": v_from.get("canonical_content_hash"),
        "to_canonical_hash": v_to.get("canonical_content_hash"),
        "from_source_url": v_from.get("source_url"),
        "to_source_url": v_to.get("source_url"),
        "lines_added": added,
        "lines_removed": removed,
        "unchanged": text_from == text_to,
        "diff_unified": unified,
        "diff_engine": "difflib.unified_diff",
        "deterministic": True,
        "invariant_2": "Les versions sont immuables — le diff est toujours reproductible",
    }


# ─── Releases corpus ───────────────────────────────────────────────────────

class ReleaseCreateRequest(BaseModel):
    label: str              # ex: 2026.10.04-001
    release_date: str       # YYYY-MM-DD
    corpus_version: str
    manifest_hash: str      # SHA-256 du manifest JSON
    description: Optional[str] = None
    documents_count: int = 0
    provisions_count: int = 0
    versions_count: int = 0
    published_by: Optional[str] = None


@app.get("/v1/releases", tags=["Corpus"])
async def list_releases():
    """J006-P0-A : Liste les releases immuables du corpus."""
    logger.debug("[API] GET /v1/releases")
    releases = _db.get_corpus_releases()
    latest = _db.get_latest_corpus_release()
    return {
        "total": len(releases),
        "latest": latest,
        "releases": releases,
        "invariant": "INSERT-only — releases immuables",
    }


@app.post("/v1/releases", status_code=201, tags=["Corpus"])
async def create_release(req: ReleaseCreateRequest):
    """J006-P0-A : Créer une release immuable du corpus."""
    logger.debug("[API] POST /v1/releases label=%s", req.label)
    try:
        rel_id = _db.insert_corpus_release(
            label=req.label,
            release_date=req.release_date,
            manifest_hash=req.manifest_hash,
            corpus_version=req.corpus_version,
            description=req.description,
            documents_count=req.documents_count,
            provisions_count=req.provisions_count,
            versions_count=req.versions_count,
            published_by=req.published_by,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})
    return {"release_id": rel_id, "label": req.label, "status": "created"}


# ─── Autorités ─────────────────────────────────────────────────────────────

class AuthorityCreateRequest(BaseModel):
    short_name: str
    full_name: str
    jurisdiction: str
    authority_type: str     # LEGISLATURE, COURT, EXECUTIVE, TREATY_BODY, INTERNATIONAL…
    language: str = "fr"
    official_url: Optional[str] = None


@app.get("/v1/authority", tags=["Authority"])
async def list_authorities(
    jurisdiction: Optional[str] = Query(default=None, description="Filtre par juridiction")
):
    """J006-P0-B : Liste les autorités juridictionnelles."""
    logger.debug("[API] GET /v1/authority juris=%s", jurisdiction)
    return {"authorities": _db.get_all_authorities(jurisdiction=jurisdiction)}


@app.post("/v1/authority", status_code=201, tags=["Authority"])
async def create_authority(req: AuthorityCreateRequest):
    """J006-P0-B : Créer une autorité juridictionnelle."""
    logger.debug("[API] POST /v1/authority short_name=%s", req.short_name)
    try:
        auth_id = _db.insert_authority(
            short_name=req.short_name,
            full_name=req.full_name,
            jurisdiction=req.jurisdiction,
            authority_type=req.authority_type,
            language=req.language,
            official_url=req.official_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})
    return {"authority_id": auth_id, "status": "created"}


# ─────────────────────────────────────────────────────────────────────────────
# J007 C15 : Endpoint /v1/translation — TranslationRecord versionnée
# ─────────────────────────────────────────────────────────────────────────────

class TranslationCreateRequest(BaseModel):
    """
    C15 J007 : Création d'un TranslationRecord relié à une LegalVersion.

    Invariants :
    - version_id doit exister dans legal_versions
    - source_version_hash est calculé automatiquement côté serveur (non fourni par le client)
    - is_normative_source = 0 TOUJOURS — une traduction n'est jamais une source normative
    - production_type ne peut pas être 'source'
    """
    version_id: str
    source_language: str
    target_language: str
    translated_text: str
    translation_type: str = "official"       # official | machine | human_reviewed
    source_url: Optional[str] = None
    translator: Optional[str] = None
    certainty_level: str = "unverified"
    production_type: str = "rule_based"      # jamais 'source'

    @field_validator("production_type")
    @classmethod
    def production_type_not_source(cls, v: str) -> str:
        if v == "source":
            raise ValueError(
                "production_type='source' interdit sur une traduction. "
                "Une traduction est toujours dérivée, jamais une source normative."
            )
        return v


@app.post("/v1/translation", status_code=201, tags=["Translation"])
async def create_translation(req: TranslationCreateRequest):
    """
    J007-C15 : Créer un TranslationRecord lié à une LegalVersion précise.

    Le source_version_hash est calculé automatiquement côté serveur depuis
    le canonical_content_hash de la LegalVersion source. Cela garantit le
    lien cryptographique entre la traduction et sa version juridique source.

    Invariant absolu : une traduction ne peut jamais devenir source normative.
    """
    logger.debug("[API] POST /v1/translation version=%s %s→%s",
                 req.version_id, req.source_language, req.target_language)
    try:
        tr_id = _db.insert_translation(
            version_id=req.version_id,
            source_language=req.source_language,
            target_language=req.target_language,
            translated_text=req.translated_text,
            translation_type=req.translation_type,
            source_url=req.source_url,
            translator=req.translator,
            certainty_level=req.certainty_level,
            production_type=req.production_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})
    return {
        "translation_id": tr_id,
        "status": "created",
        "source_version_hash_linked": True,
        "is_normative_source": False,
        "invariant": "Une traduction est dérivée de sa LegalVersion source — jamais normative",
    }


@app.get("/v1/translation/{translation_id}", tags=["Translation"])
async def get_translation(translation_id: str):
    """J007-C15 : Récupérer un TranslationRecord par son ID."""
    logger.debug("[API] GET /v1/translation/%s", translation_id)
    t = _db.get_translation(translation_id)
    if not t:
        raise HTTPException(status_code=404,
                            detail=f"TranslationRecord '{translation_id}' non trouvé.")
    return t


@app.get("/v1/translation/version/{version_id}", tags=["Translation"])
async def get_translations_for_version(version_id: str):
    """J007-C15 : Lister toutes les traductions d'une version juridique."""
    logger.debug("[API] GET /v1/translation/version/%s", version_id)
    translations = _db.get_translations_for_version(version_id)
    return {
        "version_id": version_id,
        "total": len(translations),
        "translations": translations,
        "invariant": "Toutes les traductions sont liées à leur version source par source_version_hash",
    }


@app.get("/v1/translation/{translation_id}/integrity", tags=["Translation"])
async def verify_translation_integrity(translation_id: str):
    """J007-C15 : Vérifier l'intégrité cryptographique d'un TranslationRecord."""
    logger.debug("[API] GET /v1/translation/%s/integrity", translation_id)
    ok, errors = _db.verify_translation_integrity(translation_id)
    if not ok and errors and "introuvable" in errors[0]:
        raise HTTPException(status_code=404, detail={"error": errors[0]})
    return {
        "translation_id": translation_id,
        "integrity_ok": ok,
        "errors": errors,
    }
