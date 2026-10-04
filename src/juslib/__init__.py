"""
JUSLIB — Bibliothèque Juridique Souveraine Multilingue
Version : 0.2.0
Couverture : Europe + droit international (UE, CEDH, ONU, OHADA, FR, EN, DE, ES, IT, NL, PT, PL…)
Mode DEBUG actif

R003-P0 : Corrections audit R003.
  P0-A : URLs OAuth Légifrance corrigées (piste.gouv.fr)
  P0-B : verify_integrity() sans effet de bord (_compute_hash_readonly)
  P0-C : canonical_content_hash séparé de raw_source_hash dans /v1/explain
  P0-D : _enrich_with_llm() ne marque plus llm_generated sans appel réel
  P0-E : SQLite JuslibDB (FK réelles, INSERT-only triggers, Snapshot, ELI/CELEX/ECLI)

R004-J004 : Corrections audit J003.
  P0-01 : Injection corpus fermée — séparation connector_fetched vs client_provided
  P0-02 : import hashlib ajouté
  P0-03 : INSERT strict corpus_entries
  P0-04 : Triggers INSERT-only sur 6 tables
  P1-01 : Détection chevauchement temporel
  P1-02 : version_status (in_force/repealed/suspended/not_yet_in_force/partially_repealed)
  P1-03 : Table source_captures — chaîne de provenance brute
  P1-04 : UNIQUE sur eli_id, celex_id, ecli_id

R006-J006 : Corrections audit J005 (P0 MVP).
  P0-A  : Table corpus_releases — releases immuables INSERT-only + méthodes CRUD
  P0-B  : Méthodes insert_authority/get_authority/get_all_authorities + endpoints /v1/authority
  P0-C  : FTS5 SQLite sur legal_versions.text — search_versions_fts() + /v1/search réel
  P0-D  : DB persistante par défaut data/juslib.db (plus :memory: en production)
  P0-E  : Ingestion transactionnelle atomique (BEGIN/COMMIT/ROLLBACK)
  P0-F  : Endpoints CRUD — /v1/document (GET/POST), /v1/provision (POST), /v1/version (POST),
           /v1/relation (POST), /v1/diff/{from}/{to} (GET)
  P0-G  : Sync version 0.2.0 dans __init__.py + pyproject.toml
  P0-H  : CI GitHub Actions workflow (.github/workflows/ci.yml)
"""

__version__ = "0.2.0"
__project__ = "JUSLIB"
__description__ = "Sovereign Multilingual Legal Library — European and International Level"
DEBUG_MODE = True

CERTIFIED_100 = False
COVERAGE_VERIFIED = False
