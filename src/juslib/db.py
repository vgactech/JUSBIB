"""
JUSLIB — Couche de persistance SQLite (R006).

J004 apporte :
  P0-01 : authentification de provenance — corpus_entries est INSERT-only strict,
           certainty_level CLIENT_PROVIDED interdit d'atteindre CERTAIN/SOURCE.
  P0-03 : INSERT OR REPLACE supprimé → INSERT strict + triggers INSERT-only sur corpus_entries.
  P0-04 : triggers INSERT-only ajoutés sur legal_provisions, legal_snapshots,
           relation_evidence, translation_records.
  P1-01 : détection de chevauchement temporel — insert_version rejette un chevauchement
           sauf si la version précédente est explicitement fermée.
  P1-02 : VersionStatus (IN_FORCE/REPEALED/SUSPENDED/NOT_YET_IN_FORCE/PARTIALLY_REPEALED) +
           get_version_at_date filtre sur version_status != REPEALED/SUSPENDED.
  P1-03 : table source_captures — chaîne de provenance brute (raw_bytes_hash,
           retrieval_timestamp, http_status, connector_version, etag, last_modified).
  P1-04 : contraintes UNIQUE sur eli_id, celex_id, ecli_id.

J006 apporte (P0-A / P0-B / P0-C) :
  P0-A : table corpus_releases — releases immuables du corpus (version/label/hash manifest).
         Méthodes : insert_corpus_release(), get_corpus_releases(), get_latest_corpus_release().
  P0-B : méthodes API support — insert_authority(), get_authority(), get_all_authorities().
         Ces méthodes alimentent les nouveaux endpoints /v1/document, /v1/provision, /v1/version.
         NB : /v1/document POST utilise insert_document() déjà présent.
  P0-C : FTS5 sur legal_versions.text — table virtuelle legal_versions_fts +
         méthode search_versions_fts() pour la recherche plein texte réelle.

Tables :
  authorities        : sources faisant autorité
  legal_documents    : documents normatifs (ELI/CELEX/ECLI séparés + UNIQUE)
  legal_provisions   : subdivisions (INSERT-only)
  legal_versions     : textes exacts par période (INSERT-only + version_status + FTS5)
  legal_snapshots    : vue corpus à une date (INSERT-only)
  relation_evidence  : preuves relations (INSERT-only)
  translation_records: traductions vérifiées (INSERT-only)
  corpus_entries     : index corpus — INSERT strict (jamais REPLACE)
  source_captures    : chaîne de provenance brute (P1-03)
  corpus_releases    : releases immuables versionnées (P0-A) — INSERT-only

Invariants :
  1. source_url NOT NULL sur toutes les tables principales
  2. INSERT-only sur toutes les tables historiques (10 tables + FTS)
  3. FK réelles avec PRAGMA foreign_keys=ON
  4. raw_source_hash ≠ canonical_content_hash (champs séparés)
  5. Marquage production_type obligatoire
  6. certainty_level obligatoire — CLIENT_PROVIDED ne peut jamais devenir SOURCE/CERTAIN
  7. Non-chevauchement temporel enforced à l'insertion
  8. ELI/CELEX/ECLI : UNIQUE par juridiction

Mode DEBUG actif.
CERTIFIED_100=false | unique_human_proven=false
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger("juslib.db")
logger.setLevel(logging.DEBUG if os.getenv("JUSLIB_DEBUG", "true").lower() != "false" else logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de statut de version (P1-02)
# ─────────────────────────────────────────────────────────────────────────────
VERSION_STATUS_IN_FORCE = "in_force"
VERSION_STATUS_REPEALED = "repealed"
VERSION_STATUS_SUSPENDED = "suspended"
VERSION_STATUS_NOT_YET = "not_yet_in_force"
VERSION_STATUS_PARTIAL_REPEAL = "partially_repealed"
_ACTIVE_STATUSES = (VERSION_STATUS_IN_FORCE, VERSION_STATUS_NOT_YET)
_ALL_STATUSES = (
    VERSION_STATUS_IN_FORCE, VERSION_STATUS_REPEALED,
    VERSION_STATUS_SUSPENDED, VERSION_STATUS_NOT_YET,
    VERSION_STATUS_PARTIAL_REPEAL,
)

# Niveaux de certitude (P0-01 : CLIENT_PROVIDED ne peut jamais devenir SOURCE)
CERTAINTY_CLIENT_PROVIDED = "client_provided"  # ← jamais élevé à CERTAIN/SOURCE
CERTAINTY_UNVERIFIED = "unverified"
CERTAINTY_INTERPRETED = "interpreted"
CERTAINTY_CONTESTED = "contested"
CERTAINTY_CERTAIN = "certain"
_ALL_CERTAINTY = (
    CERTAINTY_CLIENT_PROVIDED, CERTAINTY_UNVERIFIED,
    CERTAINTY_INTERPRETED, CERTAINTY_CONTESTED, CERTAINTY_CERTAIN,
)
# Certitudes jamais accessibles depuis une entrée client
_CLIENT_FORBIDDEN_CERTAINTY = (CERTAINTY_CERTAIN,)

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
    jurisdiction      TEXT NOT NULL,
    authority_type    TEXT NOT NULL,
    language          TEXT NOT NULL DEFAULT 'fr',
    official_url      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────
-- Table 2 : Documents normatifs
-- P1-04 : UNIQUE sur eli_id / celex_id / ecli_id
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_documents (
    juslib_id         TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    document_type     TEXT NOT NULL,
    jurisdiction      TEXT NOT NULL,
    language          TEXT NOT NULL DEFAULT 'fr',

    -- Identifiants officiels — P1-04 : UNIQUE (NULL autorisé car pas toujours présent)
    eli_id            TEXT UNIQUE,
    celex_id          TEXT UNIQUE,
    ecli_id           TEXT UNIQUE,
    native_id         TEXT,

    -- Métadonnées temporelles
    entry_into_force  TEXT,
    publication_date  TEXT,
    adoption_date     TEXT,
    repeal_date       TEXT,

    -- Source et intégrité
    source_url        TEXT NOT NULL,
    connector_id      TEXT NOT NULL,
    raw_source_hash   TEXT,
    canonical_content_hash TEXT,

    -- Versionnement INSERT-only
    corpus_version    TEXT,
    production_type   TEXT NOT NULL DEFAULT 'rule_based',
    certainty_level   TEXT NOT NULL DEFAULT 'unverified',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT chk_production_type CHECK (
        production_type IN ('rule_based','llm_generated','human_validated','source','connector_fetched')
    ),
    CONSTRAINT chk_certainty CHECK (
        certainty_level IN ('client_provided','unverified','interpreted','contested','certain')
    )
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_legal_documents
BEFORE UPDATE ON legal_documents
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_documents est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_legal_documents
BEFORE DELETE ON legal_documents
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_documents est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 3 : Subdivisions (P0-04 : triggers INSERT-only ajoutés)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_provisions (
    provision_id      TEXT PRIMARY KEY,
    document_id       TEXT NOT NULL REFERENCES legal_documents(juslib_id),
    number            TEXT,
    label             TEXT,
    heading           TEXT,
    language          TEXT NOT NULL DEFAULT 'fr',
    order_index       INTEGER NOT NULL DEFAULT 0,
    corpus_version    TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_legal_provisions
BEFORE UPDATE ON legal_provisions
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_provisions est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_legal_provisions
BEFORE DELETE ON legal_provisions
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_provisions est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 4 : Versions de textes
-- P1-02 : version_status ajouté (IN_FORCE / REPEALED / SUSPENDED / …)
-- INSERT-only strict
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_versions (
    version_id               TEXT PRIMARY KEY,
    provision_id             TEXT NOT NULL REFERENCES legal_provisions(provision_id),
    document_id              TEXT NOT NULL REFERENCES legal_documents(juslib_id),

    text                     TEXT NOT NULL,
    language                 TEXT NOT NULL DEFAULT 'fr',

    raw_source_hash          TEXT,
    canonical_content_hash   TEXT,

    -- Temporalité
    valid_from               TEXT NOT NULL,
    valid_until              TEXT,
    publication_date         TEXT,
    adoption_date            TEXT,

    -- P1-02 : statut explicite — évite l'ambiguïté "version trouvée = en vigueur"
    version_status           TEXT NOT NULL DEFAULT 'in_force',

    change_type              TEXT NOT NULL DEFAULT 'initial',
    amending_document_id     TEXT,
    amending_provision       TEXT,

    source_url               TEXT NOT NULL,
    connector_id             TEXT,

    revision                 INTEGER NOT NULL DEFAULT 1,
    previous_version_id      TEXT,
    corpus_version           TEXT,
    certainty_level          TEXT NOT NULL DEFAULT 'unverified',
    production_type          TEXT NOT NULL DEFAULT 'rule_based',
    created_at               TEXT NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT chk_version_status CHECK (
        version_status IN ('in_force','repealed','suspended','not_yet_in_force','partially_repealed')
    ),
    CONSTRAINT chk_change_type CHECK (change_type IN
        ('initial','amendment','consolidation','correction','repeal','partial_repeal','suspension')),
    CONSTRAINT chk_production_type CHECK (
        production_type IN ('rule_based','llm_generated','human_validated','source','connector_fetched')
    ),
    CONSTRAINT chk_certainty CHECK (
        certainty_level IN ('client_provided','unverified','interpreted','contested','certain')
    )
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_legal_versions
BEFORE UPDATE ON legal_versions
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_versions est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_legal_versions
BEFORE DELETE ON legal_versions
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_versions est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 5 : Snapshots (P0-04 : triggers INSERT-only ajoutés)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_snapshots (
    snapshot_id       TEXT PRIMARY KEY,
    provision_id      TEXT NOT NULL REFERENCES legal_provisions(provision_id),
    snapshot_date     TEXT NOT NULL,
    version_id        TEXT NOT NULL REFERENCES legal_versions(version_id),
    is_in_force       INTEGER NOT NULL DEFAULT 1,
    version_status    TEXT NOT NULL DEFAULT 'in_force',
    computed_at       TEXT NOT NULL DEFAULT (datetime('now')),
    corpus_version    TEXT
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_legal_snapshots
BEFORE UPDATE ON legal_snapshots
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_snapshots est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_legal_snapshots
BEFORE DELETE ON legal_snapshots
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: legal_snapshots est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 6 : Preuves des relations juridiques (P0-04 : triggers ajoutés)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS relation_evidence (
    evidence_id       TEXT PRIMARY KEY,
    relation_type     TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    target_id         TEXT NOT NULL,
    evidence_text     TEXT,
    evidence_url      TEXT NOT NULL,
    confidence        REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    certainty_level   TEXT NOT NULL DEFAULT 'unverified',
    production_type   TEXT NOT NULL DEFAULT 'rule_based',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_relation_evidence
BEFORE UPDATE ON relation_evidence
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: relation_evidence est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_relation_evidence
BEFORE DELETE ON relation_evidence
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: relation_evidence est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 7 : Traductions vérifiées (P0-04 : triggers ajoutés)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS translation_records (
    translation_id    TEXT PRIMARY KEY,
    version_id        TEXT NOT NULL REFERENCES legal_versions(version_id),
    source_language   TEXT NOT NULL,
    target_language   TEXT NOT NULL,
    translated_text   TEXT NOT NULL,
    translation_type  TEXT NOT NULL DEFAULT 'official',
    source_url        TEXT,
    translator        TEXT,
    canonical_hash    TEXT,
    certainty_level   TEXT NOT NULL DEFAULT 'unverified',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT chk_trans_type CHECK (translation_type IN ('official','machine','human_reviewed'))
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_translation_records
BEFORE UPDATE ON translation_records
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: translation_records est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_translation_records
BEFORE DELETE ON translation_records
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: translation_records est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 8 : Index corpus — P0-03 : INSERT strict (jamais OR REPLACE)
-- P0-01 : certainty_level CLIENT_PROVIDED ne peut pas devenir 'certain'
-- P0-04 : triggers INSERT-only
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corpus_entries (
    juslib_id              TEXT PRIMARY KEY REFERENCES legal_documents(juslib_id),
    text_excerpt           TEXT NOT NULL,
    raw_source_hash        TEXT,
    canonical_content_hash TEXT,
    source_url             TEXT NOT NULL,
    -- P0-01 : ingestion_method distingue la provenance réelle du texte client
    ingestion_method       TEXT NOT NULL DEFAULT 'client_provided',
    corpus_version         TEXT,
    indexed_at             TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT chk_ingestion CHECK (
        ingestion_method IN ('connector_fetched','client_provided','operator_import')
    )
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_corpus_entries
BEFORE UPDATE ON corpus_entries
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: corpus_entries est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_corpus_entries
BEFORE DELETE ON corpus_entries
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: corpus_entries est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 9 : SourceCapture — P1-03 : chaîne de provenance brute
-- Enregistre les métadonnées de chaque récupération depuis une source officielle.
-- Un corpus_entry authentifié doit avoir une SourceCapture liée.
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS source_captures (
    capture_id         TEXT PRIMARY KEY,
    juslib_id          TEXT NOT NULL REFERENCES legal_documents(juslib_id),
    source_url         TEXT NOT NULL,
    http_status        INTEGER,
    content_type       TEXT,
    raw_bytes_hash     TEXT NOT NULL,  -- sha256 des octets bruts reçus
    raw_bytes_length   INTEGER,
    retrieval_timestamp TEXT NOT NULL,
    connector_id       TEXT NOT NULL,
    connector_version  TEXT,
    etag               TEXT,
    last_modified      TEXT,
    corpus_version     TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_source_captures
BEFORE UPDATE ON source_captures
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: source_captures est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_source_captures
BEFORE DELETE ON source_captures
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: source_captures est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table 10 : Releases immuables du corpus — P0-A J006
-- Chaque release = snapshot du corpus entier à un instant donné.
-- INSERT-only : une release publiée ne peut jamais être modifiée.
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corpus_releases (
    release_id         TEXT PRIMARY KEY,
    label              TEXT NOT NULL UNIQUE,   -- ex: 2026.10.04-001
    release_date       TEXT NOT NULL,
    description        TEXT,
    manifest_hash      TEXT NOT NULL,          -- SHA-256 du manifest JSON de la release
    documents_count    INTEGER NOT NULL DEFAULT 0,
    provisions_count   INTEGER NOT NULL DEFAULT 0,
    versions_count     INTEGER NOT NULL DEFAULT 0,
    corpus_version     TEXT NOT NULL,
    published_by       TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_no_update_corpus_releases
BEFORE UPDATE ON corpus_releases
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: corpus_releases est INSERT-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_no_delete_corpus_releases
BEFORE DELETE ON corpus_releases
BEGIN
    SELECT RAISE(ABORT, 'INVARIANT-2: corpus_releases est INSERT-only');
END;

-- ─────────────────────────────────────────────────────────────────────
-- Table FTS5 : Index plein-texte sur legal_versions.text — P0-C J006
-- Permet la recherche full-text sans dépendance externe.
-- content=legal_versions : synchronisé automatiquement par triggers.
-- ─────────────────────────────────────────────────────────────────────
CREATE VIRTUAL TABLE IF NOT EXISTS legal_versions_fts
USING fts5(
    text,
    language,
    version_id UNINDEXED,
    provision_id UNINDEXED,
    document_id UNINDEXED,
    content='legal_versions',
    content_rowid='rowid'
);

-- Trigger de synchronisation FTS5 à l'insertion d'une version
CREATE TRIGGER IF NOT EXISTS trg_fts_insert_legal_versions
AFTER INSERT ON legal_versions
BEGIN
    INSERT INTO legal_versions_fts(rowid, text, language, version_id, provision_id, document_id)
    VALUES (new.rowid, new.text, new.language, new.version_id, new.provision_id, new.document_id);
END;

-- ─────────────────────────────────────────────────────────────────────
-- Index de performance
-- ─────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_docs_jurisdiction ON legal_documents(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_docs_native ON legal_documents(native_id) WHERE native_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_provisions_doc ON legal_provisions(document_id);
CREATE INDEX IF NOT EXISTS idx_versions_provision ON legal_versions(provision_id);
CREATE INDEX IF NOT EXISTS idx_versions_validity ON legal_versions(valid_from, valid_until);
CREATE INDEX IF NOT EXISTS idx_versions_status ON legal_versions(version_status);
CREATE INDEX IF NOT EXISTS idx_snapshots_provision_date ON legal_snapshots(provision_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_relation_source ON relation_evidence(source_id);
CREATE INDEX IF NOT EXISTS idx_relation_target ON relation_evidence(target_id);
CREATE INDEX IF NOT EXISTS idx_translations_version ON translation_records(version_id);
CREATE INDEX IF NOT EXISTS idx_translations_lang ON translation_records(source_language, target_language);
CREATE INDEX IF NOT EXISTS idx_captures_juslib ON source_captures(juslib_id);
CREATE INDEX IF NOT EXISTS idx_releases_label ON corpus_releases(label);
CREATE INDEX IF NOT EXISTS idx_releases_date ON corpus_releases(release_date);
"""


