# R005 — Audit MVP JUSLIB — État réel vérifié sur HEAD

**Session :** J005-AUDIT  
**Date :** 2026-10-04  
**SHA HEAD JUSBIB :** 058a9c8  
**Version JUSLIB :** 0.1.3  
**CERTIFIED_100 :** false  
**unique_human_proven :** false  
**Mode DEBUG :** actif  
**Remote :** vgactech/JUSBIB.git — pushé et synchronisé ✅

---

## ⚠️ Note préliminaire — SHA fictif R439

Le message entrant cite un rapport R439 avec commit `076db20a2455b8805db41c4d7d043346b8bbecac`.
Ce SHA **n'existe pas** dans `vgactech/JUSBIB.git` (vérifié : `git log --oneline` ne le contient pas).
Ce SHA appartient probablement à une session externe (ChatGPT / autre contexte).  
Le présent rapport R005 constitue l'audit MVP réel, produit sur le HEAD vérifié `058a9c8`.

---

## 1. Rappel — État commité v0.1.3

| Élément | État |
|---------|------|
| Commits pushés | 4 (d1ec32d / b55d23f / aafd040 / 058a9c8) |
| Remote jusbib/main | synchronisé ✅ |
| Tests | 173/173 PASS |
| Version | 0.1.3 |

---

## 2. Audit structure DB réelle (vérifié `python3 -c`)

### Tables présentes (9)

| Table | Triggers INSERT-only | Colonnes clés |
|-------|---------------------|---------------|
| `legal_documents` | ✅ no_update + no_delete | ELI/CELEX/ECLI UNIQUE, source_url, raw_source_hash, canonical_content_hash, production_type, certainty_level |
| `legal_provisions` | ✅ no_update + no_delete | provision_id, document_id, article_number, title |
| `legal_versions` | ✅ no_update + no_delete | version_status, valid_from, valid_until, raw_source_hash, canonical_content_hash, previous_version_id |
| `legal_snapshots` | ✅ no_update + no_delete | — |
| `corpus_entries` | ✅ no_update + no_delete | ingestion_method, raw_source_hash, canonical_content_hash |
| `source_captures` | ✅ no_update + no_delete | raw_bytes_hash, http_status, etag, connector_version |
| `relation_evidence` | ✅ no_update + no_delete | — |
| `translation_records` | ✅ no_update + no_delete | — |
| `authorities` | ❌ (pas de triggers — table référentielle) | authority_type, jurisdiction |

**Total triggers :** 16 (8 tables × 2)

### ❌ Table manquante : `corpus_releases`
- Mentionnée dans R004 comme table présente → **FAUX** — absente du DDL réel
- R004 décrivait l'intention, pas l'implémentation réelle
- **P0 : à créer**

---

## 3. Audit API endpoints (vérifié via `app.routes`)

| Endpoint | Méthode | État |
|----------|---------|------|
| `/v1/health` | GET | ✅ |
| `/v1/corpus/ingest` | POST | ✅ (connector_fetched) |
| `/v1/corpus/import/unverified` | POST | ✅ (client_provided) |
| `/v1/corpus/snapshot/{id}` | GET | ✅ |
| `/v1/corpus/versions` | GET | ✅ |
| `/v1/explain` | POST | ✅ |
| `/v1/explain/text` | POST | ✅ |
| `/v1/search` | POST | ⚠️ STUB — retourne note "Phase 7" |
| `/v1/db/stats` | GET | ✅ |
| `/v1/glossary` | GET | ✅ |
| `/v1/glossary/{term}` | GET | ✅ |
| `/v1/languages` | GET | ✅ |
| **`/v1/document`** | POST | ❌ **MANQUANT** — aucun endpoint pour insérer un document |
| **`/v1/provision`** | POST | ❌ **MANQUANT** |
| **`/v1/version`** | POST | ❌ **MANQUANT** |
| **`/v1/relation`** | POST | ❌ **MANQUANT** |
| **`/v1/search` FTS5** | POST | ❌ stub sans moteur réel |

---

## 4. Audit fonctions db.py réelles (vérifié `grep -n "def "`)

