"""
JUSLIB — Couche de persistance SQLite (R003-P0-E).

Remplace _CORPUS_REGISTRY dict Python en mémoire par un vrai schéma relationnel
avec FK réelles, contraintes NOT NULL, INSERT-only enforced par triggers.

Tables :
  legal_documents   : documents normatifs (lois, règlements, conventions…)
  legal_provisions  : subdivisions (articles, paragraphes, titres…)
  legal_versions    : textes exacts d'une provision par période (INSERT-only)
  legal_snapshots   : vue du corpus à une date donnée (droit applicable)
  relation_evidence : preuves des relations entre dispositions
  authorities       : sources faisant autorité (juridictions, organes)
  translation_records : traductions vérifiées de provisions
  corpus_entries    : index corpus (remplace _CORPUS_REGISTRY)

Identifiants officiels (séparés des JUSLIB-IDs internes) :
  eli_id    : European Legislation Identifier (ELI)
  celex_id  : EUR-Lex CELEX number
  ecli_id   : European Case Law Identifier (ECLI)

Invariants :
  1. Toute donnée a une source identifiable (source_url NOT NULL)
  2. INSERT-only — triggers bloquent UPDATE/DELETE sur les tables versionnées
  3. FK réelles avec PRAGMA foreign_keys=ON
  4. canonical_content_hash ≠ raw_source_hash (champs séparés)
  5. Toute production IA marquée production_type='llm_generated'
  6. Niveau de certitude présent sur chaque entrée

Mode DEBUG actif — toutes les opérations loggées.
CERTIFIED_100=false | unique_human_proven=false
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger("juslib.db")
logger.setLevel(logging.DEBUG if os.getenv("JUSLIB_DEBUG", "true").lower() != "false" else logging.INFO)

# Schéma SQL complet — INSERT-only enforced par triggers sur les tables versionnées
_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────
-- Table 1 : Autorités juridictionnelles
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS authorities (
    authority_id      TEXT PRIMARY KEY,
    short_name        TEXT NOT NULL,
    full_name         TEXT NOT NULL,
    jurisdiction      TEXT NOT NULL,         -- ISO 3166-1 alpha-2 ou "EU", "INT", "OHADA"
    authority_type    TEXT NOT NULL,         -- COURT | LEGISLATURE | EXECUTIVE | TREATY_BODY | OTHER
    language          TEXT NOT NULL DEFAULT 'fr',
    official_url      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────
-- Table 2 : Documents normatifs
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_documents (
    juslib_id         TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    document_type     TEXT NOT NULL,         -- regulation | directive | law | decree | constitution | treaty…
    jurisdiction      TEXT NOT NULL,
    language          TEXT NOT NULL DEFAULT 'fr',

    -- Identifiants officiels (INVARIANT : séparés du juslib_id interne)
    eli_id            TEXT,                  -- European Legislation Identifier
    celex_id          TEXT,                  -- EUR-Lex CELEX
    ecli_id           TEXT,                  -- European Case Law Identifier (pour jurisprudence)
    native_id         TEXT,                  -- ID natif de la source (ex: LEGITEXT000006070721)

    -- Métadonnées temporelles
    entry_into_force  TEXT,                  -- ISO 8601
    publication_date  TEXT,
    adoption_date     TEXT,
    repeal_date       TEXT,

    -- Source et intégrité
    source_url        TEXT NOT NULL,         -- INVARIANT-1 : source obligatoire
    connector_id      TEXT NOT NULL,
    raw_source_hash   TEXT,                  -- sha256:... du contenu brut source
    canonical_content_hash TEXT,            -- sha256:... du texte normalisé

    -- Versionnement INSERT-only
    corpus_version    TEXT,
    production_type   TEXT NOT NULL DEFAULT 'rule_based',  -- rule_based | llm_generated | human_validated
    certainty_level   TEXT NOT NULL DEFAULT 'unverified',  -- certain | interpreted | contested | unverified
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT chk_production_type CHECK (production_type IN ('rule_based','llm_generated','human_validated','source')),
    CONSTRAINT chk_certainty CHECK (certainty_level IN ('certain','interpreted','contested','unverified'))
);

-- INSERT-only trigger sur legal_documents
CREATE TRIGGER IF NOT EXISTS trg_no_update_legal_documents
BEFORE UPDATE ON legal_documents
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_documents est INSERT-only — utiliser un nouvel enregistrement');
END;

CREATE TRIGGER IF NOT EXISTS trg_no_delete_legal_documents
BEFORE DELETE ON legal_documents
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_documents est INSERT-only — les suppressions sont interdites');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 3 : Subdivisions (articles, paragraphes, titres…)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_provisions (
    provision_id      TEXT PRIMARY KEY,
    document_id       TEXT NOT NULL REFERENCES legal_documents(juslib_id),
    number            TEXT,                  -- "17", "L.111-1", "§3"
    label             TEXT,                  -- "Article 17"
    heading           TEXT,                  -- Intitulé officiel
    language          TEXT NOT NULL DEFAULT 'fr',
    order_index       INTEGER NOT NULL DEFAULT 0,
    corpus_version    TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────
-- Table 4 : Versions de textes (INSERT-only strict)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_versions (
    version_id               TEXT PRIMARY KEY,
    provision_id             TEXT NOT NULL REFERENCES legal_provisions(provision_id),
    document_id              TEXT NOT NULL REFERENCES legal_documents(juslib_id),

    -- Texte exact
    text                     TEXT NOT NULL,
    language                 TEXT NOT NULL DEFAULT 'fr',

    -- Hashes R003-P0-B/C séparés obligatoirement
    raw_source_hash          TEXT,           -- sha256:... contenu brut
    canonical_content_hash   TEXT,          -- sha256:... texte normalisé (NFC + collapse ws)

    -- Temporalité
    valid_from               TEXT NOT NULL,  -- INVARIANT : date obligatoire
    valid_until              TEXT,           -- NULL = toujours en vigueur
    publication_date         TEXT,
    adoption_date            TEXT,

    -- Nature de la modification
    change_type              TEXT NOT NULL DEFAULT 'initial',
    amending_document_id     TEXT,
    amending_provision       TEXT,

    -- Provenance
    source_url               TEXT NOT NULL,  -- INVARIANT-1
    connector_id             TEXT,

    -- Versionnement
    revision                 INTEGER NOT NULL DEFAULT 1,
    previous_version_id      TEXT,
    corpus_version           TEXT,
    certainty_level          TEXT NOT NULL DEFAULT 'unverified',
    production_type          TEXT NOT NULL DEFAULT 'rule_based',
    created_at               TEXT NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT chk_change_type CHECK (change_type IN
        ('initial','amendment','consolidation','correction','repeal','partial_repeal','suspension')),
    CONSTRAINT chk_production_type CHECK (production_type IN ('rule_based','llm_generated','human_validated','source')),
    CONSTRAINT chk_certainty CHECK (certainty_level IN ('certain','interpreted','contested','unverified'))
);

-- INSERT-only triggers sur legal_versions
CREATE TRIGGER IF NOT EXISTS trg_no_update_legal_versions
BEFORE UPDATE ON legal_versions
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_versions est INSERT-only — chaque modification crée une nouvelle version');
END;

CREATE TRIGGER IF NOT EXISTS trg_no_delete_legal_versions
BEFORE DELETE ON legal_versions
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_versions est INSERT-only — les suppressions sont interdites');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 5 : Snapshots (droit applicable à une date)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_snapshots (
    snapshot_id       TEXT PRIMARY KEY,
    provision_id      TEXT NOT NULL REFERENCES legal_provisions(provision_id),
    snapshot_date     TEXT NOT NULL,         -- ISO 8601 : date de la requête
    version_id        TEXT NOT NULL REFERENCES legal_versions(version_id),
    is_in_force       INTEGER NOT NULL DEFAULT 1,  -- 1=en vigueur, 0=abrogé
    computed_at       TEXT NOT NULL DEFAULT (datetime('now')),
    corpus_version    TEXT
);

-- ─────────────────────────────────────────────────────────────────────
-- Table 6 : Preuves des relations juridiques
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS relation_evidence (
    evidence_id       TEXT PRIMARY KEY,
    relation_type     TEXT NOT NULL,         -- MODIFIES | REPEALS | IMPLEMENTS | TRANSPOSES | CITES…
    source_id         TEXT NOT NULL,         -- ID JUSLIB de la disposition source
    target_id         TEXT NOT NULL,         -- ID JUSLIB de la disposition cible
    evidence_text     TEXT,                  -- Extrait du texte qui établit la relation
    evidence_url      TEXT NOT NULL,         -- INVARIANT-1 : source de la preuve
    confidence        REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    certainty_level   TEXT NOT NULL DEFAULT 'unverified',
    production_type   TEXT NOT NULL DEFAULT 'rule_based',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────
-- Table 7 : Traductions vérifiées de provisions
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS translation_records (
    translation_id    TEXT PRIMARY KEY,
    version_id        TEXT NOT NULL REFERENCES legal_versions(version_id),
    source_language   TEXT NOT NULL,         -- BCP-47
    target_language   TEXT NOT NULL,         -- BCP-47
    translated_text   TEXT NOT NULL,
    translation_type  TEXT NOT NULL DEFAULT 'official',  -- official | machine | human_reviewed
    source_url        TEXT,                  -- URL de la traduction officielle si disponible
    translator        TEXT,                  -- Organisme/service traducteur
    canonical_hash    TEXT,                  -- sha256:... texte traduit normalisé
    certainty_level   TEXT NOT NULL DEFAULT 'unverified',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT chk_trans_type CHECK (translation_type IN ('official','machine','human_reviewed'))
);

-- ─────────────────────────────────────────────────────────────────────
-- Table 8 : Index corpus (remplace _CORPUS_REGISTRY dict mémoire — P0-E)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corpus_entries (
    juslib_id             TEXT PRIMARY KEY REFERENCES legal_documents(juslib_id),
    text_excerpt          TEXT NOT NULL,     -- Extrait ou texte complet du document
    raw_source_hash       TEXT,              -- sha256:... contenu brut source
    canonical_content_hash TEXT,            -- sha256:... texte normalisé
    source_url            TEXT NOT NULL,
    corpus_version        TEXT,
    indexed_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────
-- Index de performance
-- ─────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_docs_jurisdiction ON legal_documents(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_docs_eli ON legal_documents(eli_id) WHERE eli_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_docs_celex ON legal_documents(celex_id) WHERE celex_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_docs_ecli ON legal_documents(ecli_id) WHERE ecli_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_docs_native ON legal_documents(native_id) WHERE native_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_provisions_doc ON legal_provisions(document_id);
CREATE INDEX IF NOT EXISTS idx_versions_provision ON legal_versions(provision_id);
CREATE INDEX IF NOT EXISTS idx_versions_validity ON legal_versions(valid_from, valid_until);
CREATE INDEX IF NOT EXISTS idx_snapshots_provision_date ON legal_snapshots(provision_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_relation_source ON relation_evidence(source_id);
CREATE INDEX IF NOT EXISTS idx_relation_target ON relation_evidence(target_id);
CREATE INDEX IF NOT EXISTS idx_translations_version ON translation_records(version_id);
CREATE INDEX IF NOT EXISTS idx_translations_lang ON translation_records(source_language, target_language);
"""


