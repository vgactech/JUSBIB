# R004 — Corrections audit J004 — JUSLIB v0.1.3

**Session :** J004  
**Date :** 2026-10-04  
**SHA HEAD ARTCB :** ae86ba4  
**Version JUSLIB :** 0.1.3  
**Résultat :** ✅ 173/173 PASS — zéro échec  
**CERTIFIED_100 :** false  
**unique_human_proven :** false  
**Mode DEBUG :** actif  

---

## 1. Contexte

La session J003 avait identifié 8 points d'audit critiques sur JUSLIB v0.1.2 (119 tests, commit `aafd040`).  
La session J004 corrige l'intégralité de ces points et ajoute 55 nouveaux tests (blocs O→X) pour les valider.

---

## 2. Corrections appliquées — Avant / Après

### P0-01 — Injection corpus fermée (CRITIQUE)

**Fichier :** `src/juslib/api/main.py`  
**Fichier :** `src/juslib/db.py`

| | Avant (v0.1.2) | Après (v0.1.3) |
|---|---|---|
| Endpoint | `/v1/corpus/index` (unique, acceptait tout) | `/v1/corpus/ingest` (connecteur officiel) + `/v1/corpus/import/unverified` (client) |
| Champ source | absent | `ingestion_method: "connector_fetched"` ou `"client_provided"` |
| Niveau EXPERT | autorisé sur tout | interdit sur `client_provided` (HTTP 403) |
| Constante DB | absente | `CERTAINTY_CLIENT_PROVIDED = "client_provided"` |

**Lignes avant (`api/main.py`) :**
```python
@app.post("/v1/corpus/index")
async def index_corpus(payload: CorpusIndexPayload, db: JuslibDB = Depends(get_db)):
    entry_id = db.index_corpus_entry(payload.text, payload.source_url, ...)
```

**Lignes après (`api/main.py`) :**
```python
@app.post("/v1/corpus/ingest")
async def ingest_corpus(payload: CorpusIngestPayload, db: JuslibDB = Depends(get_db)):
    # ingestion_method = "connector_fetched"

@app.post("/v1/corpus/import/unverified")
async def import_corpus_unverified(payload: CorpusImportPayload, db: JuslibDB = Depends(get_db)):
    # ingestion_method = "client_provided"
    # niveau EXPERT → HTTP 403
```

---

### P0-02 — Import hashlib manquant (CRITIQUE)

**Fichier :** `src/juslib/api/main.py`

| | Avant | Après |
|---|---|---|
| Ligne 1 imports | `import uuid` | `import hashlib` ajouté |
| Comportement | `NameError: name 'hashlib' is not defined` sur `/v1/explain` | fonctionnel |

**Ligne avant :** *(absent)*  
**Ligne après :** `import hashlib  # P0-02: was missing, caused NameError on /v1/explain`

---

### P0-03 — INSERT strict corpus_entries

**Fichier :** `src/juslib/db.py`

| | Avant | Après |
|---|---|---|
| Méthode `index_corpus_entry()` | `INSERT OR REPLACE INTO corpus_entries` | `INSERT INTO corpus_entries` (strict) |
| Doublon | silencieusement écrasé | `sqlite3.IntegrityError` levée |

**Ligne avant :** `cursor.execute("INSERT OR REPLACE INTO corpus_entries ...`  
**Ligne après :** `cursor.execute("INSERT INTO corpus_entries ...`

---

### P0-04 — Triggers INSERT-only manquants

**Fichier :** `src/juslib/db.py`

| Table | Avant | Après |
|---|---|---|
| `legal_provisions` | trigger absent | `trg_provisions_no_update` + `trg_provisions_no_delete` |
| `legal_snapshots` | trigger absent | `trg_snapshots_no_update` + `trg_snapshots_no_delete` |
| `relation_evidence` | trigger absent | `trg_relation_evidence_no_update` + `trg_relation_evidence_no_delete` |
| `translation_records` | trigger absent | `trg_translation_records_no_update` + `trg_translation_records_no_delete` |
| `corpus_entries` | trigger absent | `trg_corpus_entries_no_update` + `trg_corpus_entries_no_delete` |
| `source_captures` | table inexistante | table créée + `trg_source_captures_no_update` + `trg_source_captures_no_delete` |

**Avant :** 0 trigger sur ces 5 tables.  
**Après :** 12 triggers INSERT-only supplémentaires (total DB : 18 triggers).

---

### P1-01 — Détection chevauchement temporel

**Fichier :** `src/juslib/db.py` — méthode `insert_version()`

| | Avant | Après |
|---|---|---|
| Chevauchement | non détecté | `TemporalOverlapError` levée |
| Override | absent | `allow_overlap=True` pour bypass explicite |
| Méthode | absente | `find_overlapping_version()` — retourne les détails |

**Avant :** *(pas de vérification de chevauchement)*  
**Après :**
```python
def insert_version(self, provision_id, text, valid_from, valid_until=None,
                   version_status="in_force", allow_overlap=False):
    if not allow_overlap:
        overlap = self.find_overlapping_version(provision_id, valid_from, valid_until)
        if overlap:
            raise TemporalOverlapError(...)
```

---

### P1-02 — Version status

**Fichier :** `src/juslib/db.py`

