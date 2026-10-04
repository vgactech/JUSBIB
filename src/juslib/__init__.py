"""
JUSLIB — Bibliothèque Juridique Souveraine Multilingue
Version : 0.1.2
Couverture : Europe + droit international (UE, CEDH, ONU, OHADA, FR, EN, DE, ES, IT, NL, PT, PL…)
Mode DEBUG actif

R003-P0 : Corrections audit R003.
  P0-A : URLs OAuth Légifrance corrigées (piste.gouv.fr)
  P0-B : verify_integrity() sans effet de bord (_compute_hash_readonly)
  P0-C : canonical_content_hash séparé de raw_source_hash dans /v1/explain
  P0-D : _enrich_with_llm() ne marque plus llm_generated sans appel réel
  P0-E : SQLite JuslibDB (FK réelles, INSERT-only triggers, Snapshot, ELI/CELEX/ECLI)
"""

__version__ = "0.1.2"
__project__ = "JUSLIB"
__description__ = "Sovereign Multilingual Legal Library — European and International Level"
DEBUG_MODE = True

CERTIFIED_100 = False
COVERAGE_VERIFIED = False
