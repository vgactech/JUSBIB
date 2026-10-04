# JUSLIB — Bibliothèque Juridique Souveraine Multilingue

> **Version :** 0.1.0 · **Licence :** AGPL-3.0 · **Mode DEBUG actif**  
> **Couverture :** Europe + droit international — FR/EN/DE/ES/IT/NL/PT/PL + 24 langues UE + ONU + OHADA

---

## Qu'est-ce que JUSLIB ?

JUSLIB est une bibliothèque juridique de référence, **ouverte, traçable et multilingue**, conçue pour :

- **Les juristes professionnels** — accès aux sources officielles, jurisprudence consolidée, graphe des relations normatives
- **Les étudiants en droit** — navigation dans la hiérarchie des normes, historique des versions, citations normalisées
- **Le grand public** — traduction du langage juridique en langage clair, avec 3 niveaux de lecture

---

## 6 Invariants fondamentaux (non négociables)

| # | Invariant |
|---|-----------|
| 1 | **Toute information juridique doit avoir une source identifiable** (`source_url` + `source_hash` SHA-256 obligatoires) |
| 2 | **Une version historique ne doit jamais être écrasée** (INSERT-only — jamais UPDATE/DELETE sur les versions) |
| 3 | **Toute explication reste reliée au texte ou à la décision qu'elle explique** (FK non nullable) |
| 4 | **Toute modification du corpus est traçable et reproductible** (tag Git `corpus/YYYY.MM.DD-NNN` + changelog structuré) |
| 5 | **Une production IA est toujours distinguable de la source juridique** (`production_type` + `ai_warning` obligatoire) |
| 6 | **Le système distingue : CERTAIN / INTERPRÉTÉ / CONTESTÉ / NON VÉRIFIÉ** (`certainty_level` explicite) |

---

## Sources officielles couvertes (V0.1)

| Connecteur | Source | Juridiction | Langues | Authentification |
|------------|--------|-------------|---------|-----------------|
| `eurlex` | EUR-Lex / JO UE | Union Européenne | 24 langues officielles UE | Publique (SPARQL) |
| `legifrance` | Légifrance / PISTE | France | Français | OAuth2 gratuit (PISTE) |
| `echr` | HUDOC | CEDH / Conseil de l'Europe | FR + EN | Publique |
| `canlii` | CanLII | Canada / Québec | FR + EN | Clé API gratuite |
| `ohada` | OHADA.com | OHADA (17 États) | Français | Publique |
| `un` | ODS / Treaty Collection | ONU | AR, ZH, EN, FR, RU, ES | Publique |

**V1 prévue :** Bundesgesetzblatt (DE), BOE (ES), Gazzetta Ufficiale (IT), Staatsblad (NL), Dziennik Ustaw (PL), EUR-Lex étendu, CVIM, UNIDROIT

---

## Architecture

```
SOURCES OFFICIELLES
  EUR-Lex · Légifrance · HUDOC · CanLII · OHADA · ONU
       │
       ▼ source_url + source_hash (SHA-256)
COUCHE DONNÉES (Modèles canoniques JUSLIB)
  LegalDocument · Disposition · JurisprudenceItem
  LegalRelation · Citation · Provenance · CorpusVersion
       │
       ▼ INSERT-only (jamais UPDATE/DELETE)
VERSIONNEMENT (Git-backed corpus)
  tag corpus/YYYY.MM.DD-NNN · Changelog structuré · Diff juridique
       │
MOTEUR (Recherche + Graphe + Validation)
  Full-text · Relations · Cohérence · Contradictions
       │
TRADUCTION (Juriste → Grand public)
  3 niveaux : expert | intermédiaire | citoyen
  24 langues UE + 6 langues ONU · Marquage IA obligatoire
       │
API REST (FastAPI)
  /v1/search · /v1/document · /v1/jurisprudence
  /v1/explain · /v1/diff · /v1/versions · /v1/corpus
```

---

## Démarrage rapide

