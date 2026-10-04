# JUSLIB — Bibliothèque Juridique Souveraine Multilingue

> **Version :** 0.3.0 · **Licence :** AGPL-3.0 · **Statut :** Alpha — Mode DEBUG actif  
> `CERTIFIED_100=false` · `unique_human_proven=false` · Tests : **269/269 PASS**  
> Couverture : Europe + droit international — 24 langues UE + 6 langues ONU + OHADA

---

## Qu'est-ce que JUSLIB ?

JUSLIB est une **infrastructure de provenance, de versionnement temporel et d'intégrité pour les données juridiques**.

Elle n'est pas une simple base documentaire.  
Elle ne cherche pas à remplacer vLex, Harvey ou Legora.

Elle s'attaque à un problème différent :

> **Avant qu'une IA exploite une norme, la norme elle-même doit être identifiée, datée, hachée, versionnée, liée à ses dérivés, et reconstructible de manière déterministe à n'importe quelle date.**

### Trois publics

| Public | Usage |
|--------|-------|
| **Juristes professionnels** | Sources officielles, jurisprudence consolidée, graphe normatif, diff juridique versionné |
| **Étudiants en droit** | Navigation dans la hiérarchie des normes, historique temporel, citations normalisées |
| **Grand public** | Traduction en langage clair (3 niveaux), avec marquage IA obligatoire et non supprimable |

---

## Ce que JUSLIB fait que les autres ne démontrent pas publiquement

| Propriété | JUSLIB | Concurrents (vLex / Harvey / Legora / Jus Mundi) |
|-----------|--------|---------------------------------------------------|
| Version temporelle explicite (`valid_from` / `valid_until` / `status`) | ✅ | Non démontré publiquement |
| Hash cryptographique du contenu source (`canonical_content_hash`) | ✅ | Non démontré publiquement |
| Corpus INSERT-only (jamais UPDATE/DELETE sur une version) | ✅ | Non démontré publiquement |
| Traduction cryptographiquement liée à une version précise (`source_version_hash`) | ✅ | Non démontré publiquement |
| Snapshot juridique reproductible à une date quelconque | ✅ | Non démontré publiquement |
| `is_normative_source = 0` — contrainte SQL sur toutes les traductions | ✅ | Non démontré publiquement |
| Distinction CERTAIN / INTERPRÉTÉ / CONTESTÉ / NON VÉRIFIÉ | ✅ | Non démontré publiquement |
| Distinction SOURCE / LLM_GENERATED / LLM_VALIDATED / HUMAN_VALIDATED | ✅ | Non démontré publiquement |
| Code source ouvert et auditable | ✅ | ❌ (propriétaire) |

> **Note honnête :** vLex, Harvey, Lexis, Legora et Jus Mundi ont des corpus beaucoup plus larges et des produits IA beaucoup plus matures. JUSLIB n'est pas en compétition sur ce terrain aujourd'hui. Son avantage est structurel, pas volumétrique.

---

## Modèle de données — la chaîne de vérité

```
SOURCE OFFICIELLE
  │  url + hash SHA-256 + timestamp
  ▼
DOCUMENT JURIDIQUE
  │  juslib_id · celex_id · type · juridiction
  ▼
DISPOSITION (article / alinéa / paragraphe)
  │  number · heading · language
  ▼
VERSION JURIDIQUE
  │  valid_from · valid_until · version_status · canonical_content_hash
  │
  ├──────────────────────────┐
  ▼                          ▼
TRADUCTION                RELATION
  │                          │
  ├── source_version_hash    ├── relation_type (SUPPLEMENTS / IMPLEMENTS / OVERRULES…)
  ├── production_type        ├── confidence [0,1]
  ├── is_normative_source=0  └── evidence_url
  └── canonical_hash
  │
  ▼
RELEASE CORPUS
  manifest_hash · corpus_version · documents_count · versions_count
```

### Snapshot temporel

```python
# Quelle règle était applicable le 15 juin 2017 ?
snapshot = db.compute_snapshot(document_id, "2017-06-15")
# → retourne la version in_force à cette date, avec son hash et son statut réel
```

La méthode `compute_snapshot()` retourne, pour chaque disposition d'un document, la version `in_force` à la date demandée — ou `repealed` / `not_yet_in_force` si applicable. L'historique est préservé et reconstructible.

---

