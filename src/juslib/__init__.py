"""
JUSLIB — Bibliothèque Juridique Souveraine Multilingue
Version : 0.1.3
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
           /v1/corpus/ingest (officiel) vs /v1/corpus/import/unverified (client)
           EXPERT interdit sur ingestion_method=client_provided
  P0-02 : import hashlib ajouté (NameError /v1/explain corrigé)
  P0-03 : INSERT strict sur corpus_entries (plus de OR REPLACE)
  P0-04 : Triggers INSERT-only ajoutés sur legal_provisions, legal_snapshots,
           relation_evidence, translation_records, corpus_entries, source_captures
  P1-01 : Détection chevauchement temporel dans insert_version (allow_overlap=False)
  P1-02 : version_status (in_force/repealed/suspended/not_yet_in_force/partially_repealed)
           get_version_at_date filtre version_status=in_force uniquement
           get_version_status_at_date pour l'audit historique complet
  P1-03 : Table source_captures — chaîne de provenance brute
           (raw_bytes_hash, retrieval_timestamp, http_status, connector_version, etag)
  P1-04 : UNIQUE sur eli_id, celex_id, ecli_id (contraintes DDL)
"""

__version__ = "0.1.3"
__project__ = "JUSLIB"
__description__ = "Sovereign Multilingual Legal Library — European and International Level"
DEBUG_MODE = True

CERTIFIED_100 = False
COVERAGE_VERIFIED = False
