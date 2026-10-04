# R006 — Corrections audit J005/J006 — JUSLIB v0.2.0

**Session :** J006  
**Date :** 2026-10-04  
**SHA HEAD JUSBIB :** (à renseigner après push)  
**Version JUSLIB :** 0.2.0 (bump depuis 0.1.3)  
**Résultat :** ✅ 230/230 PASS — zéro échec  
**CERTIFIED_100 :** false  
**unique_human_proven :** false  
**Mode DEBUG :** actif  

---

## 1. Contexte

L'audit J005 (rapport R005 + audit externe détaillé) avait identifié 18 lacunes P0 bloquant la déclaration MVP.  
La session J006 corrige 8 des points P0 les plus critiques et produit 57 nouveaux tests (blocs AA→AJ).

---

## 2. ⚠️ Note — SHA fictif R439

Le message d'audit entrant citait un commit `076db20a...` inexistant dans `vgactech/JUSBIB.git`.  
Ce SHA appartient à une session externe (ChatGPT). Il n'a pas été intégré. Seul le HEAD réel `058a9c8` sert de base.

---

## 3. Corrections — Avant / Après

### P0-A — Table `corpus_releases` + méthodes CRUD

**Fichier :** `src/juslib/db.py`

| | Avant (v0.1.3) | Après (v0.2.0) |
|---|---|---|
| Table `corpus_releases` | **ABSENTE** | ✅ Présente — 11 colonnes |
| Triggers INSERT-only | — | `trg_no_update_corpus_releases` + `trg_no_delete_corpus_releases` |
| Méthodes | — | `insert_corpus_release()`, `get_corpus_releases()`, `get_latest_corpus_release()`, `get_corpus_release_by_label()` |
| `stats()` | 9 clés sans `corpus_releases` | 11 clés avec `corpus_releases` |
| `tables_with_insert_only_triggers` | 9 | **10** |

**Lignes avant :** *(absentes)*  
**Lignes après (`_SCHEMA_SQL`)** :
```sql
CREATE TABLE IF NOT EXISTS corpus_releases (
    release_id TEXT PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    release_date TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    ...
);
```

---

### P0-B — Méthodes `authorities` + endpoints `/v1/authority`

**Fichier :** `src/juslib/db.py` + `src/juslib/api/main.py`

| | Avant | Après |
|---|---|---|
| `insert_authority()` | **ABSENTE** | ✅ Présente |
| `get_authority()` | **ABSENTE** | ✅ Présente |
| `get_all_authorities()` | **ABSENTE** | ✅ Présente (filtre par jurisdiction) |
| `GET /v1/authority` | **ABSENT** | ✅ Présent |
| `POST /v1/authority` | **ABSENT** | ✅ Présent |

---

### P0-C — FTS5 SQLite + `/v1/search` réel

**Fichier :** `src/juslib/db.py` + `src/juslib/api/main.py`

| | Avant (v0.1.3) | Après (v0.2.0) |
|---|---|---|
| Table FTS5 | **ABSENTE** | ✅ `legal_versions_fts` (content=legal_versions) |
| Trigger sync FTS5 | **ABSENT** | `trg_fts_insert_legal_versions` — auto-indexation à l'insertion |
| `search_versions_fts()` | **ABSENTE** | ✅ Présente — FTS5 MATCH + snippet() + filtres |
| `/v1/search` | `results: []` stub | ✅ résultats FTS5 réels avec snippet |
| `engine` dans réponse | absent | `"sqlite_fts5"` |

**Ligne avant `/v1/search`** :
```python
return {"results": [], "note": "Phase 7 (V0.2)..."}
```
**Ligne après** :
```python
results = _db.search_versions_fts(query=req.query, language=req.language, ...)
return {"results": results, "total": len(results), "engine": "sqlite_fts5"}
```

---

### P0-D — DB persistante par défaut

**Fichier :** `src/juslib/api/main.py`

| | Avant | Après |
|---|---|---|
| DB par défaut | `None → :memory:` (perdue au redémarrage) | `data/juslib.db` (persistante) |
| Override test | non documenté | `JUSLIB_DB_PATH=:memory:` |

**Ligne avant** :
```python
_db = JuslibDB(db_path=os.getenv("JUSLIB_DB_PATH"), ...)  # None → :memory:
```
**Lignes après** :
```python
_DEFAULT_DB_PATH = ...data/juslib.db
_db_path = _db_path_env if _db_path_env is not None else _DEFAULT_DB_PATH
_db = JuslibDB(db_path=_db_path, ...)
```

---

### P0-E — Ingestion transactionnelle atomique

**Fichier :** `src/juslib/api/main.py` — `POST /v1/corpus/ingest`

| | Avant | Après |
|---|---|---|
| Structure | 3 appels DB séquentiels | 1 transaction `with _db.conn() as con:` |
| Atomicité | ❌ document pouvait exister sans capture | ✅ COMMIT ou ROLLBACK complet |
| Réponse | sans `atomic_transaction` | `"atomic_transaction": True` |

**Avant** :
```python
doc_id = _db.insert_document(...)
capture_id = _db.insert_source_capture(...)  # si échoue : doc sans capture
_db.index_corpus_entry(...)
```
**Après** :
```python
with _db.conn() as con:
    con.execute("INSERT INTO legal_documents ...", ...)
    con.execute("INSERT INTO source_captures ...", ...)
    con.execute("INSERT INTO corpus_entries ...", ...)
# → COMMIT automatique ou ROLLBACK si exception
```