## 6 Invariants fondamentaux (non négociables)

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | **Toute information juridique doit avoir une source identifiable** | `source_url` + `canonical_content_hash` obligatoires |
| 2 | **Une version historique ne doit jamais être écrasée** | Triggers SQLite `BEFORE UPDATE/DELETE` → erreur immédiate |
| 3 | **Toute explication reste reliée au texte qu'elle explique** | FK non nullable |
| 4 | **Toute modification du corpus est traçable et reproductible** | Tag Git `corpus/YYYY.MM.DD-NNN` + `manifest_hash` |
| 5 | **Une production IA est toujours distinguable de la source juridique** | `production_type` + `ai_warning` obligatoire et non supprimable |
| 6 | **Le système distingue CERTAIN / INTERPRÉTÉ / CONTESTÉ / NON VÉRIFIÉ** | `certainty_level` explicite sur chaque enregistrement |

---

## Traductions versionnées — invariant cryptographique

Contrairement à un système qui stocke simplement "la traduction de l'article 12", JUSLIB stocke :

> **"la traduction de l'article 12 dans sa version cryptographiquement identifiée V42"**

```sql
-- Contrainte SQL — jamais dérogeable
CHECK (is_normative_source = 0)

-- Lien automatique à la création
source_version_hash = canonical_content_hash(LegalVersion source)
```

Si la version juridique source est modifiée, elle devient une nouvelle version avec un nouvel identifiant. La traduction reste liée à l'ancienne. Le système peut détecter automatiquement une divergence entre source et traduction.

---

## Sources officielles couvertes (V0.3)

| Connecteur | Source | Juridiction | Langues | Authentification |
|------------|--------|-------------|---------|-----------------|
| `eurlex` | EUR-Lex / Journal officiel UE | Union Européenne | 24 langues officielles UE | Publique (SPARQL) |
| `legifrance` | Légifrance / PISTE API | France | Français | OAuth2 gratuit (PISTE) |
| `echr` | HUDOC | CEDH / Conseil de l'Europe | FR + EN | Publique |
| `canlii` | CanLII | Canada / Québec | FR + EN | Clé API gratuite |
| `ohada` | OHADA.com | OHADA (17 États) | Français | Publique |
| `un` | ODS / Treaty Collection | ONU | AR, ZH, EN, FR, RU, ES | Publique |

**V1 prévue :** Bundesgesetzblatt (DE), BOE (ES), Gazzetta Ufficiale (IT), Staatsblad (NL), Dziennik Ustaw (PL), CVIM, UNIDROIT

---

## Architecture technique

```
SOURCES OFFICIELLES
  EUR-Lex · Légifrance · HUDOC · CanLII · OHADA · ONU
       │
       ▼  source_url + canonical_content_hash (SHA-256)
COUCHE PERSISTANCE SQLite (juslib.db)
  LegalDocument · LegalProvision · LegalVersion
  TranslationRecord · RelationEvidence
  CorpusRelease · LegalAuthority · LegalSnapshot
       │
       ▼  INSERT-only — triggers BEFORE UPDATE/DELETE → erreur
VERSIONNEMENT CORPUS
  CorpusRelease (manifest_hash) · Tag Git corpus/YYYY.MM.DD-NNN
       │
MOTEUR
  FTS5 full-text · compute_snapshot() · diff juridique (difflib)
  Relations normatives · Autorités
       │
TRADUCTION (3 niveaux)
  EXPERT | INTERMEDIATE | CITIZEN
  Marquage IA obligatoire · source_version_hash lié
       │
API REST (FastAPI)
  /v1/document   /v1/provision   /v1/version
  /v1/search     /v1/diff        /v1/snapshot
  /v1/translation             /v1/corpus/release
  /v1/health
```

---

## Démarrage rapide

```bash
# 1. Cloner
git clone https://github.com/vgactech/JUSBIB.git
cd JUSBIB/juslib

# 2. Environnement
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Tests complets
python3 -m pytest tests/ -v
# → 269 passed

# 4. API locale
uvicorn juslib.api.main:app --port 8765
# → http://localhost:8765/v1/health
# → http://localhost:8765/docs

# 5. Snapshot temporel (exemple)
curl "http://localhost:8765/v1/snapshot/{document_id}?on_date=2017-06-15"
```

---

## Structure du projet

```
juslib/
├── src/juslib/
│   ├── __init__.py          # v0.3.0 — constantes, DEBUG_MODE
│   ├── db.py                # JuslibDB — persistance SQLite, modèles, snapshots, FTS5
│   └── api/
│       └── main.py          # API REST FastAPI — tous les endpoints
├── tests/
│   ├── test_juslib_core.py  # 69 tests — modèles, invariants, DB de base
│   ├── test_juslib_r003.py  # 49 tests — FTS5, relations, releases
│   ├── test_juslib_j004.py  # 55 tests — audit P0, autorités, snapshots
│   ├── test_juslib_j006.py  # 57 tests — MVP 23/23 critères, API complète
│   └── test_juslib_j007.py  # 39 tests — TranslationRecord, E2E persistance, CI strict
├── rapports/                # Rapports de session (jamais écrasés)
│   ├── R001 … R007
├── logs/                    # Logs JSON (mode DEBUG)
├── .github/workflows/
│   └── ci.yml               # CI GitHub Actions — unit-tests (3.11+3.12) + e2e-persistence
├── pyproject.toml
└── .env.example
```