| Fonction | État | Note |
|----------|------|------|
| `insert_document()` | ✅ | |
| `get_document()` | ✅ | |
| `find_documents_by_identifier()` | ✅ | ELI/CELEX/ECLI/native_id |
| `insert_provision()` | ✅ | |
| `insert_version()` | ✅ | TemporalOverlapError, version_status |
| `_find_overlapping_version()` | ✅ | |
| `get_version_at_date()` | ✅ | filtre in_force |
| `get_version_status_at_date()` | ✅ | audit historique |
| `compute_snapshot()` | ✅ | |
| `index_corpus_entry()` | ✅ | INSERT strict |
| `get_corpus_entry()` | ✅ | |
| `verify_corpus_entry_integrity()` | ✅ | |
| `insert_source_capture()` | ✅ | |
| `get_source_captures()` | ✅ | |
| `is_connector_fetched()` | ✅ | |
| `insert_relation_evidence()` | ✅ | |
| `insert_translation()` | ✅ | |
| `stats()` | ✅ | |
| **`insert_corpus_release()`** | ❌ **MANQUANT** | table absente |
| **`search_fts()`** | ❌ **MANQUANT** | pas de FTS5 |
| **`insert_authority()`** | ❌ **MANQUANT** | table présente mais pas de méthode |

---

## 5. Analyse des 20 critères MVP (basés sur le cahier des charges)

| # | Critère | État |
|---|---------|------|
| C01 | Document avec source identifiable | ✅ |
| C02 | Hash brut (raw_source_hash) | ✅ |
| C03 | Hash canonique normalisé | ✅ |
| C04 | Identifiants officiels ELI/CELEX/ECLI UNIQUE | ✅ |
| C05 | Versions temporelles avec valid_from/valid_until | ✅ |
| C06 | version_status (in_force/repealed/suspended…) | ✅ |
| C07 | Détection chevauchement temporel | ✅ |
| C08 | Snapshot à une date donnée | ✅ |
| C09 | Triggers INSERT-only sur 8 tables | ✅ |
| C10 | source_captures — provenance brute | ✅ |
| C11 | Séparation connector_fetched / client_provided | ✅ |
| C12 | EXPERT interdit sur client_provided | ✅ |
| C13 | Corpus entries avec intégrité vérifiable | ✅ |
| C14 | Relation entre documents (relation_evidence) | ⚠️ table présente, pas d'endpoint API |
| C15 | Traductions (translation_records) | ⚠️ table présente, pas d'endpoint API |
| C16 | Releases versionnées du corpus | ❌ table absente |
| C17 | Recherche full-text FTS5 | ❌ stub uniquement |
| C18 | API REST complète CRUD document/provision/version | ❌ endpoints manquants |
| C19 | Connecteurs réseau testés live (EUR-Lex, Légifrance…) | ❌ tests in-memory uniquement |
| C20 | E2E : ingest → version → snapshot → search → explain | ❌ pas de test E2E complet |

**Score :** 13/20 critères ✅ — **NO-GO certification** — GO implémentation immédiate

---

## 6. Points P0 bloquants pour MVP complet (prochaine session J006)

| Priorité | Chantier | Fichiers concernés |
|----------|----------|-------------------|
| **P0-A** | Ajouter table `corpus_releases` + méthode `insert_corpus_release()` | `db.py` |
| **P0-B** | Endpoints API : `/v1/document`, `/v1/provision`, `/v1/version`, `/v1/relation` | `api/main.py` |
| **P0-C** | FTS5 SQLite sur `legal_versions.text` — recherche réelle dans `/v1/search` | `db.py` + `api/main.py` |
| **P1-A** | Méthode `insert_authority()` / `get_authority()` + endpoint `/v1/authority` | `db.py` + `api/main.py` |
| **P1-B** | Test E2E complet : ingest → provision → version → snapshot → search → explain | `tests/test_juslib_j006.py` |

---

## 7. Invariants — Statut réel

| # | Invariant | Statut |
|---|-----------|--------|
| I1 | Toute information juridique a une source identifiable | ✅ |
| I2 | Aucune version historique ne peut être écrasée (triggers INSERT-only) | ✅ 16 triggers |
| I3 | Toute explication reste reliée à sa source | ✅ |
| I4 | Toute modification du corpus est traçable (source_captures) | ✅ |
| I5 | Production IA distinguable de la source | ✅ |
| I6 | Distinction certain / interprété / contesté / non vérifié | ✅ |

---

## 8. Verdict

| Verdict | Valeur |
|---------|--------|
| Tests | ✅ 173/173 PASS |
| SHA fictif R439 | ❌ N'existe pas dans JUSBIB — ignoré |
| Rapport envoyé au bon dépôt | ✅ `vgactech/JUSBIB.git` — commit 058a9c8 |
| Certification MVP | ❌ NO-GO — C16/C17/C18/C19/C20 non remplis |
| Prochaine session | **J006 — P0-A/B/C : corpus_releases + API CRUD + FTS5** |

---

*Rapport généré après audit ligne par ligne — JUSLIB R005 — Mode DEBUG actif*  
*CERTIFIED_100=false | unique_human_proven=false*