---

### P0-F — Endpoints CRUD

**Fichier :** `src/juslib/api/main.py`

| Endpoint | Avant | Après |
|----------|-------|-------|
| `POST /v1/document` | **ABSENT** | ✅ 201 Created |
| `GET /v1/document/{id}` | **ABSENT** | ✅ 200 ou 404 |
| `POST /v1/provision` | **ABSENT** | ✅ 201 Created (vérifie document parent) |
| `POST /v1/version` | **ABSENT** | ✅ 201 + FTS5 auto-indexé |
| `POST /v1/relation` | **ABSENT** | ✅ 201 Created |
| `GET /v1/diff/{from}/{to}` | **ABSENT** | ✅ diff unified_diff déterministe |
| `GET /v1/releases` | partiel (corpus_tracker) | ✅ depuis DB + latest |
| `POST /v1/releases` | **ABSENT** | ✅ 201 Created |

---

### P0-G — Synchronisation version 0.2.0

| Fichier | Avant | Après |
|---------|-------|-------|
| `src/juslib/__init__.py` | `0.1.3` | `0.2.0` |
| `pyproject.toml` | `0.1.0` | `0.2.0` |

---

### P0-H — CI GitHub Actions

**Fichier :** `.github/workflows/ci.yml` (NOUVEAU)

- Push sur `main` → pytest sur Python 3.11 et 3.12
- `JUSLIB_DB_PATH=:memory:` pour les tests CI
- Ruff lint

---

## 4. Résultats des tests

| Fichier | Tests | Résultat |
|---------|-------|----------|
| `test_juslib_core.py` | 69 (blocs A–G) | ✅ 69 PASS |
| `test_juslib_j004.py` | 55 (blocs O–X) | ✅ 55 PASS (R07 mis à jour : 9→10 tables) |
| `test_juslib_j006.py` | 57 (blocs AA–AJ) | ✅ 57 PASS (NOUVEAU) |
| `test_juslib_r003.py` | 49 (blocs H–N) | ✅ 49 PASS |
| **TOTAL** | **230** | **✅ 230 PASS** |

**Durée :** 3.49s  
**Régression :** 0 test cassé par rapport à v0.1.3

---

## 5. Nouveaux tests J006 (blocs AA→AJ)

| Bloc | Thème | Tests |
|------|-------|-------|
| AA | corpus_releases CRUD + INSERT-only | AA01–AA10 |
| AB | authorities CRUD | AB01–AB06 |
| AC | FTS5 recherche full-text | AC01–AC08 |
| AD | DB persistante par défaut | AD01–AD03 |
| AE | Transaction atomique ingest | AE01–AE03 |
| AF | Endpoints CRUD document/provision/version/relation/diff | AF01–AF10 |
| AG | Releases + Authorities via API | AG01–AG05 |
| AH | Sync version 0.2.0 | AH01–AH03 |
| AI | CI GitHub Actions | AI01–AI03 |
| AJ | Non-régression J006 | AJ01–AJ06 |

---

## 6. Scorecard MVP — mise à jour

| # | Critère | Avant J006 | Après J006 |
|---|---------|-----------|-----------|
| C01–C13 | DB, triggers, identifiants, provenance | ✅ | ✅ |
| C14 | Relations entre documents (API) | ⚠️ table seule | ✅ `/v1/relation` |
| C15 | Traductions (API) | ⚠️ table seule | ⚠️ (P1) |
| C16 | Releases versionnées | ❌ | ✅ |
| C17 | Recherche full-text FTS5 | ❌ stub | ✅ réel |
| C18 | API CRUD document/provision/version | ❌ | ✅ |
| C19 | Diff juridique | ❌ | ✅ `/v1/diff` |
| C20 | E2E : ingest→version→snapshot→search→explain | ❌ | ⚠️ (partiel — CI absent en live) |
| C21 | DB persistante (redémarrage) | ❌ :memory: | ✅ data/juslib.db |
| C22 | Transaction atomique ingestion | ❌ | ✅ |
| C23 | CI GitHub Actions | ❌ | ✅ .github/workflows/ci.yml |

**Score :** 20/23 critères ✅  
**Encore NO-GO certification** — critères restants : C15 (traductions API), C20 (E2E live), tests live connecteurs.

---

## 7. Correction documentaire R004

Le rapport R004 indiquait :
- `test_juslib_r003.py : 49 tests` → correct (R004 déclarait 50 par erreur de comptage)
- `test_juslib_j004.py : 55 tests` → correct (R004 déclarait 55 ✅)

---

## 8. Points restants (chantier suivant J007)

| Priorité | Chantier |
|----------|----------|
| P0 | Connecteurs live réellement testés (EUR-Lex, Légifrance sandbox) |
| P0 | Test E2E complet avec redémarrage API (persistance vérifiée) |
| P0 | Endpoint `/v1/translation` (traductions) |
| P1 | Graphe NetworkX `/v1/graph/{id}` |
| P1 | `check_same_thread=False` → RLock ou connexion par requête |
| P1 | `compute_snapshot()` — erreurs silencieuses → exception explicite |
| P1 | Lien vers README mis à jour (0.2.0) |

---

## 9. Log de session

**Fichier :** `logs/20261004_R006_corrections_J006.json`  
**Résultat :** `ALL_PASS` — 230/230

---

*Rapport généré après audit ligne par ligne — JUSLIB R006 — Mode DEBUG actif*  
*CERTIFIED_100=false | unique_human_proven=false*