---

## Nomenclature des identifiants

```
JUSLIB-{TYPE}-{JURISDICTION}-{CODE}-{YYYYMMDD}-{REV:03d}

Exemples :
  JUSLIB-REGULATION-EU-32016R0679-20160504-001   (RGPD)
  JUSLIB-LAW-FR-LEGITEXT000006070721-19040301-001 (Code civil)
  JUSLIB-JURISPRUDENCE-EU-C-311-18-20200716-001  (Schrems II)
  JUSLIB-CONVENTION-INT-A-RES-217-19481210-001   (DUDH)
```

---

## Niveaux de lecture

| Niveau | Cible | Règle |
|--------|-------|-------|
| `EXPERT` | Juriste / Magistrat | Texte original — jamais modifié |
| `INTERMEDIATE` | Étudiant / Praticien | Simplification + glossaire inline |
| `CITIZEN` | Grand public | Langage courant + définitions automatiques |

> ⚠️ Toute production de niveau INTERMEDIATE ou CITIZEN générée par IA est marquée  
> **`[⚠️ GÉNÉRÉ PAR IA — NON VALIDÉ PAR UN JURISTE HUMAIN]`** — obligatoire et non supprimable.

---

## Releases corpus

```
Tag Git annoté : corpus/YYYY.MM.DD-NNN
Exemple       : corpus/2026.10.04-001

Chaque release contient :
  - manifest_hash   : SHA-256 de l'index canonique
  - corpus_version  : version JUSLIB à la date de release
  - documents_count : nb de documents ingérés
  - versions_count  : nb de versions actives
  - release_date    : date ISO 8601
```

---

## Licences des données

| Source | Licence données |
|--------|----------------|
| EUR-Lex | Open Data Licence v2 (attribution requise) |
| Légifrance | Licence Ouverte Etalab 2.0 |
| HUDOC (CEDH) | Accès public (règlement intérieur CoE) |
| CanLII | CC BY-NC-ND (non commercial) |
| OHADA | Accès public site officiel |
| ONU ODS | Accès public |

> Le **code source** JUSLIB est sous licence **AGPL-3.0**.  
> Les **données** restent sous la licence de leur source officielle d'origine.

---

## État d'avancement honnête

```
✅  Modèle de données complet (LegalDocument → LegalVersion → TranslationRecord)
✅  Persistance SQLite — INSERT-only — triggers — FTS5
✅  Modèle temporel — compute_snapshot() — get_version_at_date()
✅  TranslationRecord cryptographiquement lié à la version source
✅  Diff juridique déterministe (difflib)
✅  API REST FastAPI — 12+ endpoints
✅  CI GitHub Actions — Python 3.11 + 3.12 — jobs unit + E2E
✅  269/269 tests PASS (synthétiques)

❌  Corpus réel non encore ingéré à grande échelle
❌  Connecteurs non testés à volume (> 10k documents)
❌  Graphe juridique inter-documents non encore dense
❌  Validation humaine des données non effectuée
❌  Interface utilisateur non implémentée
```

`CERTIFIED_100=false` — Les 269 tests valident l'architecture et les invariants sur des données synthétiques. Ils ne certifient ni l'exhaustivité ni la justesse juridique d'un corpus réel.

---

## Feuille de route

| Version | Contenu |
|---------|---------|
| **V0.3** ✅ | Persistance SQLite, modèle temporel, TranslationRecord, API REST, CI strict — 269/269 PASS |
| **V0.4** | Ingestion réelle EUR-Lex + Légifrance — 1 000 documents — mesure couverture/intégrité |
| **V0.5** | Graphe juridique inter-documents — relations IMPLEMENTS / OVERRULES / SUPPLEMENTS |
| **V1.0** | Interface juriste + 10+ connecteurs nationaux + recherche full-text sémantique |
| **V2.0** | Enrichissement LLM validé + détection contradictions jurisprudentielles + alertes |
| **V3.0** | API publique + partenariats institutionnels + certification données |

---

*JUSLIB v0.3.0 — Mode DEBUG actif — `CERTIFIED_100=false` — Alpha*