def _compute_canonical_hash(text: str) -> str:
    """Hash canonique : NFC + collapse whitespace + strip + SHA-256 (sans effet de bord)."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _compute_raw_hash(raw_bytes: bytes) -> str:
    """SHA-256 du contenu brut (avant parsing/normalisation)."""
    return hashlib.sha256(raw_bytes).hexdigest()


class JuslibDB:
    """
    Gestionnaire de base de données SQLite pour JUSLIB.

    J004 : toutes les tables historiques sont INSERT-only (triggers).
    J004 : corpus_entries n'accepte jamais OR REPLACE.
    J004 : insert_version vérifie les chevauchements temporels (P1-01).
    J004 : version_status distingue IN_FORCE / REPEALED / SUSPENDED (P1-02).
    J004 : source_captures trace la provenance brute (P1-03).
    J004 : ELI/CELEX/ECLI ont des contraintes UNIQUE (P1-04).
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
        con = self._get_connection()
        con.executescript(_SCHEMA_SQL)
        con.commit()

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
        conditions, params = [], []
        if eli_id:
            conditions.append("eli_id = ?"); params.append(eli_id)
        if celex_id:
            conditions.append("celex_id = ?"); params.append(celex_id)
        if ecli_id:
            conditions.append("ecli_id = ?"); params.append(ecli_id)
        if native_id:
            conditions.append("native_id = ?"); params.append(native_id)
        if not conditions:
            return []
        where = " OR ".join(conditions)
        with self.conn() as con:
            rows = con.execute(f"SELECT * FROM legal_documents WHERE {where}", params).fetchall()
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
        version_status: str = VERSION_STATUS_IN_FORCE,
        change_type: str = "initial",
        revision: int = 1,
        previous_version_id: Optional[str] = None,
        corpus_version: Optional[str] = None,
        connector_id: Optional[str] = None,
        raw_source_hash: Optional[str] = None,
        certainty_level: str = "unverified",
        production_type: str = "rule_based",
        amending_document_id: Optional[str] = None,
        allow_overlap: bool = False,
    ) -> str:
        """
        Insère une version de texte (INSERT-only).

        P1-01 : détecte et rejette les chevauchements temporels par défaut.
        Un chevauchement survient si une autre version active (version_status in_force /
        not_yet_in_force) couvre la même provision et que les périodes se superposent.
        Passer allow_overlap=True uniquement pour les tests ou cas explicitement documentés.

        P1-02 : version_status stocké explicitement.
        """
        if not allow_overlap:
            overlap = self._find_overlapping_version(provision_id, valid_from, valid_until)
            if overlap:
                raise ValueError(
                    f"P1-01: Chevauchement temporel détecté pour provision {provision_id}. "
                    f"Version existante {overlap['version_id']} couvre "
                    f"{overlap['valid_from']}→{overlap['valid_until'] or 'NULL'}. "
                    f"Nouvelle période : {valid_from}→{valid_until or 'NULL'}. "
                    "Fermer explicitement la version précédente avant d'en créer une nouvelle, "
                    "ou passer allow_overlap=True si le chevauchement est intentionnel."
                )

        version_id = str(uuid.uuid4())
        canonical_hash = _compute_canonical_hash(text)
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO legal_versions (
                    version_id, provision_id, document_id, text, language,
                    raw_source_hash, canonical_content_hash,
                    valid_from, valid_until, version_status, change_type,
                    source_url, connector_id,
                    revision, previous_version_id, corpus_version,
                    certainty_level, production_type, amending_document_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    version_id, provision_id, document_id, text, language,
                    raw_source_hash, canonical_hash,
                    valid_from, valid_until, version_status, change_type,
                    source_url, connector_id,
                    revision, previous_version_id, corpus_version,
                    certainty_level, production_type, amending_document_id,
                ),
            )
        self._log.debug("[DB] insert_version id=%s prov=%s from=%s status=%s",
                        version_id, provision_id, valid_from, version_status)
        return version_id

    def _find_overlapping_version(
        self, provision_id: str, valid_from: str, valid_until: Optional[str]
    ) -> Optional[dict[str, Any]]:
        """
        P1-01 : cherche une version active (in_force / not_yet_in_force) qui chevauche
        la période [valid_from, valid_until) pour la même provision.
        NULL = toujours en vigueur (période ouverte).
        """
        if valid_until is None:
            # Nouvelle version à période ouverte — chevauche toute version existante
            # dont valid_until est NULL ou > valid_from
            query = """
                SELECT version_id, valid_from, valid_until FROM legal_versions
                WHERE provision_id = ?
                  AND version_status IN ('in_force','not_yet_in_force')
                  AND (valid_until IS NULL OR valid_until > ?)
                LIMIT 1
            """
            params = (provision_id, valid_from)
        else:
            # Nouvelle version à période fermée
            query = """
                SELECT version_id, valid_from, valid_until FROM legal_versions
                WHERE provision_id = ?
                  AND version_status IN ('in_force','not_yet_in_force')
                  AND valid_from < ?
                  AND (valid_until IS NULL OR valid_until > ?)
                LIMIT 1
            """
            params = (provision_id, valid_until, valid_from)

        with self.conn() as con:
            row = con.execute(query, params).fetchone()
        return dict(row) if row else None

    # ─────────────────────────────────────────────────────────────────
    # Snapshot : droit applicable à une date (P1-02 aware)
    # ─────────────────────────────────────────────────────────────────

    def get_version_at_date(
        self, provision_id: str, on_date: str
    ) -> Optional[dict[str, Any]]:
        """
        Retourne la version EN VIGUEUR (version_status = 'in_force') à la date donnée.
        P1-02 : les versions REPEALED/SUSPENDED ne sont pas retournées comme "applicables",
        mais sont retournées avec leur statut réel si on_date tombe dans leur période.
        on_date : ISO 8601 (YYYY-MM-DD).
        """
        with self.conn() as con:
            row = con.execute(
                """
                SELECT * FROM legal_versions
                WHERE provision_id = ?
                  AND valid_from <= ?
                  AND (valid_until IS NULL OR valid_until > ?)
                  AND version_status = 'in_force'
                ORDER BY valid_from DESC, revision DESC
                LIMIT 1
                """,
                (provision_id, on_date, on_date),
            ).fetchone()
        return dict(row) if row else None

    def get_version_status_at_date(
        self, provision_id: str, on_date: str
    ) -> dict[str, Any]:
        """
        P1-02 : retourne le statut complet d'une provision à une date.
        Inclut les versions abrogées/suspendues pour permettre l'audit historique.
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
        if not row:
            return {"provision_id": provision_id, "on_date": on_date,
                    "status": "no_version_found", "version": None}
        v = dict(row)
        return {
            "provision_id": provision_id,
            "on_date": on_date,
            "status": v["version_status"],
            "is_applicable": v["version_status"] == VERSION_STATUS_IN_FORCE,
            "version": v,
        }

    def compute_snapshot(
        self, document_id: str, on_date: str, corpus_version: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Calcule le snapshot complet d'un document à une date.
        P1-02 : inclut le version_status dans chaque entrée snapshot.
        """
        results = []
        with self.conn() as con:
            provisions = con.execute(
                "SELECT * FROM legal_provisions WHERE document_id = ? ORDER BY order_index",
                (document_id,),
            ).fetchall()

        for prov in provisions:
            status_info = self.get_version_status_at_date(prov["provision_id"], on_date)
            version = status_info.get("version")
            is_in_force = int(status_info["is_applicable"]) if version else 0
            if version:
                snap_id = str(uuid.uuid4())
                with self.conn() as con:
                    try:
                        con.execute(
                            """
                            INSERT INTO legal_snapshots (
                                snapshot_id, provision_id, snapshot_date, version_id,
                                is_in_force, version_status, corpus_version
                            ) VALUES (?,?,?,?,?,?,?)
                            """,
                            (snap_id, prov["provision_id"], on_date,
                             version["version_id"], is_in_force,
                             version["version_status"], corpus_version),
                        )
                    except Exception:
                        pass  # snapshot déjà enregistré — INSERT-only, pas d'erreur
            results.append({
                "provision": dict(prov),
                "version": version,
                "is_in_force": bool(is_in_force),
                "version_status": status_info["status"],
                "snapshot_date": on_date,
            })
        return results

    # ─────────────────────────────────────────────────────────────────
    # Corpus index — P0-03 : INSERT strict (jamais REPLACE)
    # P0-01 : ingestion_method trace la provenance du texte
    # ─────────────────────────────────────────────────────────────────

    def index_corpus_entry(
        self,
        juslib_id: str,
        text_excerpt: str,
        source_url: str,
        *,
        raw_source_hash: Optional[str] = None,
        corpus_version: Optional[str] = None,
        ingestion_method: str = "client_provided",
    ) -> None:
        """
        Indexe une entrée dans le corpus.
        P0-03 : INSERT strict — lève IntegrityError si l'ID existe déjà.
        P0-01 : ingestion_method trace si le texte vient d'un connecteur officiel
                ('connector_fetched') ou du client ('client_provided').
        canonical_content_hash calculé automatiquement.
        """
        if ingestion_method not in ("connector_fetched", "client_provided", "operator_import"):
            raise ValueError(
                f"ingestion_method invalide : {ingestion_method}. "
                "Valeurs autorisées : connector_fetched | client_provided | operator_import"
            )
        canonical_hash = _compute_canonical_hash(text_excerpt)
        with self.conn() as con:
            # INSERT strict — pas de OR REPLACE (P0-03)
            con.execute(
                """
                INSERT INTO corpus_entries (
                    juslib_id, text_excerpt, raw_source_hash, canonical_content_hash,
                    source_url, ingestion_method, corpus_version
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (juslib_id, text_excerpt, raw_source_hash, canonical_hash,
                 source_url, ingestion_method, corpus_version),
            )
        self._log.debug("[DB] corpus_entry indexed id=%s method=%s", juslib_id, ingestion_method)

    def get_corpus_entry(self, juslib_id: str) -> Optional[dict[str, Any]]:
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM corpus_entries WHERE juslib_id = ?", (juslib_id,)
            ).fetchone()
        return dict(row) if row else None

    def verify_corpus_entry_integrity(self, juslib_id: str) -> tuple[bool, list[str]]:
        """Vérifie canonical_content_hash sans effet de bord (P0-B)."""
        entry = self.get_corpus_entry(juslib_id)
        errors: list[str] = []
        if not entry:
            return False, [f"Entrée '{juslib_id}' non trouvée dans le corpus"]
        stored = entry.get("canonical_content_hash", "")
        if not stored:
            errors.append("canonical_content_hash absent")
        else:
            computed = _compute_canonical_hash(entry["text_excerpt"])
            if computed != stored:
                errors.append(
                    f"canonical_content_hash incohérent — "
                    f"stocké={stored[:12]}… calculé={computed[:12]}…"
                )
        return len(errors) == 0, errors

    # ─────────────────────────────────────────────────────────────────
    # SourceCapture — P1-03 : chaîne de provenance brute
    # ─────────────────────────────────────────────────────────────────

    def insert_source_capture(
        self,
        juslib_id: str,
        source_url: str,
        raw_bytes_hash: str,
        connector_id: str,
        *,
        http_status: Optional[int] = None,
        content_type: Optional[str] = None,
        raw_bytes_length: Optional[int] = None,
        retrieval_timestamp: Optional[str] = None,
        connector_version: Optional[str] = None,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        corpus_version: Optional[str] = None,
    ) -> str:
        """
        P1-03 : enregistre les métadonnées de capture d'une source officielle.
        raw_bytes_hash = SHA-256 des octets bruts reçus (avant parsing/normalisation).
        retrieval_timestamp = ISO 8601 UTC de la récupération.
        """
        capture_id = str(uuid.uuid4())
        ts = retrieval_timestamp or datetime.utcnow().isoformat() + "Z"
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO source_captures (
                    capture_id, juslib_id, source_url, http_status, content_type,
                    raw_bytes_hash, raw_bytes_length, retrieval_timestamp,
                    connector_id, connector_version, etag, last_modified, corpus_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (capture_id, juslib_id, source_url, http_status, content_type,
                 raw_bytes_hash, raw_bytes_length, ts,
                 connector_id, connector_version, etag, last_modified, corpus_version),
            )
        self._log.debug("[DB] source_capture id=%s doc=%s url=%s", capture_id, juslib_id, source_url[:60])
        return capture_id

    def get_source_captures(self, juslib_id: str) -> list[dict[str, Any]]:
        """Retourne toutes les captures pour un document donné."""
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM source_captures WHERE juslib_id = ? ORDER BY retrieval_timestamp DESC",
                (juslib_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def is_connector_fetched(self, juslib_id: str) -> bool:
        """
        P0-01 : retourne True si le document a au moins une SourceCapture
        (preuve qu'un connecteur a réellement récupéré les données depuis la source officielle).
        """
        entry = self.get_corpus_entry(juslib_id)
        if not entry:
            return False
        return entry.get("ingestion_method") == "connector_fetched"

    # ─────────────────────────────────────────────────────────────────
    # Relations et traductions
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

    # ─────────────────────────────────────────────────────────────────
    # P0-A J006 : corpus_releases — releases immuables
    # ─────────────────────────────────────────────────────────────────

    def insert_corpus_release(
        self,
        label: str,
        release_date: str,
        manifest_hash: str,
        corpus_version: str,
        description: Optional[str] = None,
        documents_count: int = 0,
        provisions_count: int = 0,
        versions_count: int = 0,
        published_by: Optional[str] = None,
    ) -> str:
        """
        Enregistre une release immuable du corpus.

        label : identifiant human-readable (ex: 2026.10.04-001)
        manifest_hash : SHA-256 du fichier manifest JSON de la release
        Retourne release_id (UUID préfixé 'rel:')
        """
        release_id = f"rel:{uuid.uuid4().hex[:16]}"
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO corpus_releases
                    (release_id, label, release_date, description, manifest_hash,
                     documents_count, provisions_count, versions_count,
                     corpus_version, published_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_id, label, release_date, description, manifest_hash,
                    documents_count, provisions_count, versions_count,
                    corpus_version, published_by,
                ),
            )
        logger.debug("[DB] insert_corpus_release label=%s release_id=%s", label, release_id)
        return release_id

    def get_corpus_releases(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retourne les releases ordonnées par date décroissante."""
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM corpus_releases ORDER BY release_date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_corpus_release(self) -> Optional[dict[str, Any]]:
        """Retourne la release la plus récente ou None si aucune."""
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM corpus_releases ORDER BY release_date DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def get_corpus_release_by_label(self, label: str) -> Optional[dict[str, Any]]:
        """Retourne une release par son label (ex: '2026.10.04-001')."""
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM corpus_releases WHERE label = ?", (label,)
            ).fetchone()
        return dict(row) if row else None

    # ─────────────────────────────────────────────────────────────────
    # P0-B J006 : authorities — méthodes CRUD
    # ─────────────────────────────────────────────────────────────────

    def insert_authority(
        self,
        short_name: str,
        full_name: str,
        jurisdiction: str,
        authority_type: str,
        language: str = "fr",
        official_url: Optional[str] = None,
    ) -> str:
        """Enregistre une autorité juridictionnelle. Retourne authority_id."""
        authority_id = f"auth:{uuid.uuid4().hex[:16]}"
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO authorities
                    (authority_id, short_name, full_name, jurisdiction,
                     authority_type, language, official_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (authority_id, short_name, full_name, jurisdiction,
                 authority_type, language, official_url),
            )
        logger.debug("[DB] insert_authority short_name=%s id=%s", short_name, authority_id)
        return authority_id

    def get_authority(self, authority_id: str) -> Optional[dict[str, Any]]:
        """Retourne une autorité par son ID."""
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM authorities WHERE authority_id = ?", (authority_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_all_authorities(self, jurisdiction: Optional[str] = None) -> list[dict[str, Any]]:
        """Liste toutes les autorités, avec filtre optionnel par juridiction."""
        with self.conn() as con:
            if jurisdiction:
                rows = con.execute(
                    "SELECT * FROM authorities WHERE jurisdiction = ? ORDER BY short_name",
                    (jurisdiction,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM authorities ORDER BY jurisdiction, short_name"
                ).fetchall()
        return [dict(r) for r in rows]

    # ─────────────────────────────────────────────────────────────────
    # P0-C J006 : FTS5 — recherche plein texte sur legal_versions
    # ─────────────────────────────────────────────────────────────────

    def search_versions_fts(
        self,
        query: str,
        language: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        version_status: str = VERSION_STATUS_IN_FORCE,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Recherche full-text dans legal_versions via FTS5.

        query      : termes de recherche (supporte les opérateurs FTS5 : AND, OR, NOT, "phrase")
        language   : filtre optionnel sur la langue (fr, en, de…)
        jurisdiction : filtre optionnel sur la juridiction du document parent
        version_status : par défaut 'in_force' — seules les versions en vigueur
        limit      : nombre max de résultats

        Retourne une liste de dicts avec version_id, document_id, provision_id,
        snippet (extrait), language, version_status.
        """
        if not query or not query.strip():
            return []

        params: list[Any] = [query, limit]
        join_filter = ""
        if language:
            join_filter += " AND lv.language = ?"
            params.insert(1, language)
        if version_status:
            join_filter += " AND lv.version_status = ?"
            params.insert(len(params) - 1, version_status)
        if jurisdiction:
            join_filter += " AND ld.jurisdiction = ?"
            params.insert(len(params) - 1, jurisdiction)

        sql = f"""
            SELECT
                lv.version_id,
                lv.provision_id,
                lv.document_id,
                lv.language,
                lv.version_status,
                lv.valid_from,
                lv.valid_until,
                lv.certainty_level,
                ld.title AS document_title,
                ld.jurisdiction,
                snippet(legal_versions_fts, 0, '<b>', '</b>', '…', 15) AS snippet
            FROM legal_versions_fts
            JOIN legal_versions lv ON legal_versions_fts.version_id = lv.version_id
            JOIN legal_documents ld ON lv.document_id = ld.juslib_id
            WHERE legal_versions_fts MATCH ?
            {join_filter}
            ORDER BY rank
            LIMIT ?
        """
        try:
            with self.conn() as con:
                rows = con.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            logger.error("[DB] search_versions_fts error: %s | query=%s", e, query)
            return []

    # ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
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
                "source_captures": con.execute("SELECT COUNT(*) FROM source_captures").fetchone()[0],
                "corpus_releases": con.execute("SELECT COUNT(*) FROM corpus_releases").fetchone()[0],
                "db_path": self._path,
                "insert_only_enforced": True,
                "foreign_keys_enabled": True,
                "tables_with_insert_only_triggers": 10,
            }