def _compute_canonical_hash(text: str) -> str:
    """
    Calcule le hash canonique d'un texte : NFC + collapse whitespace + strip + SHA-256.
    Utilisé à la fois pour le stockage et pour la vérification (pas d'effet de bord).
    """
    normalized = unicodedata.normalize("NFC", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _compute_raw_hash(raw_bytes: bytes) -> str:
    """Calcule le hash SHA-256 du contenu brut (avant parsing/normalisation)."""
    return hashlib.sha256(raw_bytes).hexdigest()


class JuslibDB:
    """
    Gestionnaire de base de données SQLite pour JUSLIB.

    Une seule instance par processus recommandée.
    Thread-safe : utiliser check_same_thread=False avec serialisation externe.

    Usage :
        db = JuslibDB()                         # mémoire (tests)
        db = JuslibDB("data/corpus/juslib.db")  # persistant
        with db.conn() as con:
            con.execute("SELECT …")
    """

    def __init__(self, db_path: Optional[str] = None, debug: bool = True):
        self._path = db_path or ":memory:"
        self._debug = debug
        self._log = logging.getLogger("juslib.db")
        if debug:
            self._log.setLevel(logging.DEBUG)

        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        self._connection: Optional[sqlite3.Connection] = None
        self._init_db()
        self._log.debug("[JuslibDB] initialisée path=%s", self._path)

    def _init_db(self) -> None:
        """Crée les tables, triggers et index si absent."""
        con = self._get_connection()
        con.executescript(_SCHEMA_SQL)
        con.commit()
        self._log.debug("[JuslibDB] schéma initialisé")

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                self._path,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._connection.row_factory = sqlite3.Row
        return self._connection

    @contextmanager
    def conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager retournant la connexion — commit auto sur succès."""
        con = self._get_connection()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise

    def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None

    # ─────────────────────────────────────────────────────────────────
    # Documents normatifs
    # ─────────────────────────────────────────────────────────────────

    def insert_document(
        self,
        title: str,
        document_type: str,
        jurisdiction: str,
        source_url: str,
        connector_id: str,
        *,
        language: str = "fr",
        eli_id: Optional[str] = None,
        celex_id: Optional[str] = None,
        ecli_id: Optional[str] = None,
        native_id: Optional[str] = None,
        entry_into_force: Optional[str] = None,
        publication_date: Optional[str] = None,
        adoption_date: Optional[str] = None,
        repeal_date: Optional[str] = None,
        raw_source_hash: Optional[str] = None,
        canonical_content_hash: Optional[str] = None,
        corpus_version: Optional[str] = None,
        production_type: str = "rule_based",
        certainty_level: str = "unverified",
    ) -> str:
        """Insère un document normatif. Retourne le juslib_id généré."""
        juslib_id = f"JUSLIB-DOC-{jurisdiction.upper()}-{uuid.uuid4().hex[:8].upper()}"
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO legal_documents (
                    juslib_id, title, document_type, jurisdiction, language,
                    eli_id, celex_id, ecli_id, native_id,
                    entry_into_force, publication_date, adoption_date, repeal_date,
                    source_url, connector_id,
                    raw_source_hash, canonical_content_hash,
                    corpus_version, production_type, certainty_level
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    juslib_id, title, document_type, jurisdiction, language,
                    eli_id, celex_id, ecli_id, native_id,
                    entry_into_force, publication_date, adoption_date, repeal_date,
                    source_url, connector_id,
                    raw_source_hash, canonical_content_hash,
                    corpus_version, production_type, certainty_level,
                ),
            )
        self._log.debug("[DB] insert_document id=%s title=%.40s", juslib_id, title)
        return juslib_id

    def get_document(self, juslib_id: str) -> Optional[dict[str, Any]]:
        """Récupère un document par son juslib_id."""
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM legal_documents WHERE juslib_id = ?", (juslib_id,)
            ).fetchone()
        return dict(row) if row else None

    def find_documents_by_identifier(
        self,
        *,
        eli_id: Optional[str] = None,
        celex_id: Optional[str] = None,
        ecli_id: Optional[str] = None,
        native_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Recherche par identifiant officiel (ELI/CELEX/ECLI/natif)."""
        conditions = []
        params = []
        if eli_id:
            conditions.append("eli_id = ?")
            params.append(eli_id)
        if celex_id:
            conditions.append("celex_id = ?")
            params.append(celex_id)
        if ecli_id:
            conditions.append("ecli_id = ?")
            params.append(ecli_id)
        if native_id:
            conditions.append("native_id = ?")
            params.append(native_id)
        if not conditions:
            return []
        where = " OR ".join(conditions)
        with self.conn() as con:
            rows = con.execute(
                f"SELECT * FROM legal_documents WHERE {where}", params
            ).fetchall()
        return [dict(r) for r in rows]

    # ─────────────────────────────────────────────────────────────────
    # Provisions et versions
    # ─────────────────────────────────────────────────────────────────

    def insert_provision(
        self,
        document_id: str,
        *,
        number: Optional[str] = None,
        label: Optional[str] = None,
        heading: Optional[str] = None,
        language: str = "fr",
        order_index: int = 0,
        corpus_version: Optional[str] = None,
    ) -> str:
        """Insère une subdivision de document. Retourne le provision_id."""
        provision_id = str(uuid.uuid4())
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO legal_provisions (
                    provision_id, document_id, number, label, heading,
                    language, order_index, corpus_version
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (provision_id, document_id, number, label, heading,
                 language, order_index, corpus_version),
            )
        self._log.debug("[DB] insert_provision id=%s doc=%s num=%s", provision_id, document_id, number)
        return provision_id

    def insert_version(
        self,
        provision_id: str,
        document_id: str,
        text: str,
        valid_from: str,
        source_url: str,
        *,
        language: str = "fr",
        valid_until: Optional[str] = None,
        change_type: str = "initial",
        revision: int = 1,
        previous_version_id: Optional[str] = None,
        corpus_version: Optional[str] = None,
        connector_id: Optional[str] = None,
        raw_source_hash: Optional[str] = None,
        certainty_level: str = "unverified",
        production_type: str = "rule_based",
        amending_document_id: Optional[str] = None,
    ) -> str:
        """
        Insère une nouvelle version de texte (INSERT-only).
        Calcule automatiquement canonical_content_hash si non fourni.
        Retourne le version_id.
        """
        version_id = str(uuid.uuid4())
        canonical_hash = _compute_canonical_hash(text)
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO legal_versions (
                    version_id, provision_id, document_id, text, language,
                    raw_source_hash, canonical_content_hash,
                    valid_from, valid_until, change_type,
                    source_url, connector_id,
                    revision, previous_version_id, corpus_version,
                    certainty_level, production_type, amending_document_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    version_id, provision_id, document_id, text, language,
                    raw_source_hash, canonical_hash,
                    valid_from, valid_until, change_type,
                    source_url, connector_id,
                    revision, previous_version_id, corpus_version,
                    certainty_level, production_type, amending_document_id,
                ),
            )
        self._log.debug("[DB] insert_version id=%s provision=%s from=%s", version_id, provision_id, valid_from)
        return version_id

    # ─────────────────────────────────────────────────────────────────
    # Snapshot : droit applicable à une date
    # ─────────────────────────────────────────────────────────────────

    def get_version_at_date(
        self, provision_id: str, on_date: str
    ) -> Optional[dict[str, Any]]:
        """
        Retourne la version en vigueur d'une provision à la date donnée.
        on_date : ISO 8601 (YYYY-MM-DD).

        Logique : valid_from <= on_date AND (valid_until IS NULL OR valid_until > on_date)
        En cas de plusieurs versions valides, retourne la plus récente (valid_from MAX).
        """
        with self.conn() as con:
            row = con.execute(
                """
                SELECT * FROM legal_versions
                WHERE provision_id = ?
                  AND valid_from <= ?
                  AND (valid_until IS NULL OR valid_until > ?)
                ORDER BY valid_from DESC, revision DESC
                LIMIT 1
                """,
                (provision_id, on_date, on_date),
            ).fetchone()
        return dict(row) if row else None

    def compute_snapshot(
        self, document_id: str, on_date: str, corpus_version: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Calcule le snapshot complet d'un document à une date donnée.
        Retourne la liste des (provision, version) en vigueur à cette date.
        Enregistre les snapshots dans legal_snapshots pour audit.
        """
        results = []
        with self.conn() as con:
            provisions = con.execute(
                "SELECT * FROM legal_provisions WHERE document_id = ? ORDER BY order_index",
                (document_id,),
            ).fetchall()

        for prov in provisions:
            version = self.get_version_at_date(prov["provision_id"], on_date)
            is_in_force = 1 if version else 0
            if version:
                snap_id = str(uuid.uuid4())
                with self.conn() as con:
                    con.execute(
                        """
                        INSERT OR IGNORE INTO legal_snapshots (
                            snapshot_id, provision_id, snapshot_date, version_id,
                            is_in_force, corpus_version
                        ) VALUES (?,?,?,?,?,?)
                        """,
                        (snap_id, prov["provision_id"], on_date,
                         version["version_id"], is_in_force, corpus_version),
                    )
                results.append({
                    "provision": dict(prov),
                    "version": version,
                    "is_in_force": bool(is_in_force),
                    "snapshot_date": on_date,
                })
        self._log.debug("[DB] snapshot doc=%s date=%s provisions=%d", document_id, on_date, len(results))
        return results

    # ─────────────────────────────────────────────────────────────────
    # Corpus index (remplace _CORPUS_REGISTRY dict)
    # ─────────────────────────────────────────────────────────────────

    def index_corpus_entry(
        self,
        juslib_id: str,
        text_excerpt: str,
        source_url: str,
        *,
        raw_source_hash: Optional[str] = None,
        corpus_version: Optional[str] = None,
    ) -> None:
        """
        Indexe une entrée dans le corpus (remplace _CORPUS_REGISTRY).
        canonical_content_hash calculé automatiquement.
        """
        canonical_hash = _compute_canonical_hash(text_excerpt)
        with self.conn() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO corpus_entries (
                    juslib_id, text_excerpt, raw_source_hash, canonical_content_hash,
                    source_url, corpus_version
                ) VALUES (?,?,?,?,?,?)
                """,
                (juslib_id, text_excerpt, raw_source_hash, canonical_hash,
                 source_url, corpus_version),
            )
        self._log.debug("[DB] corpus_entry indexed id=%s", juslib_id)

    def get_corpus_entry(self, juslib_id: str) -> Optional[dict[str, Any]]:
        """Récupère une entrée du corpus par son identifiant JUSLIB."""
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM corpus_entries WHERE juslib_id = ?", (juslib_id,)
            ).fetchone()
        return dict(row) if row else None

    def verify_corpus_entry_integrity(self, juslib_id: str) -> tuple[bool, list[str]]:
        """
        Vérifie l'intégrité d'une entrée corpus.
        Recalcule canonical_content_hash sans effet de bord (R003-P0-B).
        """
        entry = self.get_corpus_entry(juslib_id)
        errors: list[str] = []
        if not entry:
            return False, [f"Entrée '{juslib_id}' non trouvée dans le corpus"]
        stored = entry.get("canonical_content_hash", "")
        if not stored:
            errors.append("canonical_content_hash absent — intégrité non vérifiable")
        else:
            computed = _compute_canonical_hash(entry["text_excerpt"])
            if computed != stored:
                errors.append(
                    f"canonical_content_hash incohérent — "
                    f"stocké={stored[:12]}… calculé={computed[:12]}…"
                )
        return len(errors) == 0, errors

    # ─────────────────────────────────────────────────────────────────
    # Relations et preuves
    # ─────────────────────────────────────────────────────────────────

    def insert_relation_evidence(
        self,
        relation_type: str,
        source_id: str,
        target_id: str,
        evidence_url: str,
        *,
        evidence_text: Optional[str] = None,
        confidence: float = 0.0,
        certainty_level: str = "unverified",
        production_type: str = "rule_based",
    ) -> str:
        """Insère une preuve de relation juridique. Retourne l'evidence_id."""
        evidence_id = str(uuid.uuid4())
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO relation_evidence (
                    evidence_id, relation_type, source_id, target_id,
                    evidence_text, evidence_url, confidence, certainty_level, production_type
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (evidence_id, relation_type, source_id, target_id,
                 evidence_text, evidence_url, confidence, certainty_level, production_type),
            )
        return evidence_id

    # ─────────────────────────────────────────────────────────────────
    # Traductions
    # ─────────────────────────────────────────────────────────────────

    def insert_translation(
        self,
        version_id: str,
        source_language: str,
        target_language: str,
        translated_text: str,
        *,
        translation_type: str = "official",
        source_url: Optional[str] = None,
        translator: Optional[str] = None,
        certainty_level: str = "unverified",
    ) -> str:
        """Insère une traduction vérifiée. Retourne le translation_id."""
        translation_id = str(uuid.uuid4())
        canonical_hash = _compute_canonical_hash(translated_text)
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO translation_records (
                    translation_id, version_id, source_language, target_language,
                    translated_text, translation_type, source_url, translator,
                    canonical_hash, certainty_level
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (translation_id, version_id, source_language, target_language,
                 translated_text, translation_type, source_url, translator,
                 canonical_hash, certainty_level),
            )
        return translation_id

    # ─────────────────────────────────────────────────────────────────
    # Statistiques
    # ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Retourne des statistiques sur le contenu de la DB."""
        with self.conn() as con:
            return {
                "documents": con.execute("SELECT COUNT(*) FROM legal_documents").fetchone()[0],
                "provisions": con.execute("SELECT COUNT(*) FROM legal_provisions").fetchone()[0],
                "versions": con.execute("SELECT COUNT(*) FROM legal_versions").fetchone()[0],
                "snapshots": con.execute("SELECT COUNT(*) FROM legal_snapshots").fetchone()[0],
                "relation_evidence": con.execute("SELECT COUNT(*) FROM relation_evidence").fetchone()[0],
                "translations": con.execute("SELECT COUNT(*) FROM translation_records").fetchone()[0],
                "corpus_entries": con.execute("SELECT COUNT(*) FROM corpus_entries").fetchone()[0],
                "authorities": con.execute("SELECT COUNT(*) FROM authorities").fetchone()[0],
                "db_path": self._path,
                "insert_only_enforced": True,
                "foreign_keys_enabled": True,
            }