```bash
# 1. Cloner
git clone https://github.com/vgactech/JUSBIB.git
cd JUSBIB

# 2. Environnement
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configuration (facultatif — les connecteurs publics fonctionnent sans clé)
cp .env.example .env
# Renseigner LEGIFRANCE_CLIENT_ID/SECRET si nécessaire

# 4. Tests
pytest tests/ -v

# 5. API (Phase 6)
# uvicorn juslib.api.main:app --port 8765
```

---

## Structure du projet

```
juslib/
├── src/juslib/
│   ├── models/              # Modèles canoniques (document, disposition, jurisprudence…)
│   ├── connectors/          # Connecteurs sources officielles (EUR-Lex, Légifrance, HUDOC…)
│   ├── engine/              # Moteur de recherche, graphe, validation
│   ├── versioning/          # Suivi des releases corpus (traçabilité Git)
│   ├── translation/         # Vulgarisation multilingue (3 niveaux de lecture)
│   └── api/                 # API REST FastAPI
├── tests/                   # Tests pytest (invariants + modèles + connecteurs)
├── rapports/                # Rapports de développement (jamais écrasés)
├── logs/                    # Logs JSON (mode DEBUG)
├── data/
│   ├── corpus/              # Index corpus + releases JSONL
│   ├── schemas/             # Schémas JSON/XML (Akoma Ntoso, JSON-LD)
│   └── fixtures/            # Données de test
├── docs/                    # Documentation technique
├── scripts/                 # Scripts d'import et de maintenance
├── rules/                   # Règles de validation juridique
├── pyproject.toml
├── requirements.txt
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

## Format des releases corpus

```
corpus/YYYY.MM.DD-NNN  (tag Git annoté)

Exemple : corpus/2026.10.04-001

Chaque release contient :
  - Index JSON canonique (SHA-256 = corpus_hash)
  - Changelog structuré (JSON + Markdown)
  - Statistiques (nb documents, nb décisions, juridictions, langues)
```

---

## Niveaux de lecture

| Niveau | Cible | Règle |
|--------|-------|-------|
| `EXPERT` | Juriste / Magistrat | Texte original — jamais modifié |
| `INTERMEDIATE` | Étudiant / Praticien | Simplification + glossaire inline |
| `CITIZEN` | Grand public | Langage courant + définitions automatiques |

> ⚠️ Toute production du niveau INTERMEDIATE ou CITIZEN générée par IA est marquée  
> **`[⚠️ GÉNÉRÉ PAR IA — NON VALIDÉ PAR UN JURISTE HUMAIN]`** — obligatoire et non supprimable.

---

## Licences des données

| Source | Licence données |
|--------|----------------|
| EUR-Lex | Open Data Licence v2 (gratuit, attribution requise) |
| Légifrance | Licence Ouverte Etalab 2.0 |
| HUDOC (CEDH) | Accès public (règlement intérieur CoE) |
| CanLII | CC BY-NC-ND (non commercial) |
| OHADA | Accès public site officiel |
| ONU ODS | Accès public |

> Le **code source** JUSLIB est sous licence **AGPL-3.0**.  
> Les **données** restent sous la licence de leur source officielle d'origine.

---

## Feuille de route

| Version | Contenu principal |
|---------|-------------------|
| **V0.1** | Modèles canoniques + 6 connecteurs + versionnement + vulgarisation 3 niveaux + tests |
| **V0.2** | API REST FastAPI complète + interface juriste (recherche + graphe) |
| **V0.3** | Import Akoma Ntoso / LegalXML / JSON-LD + diff juridique |
| **V1.0** | Interface grand public + 10+ connecteurs nationaux + graphe complet + recherche full-text |
| **V2.0** | Enrichissement LLM validé + détection contradictions jurisprudentielles + alertes mise à jour |
| **V3.0** | API publique + partenariats institutionnels + certification données |

---

*JUSLIB v0.1.0 — Mode DEBUG actif — `CERTIFIED_100=false` — Sources non encore vérifiées sur HEAD*