| | Avant | Après |
|---|---|---|
| Colonne `version_status` | absente dans schema | présente dans `legal_versions` |
| Valeurs | inexistantes | `in_force` / `repealed` / `suspended` / `not_yet_in_force` / `partially_repealed` |
| `get_version_at_date()` | retournait toute version | filtre `version_status = "in_force"` uniquement |
| `get_version_status_at_date()` | absent | nouvelle méthode — audit historique toutes versions |

**Ligne avant (CREATE TABLE) :** *(pas de colonne version_status)*  
**Ligne après :** `version_status TEXT NOT NULL DEFAULT 'in_force'`

---

### P1-03 — Table source_captures

**Fichier :** `src/juslib/db.py`

| | Avant | Après |
|---|---|---|
| Table | absente | `source_captures` créée |
| Colonnes | — | `id`, `corpus_entry_id`, `retrieval_timestamp`, `http_status`, `raw_bytes_hash`, `connector_version`, `etag`, `last_modified`, `created_at` |
| Méthodes | absentes | `insert_source_capture()`, `get_source_captures()` |
| Endpoint | absent | `/v1/corpus/ingest` crée automatiquement une `SourceCapture` |

---

### P1-04 — Contraintes UNIQUE sur identifiants officiels

**Fichier :** `src/juslib/db.py` — DDL `legal_documents`

| Colonne | Avant | Après |
|---|---|---|
| `eli_id` | pas de contrainte UNIQUE | `UNIQUE` |
| `celex_id` | pas de contrainte UNIQUE | `UNIQUE` |
| `ecli_id` | pas de contrainte UNIQUE | `UNIQUE` |

**Ligne avant :** `celex_id TEXT,`  
**Ligne après :** `celex_id TEXT UNIQUE,`

---

### Adaptation test K09

**Fichier :** `tests/test_juslib_r003.py`

| | Avant | Après |
|---|---|---|
| Test K09 | deux versions à période ouverte (chevauchaient) | première version fermée avec `valid_until="2021-01-01"` avant d'en insérer une deuxième |

---

## 3. Résultats des tests

| Fichier | Tests | Résultat |
|---------|-------|----------|
| `test_juslib_core.py` | 69 (blocs A–G) | ✅ 69 PASS |
| `test_juslib_j004.py` | 55 (blocs O–X) | ✅ 55 PASS |
| `test_juslib_r003.py` | 49 (blocs H–N) | ✅ 49 PASS |
| **TOTAL** | **173** | **✅ 173 PASS** |

**Durée :** 2.38s  
**Régression :** 0 test cassé par rapport à v0.1.2

---

## 4. Nouveaux tests J004 (blocs O→X)

| Bloc | Thème | Tests |
|------|-------|-------|
| O | Injection corpus fermée | O01–O06 |
| P | Import hashlib | P01–P02 |
| Q | INSERT strict corpus_entries | Q01–Q03 |
| R | Triggers INSERT-only toutes tables | R01–R07 |
| S | API HTTP (TestClient FastAPI) | S01–S10 |
| T | Chevauchement temporel | T01–T06 |
| U | Version status | U01–U05 |
| V | Source captures | V01–V05 |
| W | Identifiants uniques ELI/CELEX/ECLI | W01–W05 |
| X | Non-régression J004 | X01–X05 |

---

## 5. Architecture DB après J004

```
legal_documents       — documents officiels (ELI/CELEX/ECLI UNIQUE)
legal_provisions      — dispositions (INSERT-only)
legal_versions        — versions temporelles (version_status, chevauchement détecté)
legal_snapshots       — snapshots (INSERT-only)
corpus_entries        — entrées corpus (INSERT strict, ingestion_method)
source_captures       — provenance brute (NOUVEAU — INSERT-only)
relation_evidence     — relations juridiques (INSERT-only)
translation_records   — traductions (INSERT-only)
corpus_releases       — releases versionnées (INSERT-only)
```

**Triggers actifs :** 18 au total (INSERT-only sur 9 tables)

---

## 6. Log de session

**Fichier :** `logs/20261004_R004_corrections_J004.json`  
**Résultat :** `ALL_PASS` — 173/173

---

## 7. Limites et chantiers suivants

| Limite | Statut |
|--------|--------|
| Tests HTTP utilisent `TestClient` in-memory — pas de serveur réel | OK pour CI |
| Connecteurs réseau (EUR-Lex, Légifrance, HUDOC) non testés en live | NEXT TASK |
| Interface web (Q-J04) non encore développée | ROADMAP V1 |
| Graphe juridique (relations inter-documents) | ROADMAP V1 |
| Recherche full-text | ROADMAP V1 |
| Export SPARQL/RDF | ROADMAP V2 |
| Multilingue 24 langues UE complet | ROADMAP V2 |

---

## 8. Invariants vérifiés

| # | Invariant | Statut |
|---|-----------|--------|
| I1 | Toute information juridique a une source identifiable | ✅ |
| I2 | Aucune version historique ne peut être écrasée | ✅ (18 triggers) |
| I3 | Toute explication reste reliée à sa source | ✅ |
| I4 | Toute modification du corpus est traçable | ✅ (source_captures) |
| I5 | Production IA distinguable de la source | ✅ (ingestion_method + ProductionType) |
| I6 | Distinction certain / interprété / contesté / non vérifié | ✅ (certainty_level) |

---

*Rapport généré automatiquement — JUSLIB R004 — Mode DEBUG actif*  
*CERTIFIED_100=false | unique_human_proven=false*
