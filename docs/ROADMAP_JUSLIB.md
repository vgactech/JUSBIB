# ROADMAP JUSLIB — Versions V0.4 → V3.0

> **Document :** ROADMAP_JUSLIB.md  
> **Version :** 1.0 — 2026-10-04  
> **Statut :** Feuille de route opérationnelle — Mode DEBUG actif  
> `CERTIFIED_100=false` | `unique_human_proven=false`

---

## Principe directeur

La roadmap JUSLIB distingue trois registres de travail qui ne doivent pas être confondus :

| Registre | Question | Condition de passage |
|----------|----------|---------------------|
| **Architecture** | Les modèles, invariants et flux sont-ils corrects ? | 269 tests PASS ✅ — déjà atteint en V0.3 |
| **Corpus réel** | Les données juridiques réelles sont-elles ingérées, vérifiées et à jour ? | Non encore atteint — priorité P0 absolue |
| **Capacités métier** | Les fonctions juridiques avancées (contradictions, veille, accès citoyen) sont-elles utilisables ? | Dépend du corpus réel — jamais avant P0 |

> **Règle d'or :** aucune capacité métier avancée ne peut être déclarée opérationnelle avant que le corpus réel soit ingéré, vérifié et surveillé.  
> `269 tests synthétiques PASS ≠ corpus juridiquement utilisable.`

---

## Vue d'ensemble des versions

```
V0.3 ✅  Architecture de base — persistance, snapshots, TranslationRecord, API, CI
V0.4     Corpus réel contrôlé — premiers documents réels ingérés et vérifiés
V0.5     Santé corpus + provenance + validation humaine — métriques de confiance
V0.6     LegalConcept + interopérabilité — couche conceptuelle multi-juridictions
V0.7     Graphe juridique dense — relations, jurisprudence, ratio/obiter
V0.8     Veille juridique — LegalDiff substantiel, alertes, décrets d'application
V0.9     Accès citoyen — LegalSituation, orientation procédurale, CITIZEN amélioré
V1.0     Bibliothèque juridique opérationnelle — interface juriste + public
V2.0     IA jurisprudentielle avancée — contradictions, raisonnement assisté
V3.0     Infrastructure ouverte — API publique, partenariats institutionnels, certification
```

---

## V0.4 — Corpus réel contrôlé (PRIORITÉ P0)

**Objectif :** Passer des 269 tests synthétiques à un corpus juridique réel, même petit mais rigoureusement vérifié.

**Critère de succès :** ≥ 1 000 documents réels ingérés depuis des sources officielles, avec hash vérifié, statut temporel correct et source traçable.

### Fonctions à implémenter

| Fonction | Module | Description |
|----------|--------|-------------|
| `run_connector(source_id)` | `connectors/` | Exécution réelle des 6 connecteurs sur sources officielles |
| `verify_import(document_id)` | `db.py` | Vérification post-ingestion : hash source ≠ hash stocké = ERREUR |
| `mark_unverified(document_id)` | `db.py` | Tout document ingéré automatiquement = `NON_VERIFIED` |
| `corpus_stats_real()` | `db.py` | Statistiques distinguant corpus réel vs données de test |
| `ConnectorRun` | `db.py` | Nouveau modèle — log de chaque exécution de connecteur |
| `import_error_log` | `logs/` | Log JSON de chaque erreur d'import par source |

### Modèle `ConnectorRun`

```python
ConnectorRun:
  run_id          : str      # UUID
  connector_id    : str      # 'eurlex' | 'legifrance' | 'echr' | ...
  started_at      : str      # ISO 8601
  completed_at    : str      # ISO 8601
  status          : str      # 'success' | 'partial' | 'failed'
  documents_fetched : int
  documents_inserted : int
  documents_failed  : int
  error_messages  : list[str]
  raw_source_hash : str      # hash du lot reçu
```

### Tests obligatoires (bloc AP)

- `AP01` : connecteur EUR-Lex retourne ≥ 1 document RGPD réel avec `canonical_content_hash`
- `AP02` : document ingéré a `version_status = 'in_force'` ou `'repealed'` réel (pas valeur par défaut)
- `AP03` : `mark_unverified` appliqué automatiquement à tout nouveau document
- `AP04` : `ConnectorRun` enregistré avec `status` et compteurs
- `AP05` : import avec hash invalide → erreur explicite, pas de silencing

---

## V0.5 — Santé corpus + provenance + validation humaine (PRIORITÉ P0)

**Objectif :** Rendre visible et mesurable l'état réel du corpus. Implémenter le workflow de validation humaine.

**Critère de succès :** Tableau de bord `CorpusHealth` opérationnel + premier document passé de `NON_VERIFIED` à `HUMAN_VALIDATED`.

### Modèle `CorpusHealth`

```python
CorpusHealth:
  source_id              : str
  jurisdiction           : str
  last_sync_attempted    : str   # ISO 8601
  last_sync_success      : str   # ISO 8601
  last_sync_error        : str   # message ou None
  total_documents        : int
  total_versions         : int
  docs_unverified        : int
  docs_automated_checked : int
  docs_human_reviewed    : int
  docs_certain           : int
  docs_contested         : int
  docs_rejected          : int
  failure_rate           : float # docs_failed / docs_fetched [0,1]
  freshness_days         : int   # jours depuis last_sync_success
  connector_status       : str   # 'active' | 'degraded' | 'down' | 'unknown'
```

### Endpoint API

```
GET /v1/corpus/health              → CorpusHealth[] (toutes sources)
GET /v1/corpus/health/{source_id}  → CorpusHealth (une source)
```

### Workflow validation humaine

```
NON_VERIFIED
     │
     ▼
AUTOMATED_CHECKED  ← hash vérifié, structure parsée, période temporelle cohérente
     │
     ▼ (intervention humaine requise)
HUMAN_REVIEWED     ← validateur_id + date + version_hash examinée
     │
     ├──→ CERTAIN    ← contenu confirmé exact par rapport à la source officielle
     ├──→ CONTESTED  ← divergence identifiée, signalée, en attente de résolution
     └──→ REJECTED   ← document incorrectement ingéré, retiré du corpus actif
```

### Modèle `HumanValidation`

```python
HumanValidation:
  validation_id      : str   # UUID
  document_id        : str
  version_id         : str
  validator_id       : str   # identifiant anonymisé ou pseudonyme
  validated_at       : str   # ISO 8601
  previous_status    : str
  new_status         : str
  source_checked     : str   # URL officielle consultée
  canonical_hash_at_validation : str
  notes              : str
  is_normative_check : bool  # True = juriste professionnel
```

### Invariant

> Une version ne peut pas passer de `NON_VERIFIED` à `CERTAIN` sans `HumanValidation` avec `is_normative_check=True`.  
> Aucun bypass automatique possible.

### Tests obligatoires (bloc AQ)

- `AQ01` : `CorpusHealth` retourne les bons compteurs pour chaque statut
- `AQ02` : `AUTOMATED_CHECKED` ne peut pas être `CERTAIN` — invariant SQL
- `AQ03` : `CERTAIN` requiert `HumanValidation` avec `is_normative_check=True`
- `AQ04` : `REJECTED` préserve la version dans l'historique (INSERT-only)
- `AQ05` : `freshness_days` calculé en temps réel (pas en cache)

---

## V0.6 — LegalConcept + interopérabilité (PRIORITÉ P1)

**Objectif :** Permettre de naviguer entre systèmes de droit (civil law / common law / OHADA) sans confondre les concepts.

**Critère de succès :** Table de correspondance opérationnelle pour ≥ 50 concepts juridiques fondamentaux en FR/EN/AR sur 3 systèmes (France, UE, OHADA).

### Modèle `LegalConcept`

```python
LegalConcept:
  concept_id       : str    # UUID JUSLIB
  canonical_label  : str    # EN — libellé de référence
  definition       : str    # définition générale
  legal_system     : str    # 'civil_law' | 'common_law' | 'mixed' | 'religious' | 'customary'
  jurisdiction     : str    # 'EU' | 'FR' | 'OHADA' | ...
  domain           : str    # 'contract' | 'tort' | 'property' | 'procedural' | ...
  canonical_content_hash : str
```

### Modèle `ConceptTerm`

```python
ConceptTerm:
  term_id     : str
  concept_id  : str    # FK → LegalConcept
  language    : str    # 'fr' | 'en' | 'ar' | ...
  term        : str    # le terme dans cette langue
  term_type   : str    # 'preferred' | 'synonym' | 'false_friend' | 'broader' | 'narrower'
  note        : str    # avertissement de perte de sens si 'false_friend'
```

### Modèle `ConceptEquivalence`

```python
ConceptEquivalence:
  equivalence_id    : str
  concept_a_id      : str    # FK → LegalConcept
  concept_b_id      : str    # FK → LegalConcept
  equivalence_level : str    # 'EXACT' | 'FUNCTIONAL' | 'PARTIAL' | 'ANALOGOUS' | 'NO_EQUIVALENT'
  direction         : str    # 'bidirectional' | 'a_to_b' | 'b_to_a'
  note              : str
  source_url        : str
  validated_by      : str    # identifiant validateur humain
```

### Identifiants normalisés (ELI / ECLI)

```python
LegalIdentifier:
  identifier_id    : str
  juslib_id        : str    # FK interne JUSLIB
  standard         : str    # 'ELI' | 'ECLI' | 'CELEX' | 'HUDOC' | 'CANLII' | 'OHADA_REF'
  value            : str    # valeur dans ce standard
  verified         : bool   # cross-vérifié avec source officielle
```

**Règle :** l'identifiant JUSLIB interne ne remplace jamais un identifiant officiel (ELI/ECLI). Les deux coexistent. La correspondance est traçable et vérifiable.

---

## V0.7 — Graphe juridique dense (PRIORITÉ P1)

**Objectif :** Passer du graphe peu dense actuel à un graphe juridiquement exploitable avec evidence, jurisprudence annotée (ratio/obiter) et couverture relationnelle mesurable.

**Critère de succès :** ≥ 500 relations vérifiées dans le corpus réel + modèle ratio/obiter implémenté.

### Extension de `RelationEvidence`

Ajouter au modèle existant :

```python
relation_subtype    : str   # 'DIRECT' | 'IMPLICIT' | 'OVERTURNED' | 'NARROWED' | 'EXTENDED'
temporal_scope      : str   # JSON — période d'application de la relation
jurisdiction_scope  : str   # liste de juridictions où la relation s'applique
validation_status   : str   # 'AUTOMATED' | 'HUMAN_VERIFIED' | 'DISPUTED'
```

### Modèle `JurisprudenceSegment`

```python
JurisprudenceSegment:
  segment_id     : str
  version_id     : str    # FK → LegalVersion (de la décision)
  segment_type   : str    # 'RATIO_DECIDENDI' | 'OBITER_DICTUM' | 'PROCEDURAL'
                          # 'FACTUAL' | 'BACKGROUND' | 'UNKNOWN'
  text_excerpt   : str
  start_char     : int
  end_char       : int
  canonical_hash : str
  annotated_by   : str    # 'automated' | identifiant humain
  confidence     : float  # [0,1] — pertinent si annotated_by = 'automated'
```

**Règle :** une contradiction ne peut être déclarée que sur des `RATIO_DECIDENDI`, jamais sur des `OBITER_DICTUM`.

### Indicateur de couverture relationnelle

```
GET /v1/stats/graph_coverage

→ {
    "total_documents": N,
    "documents_with_relations": K,
    "coverage_pct": K/N * 100,
    "total_relations": R,
    "verified_relations": V,
    "jurisprudence_with_ratio_annotation": J
  }
```

---

## V0.8 — Veille juridique (PRIORITÉ P1)

**Objectif :** Transformer le corpus statique en système de surveillance actif des évolutions normatives.

**Critère de succès :** Première alerte réelle déclenchée par une modification détectée sur EUR-Lex.

### LegalDiff substantiel — 3 catégories

```python
LegalDiffEntry:
  diff_id          : str
  version_from_id  : str
  version_to_id    : str
  change_category  : str   # 'FORMAL' | 'STRUCTURAL' | 'SUBSTANTIVE'
  change_type      : str   # 'ADDITION' | 'DELETION' | 'MODIFICATION' | 'RENUMBERING'
  affected_text    : str   # fragment concerné
  interpretation_hint : str  # ex: "'peut' → 'doit' : obligation créée"
  requires_review  : bool  # True si SUBSTANTIVE
```

| Catégorie | Déclencheur | Priorité alerte |
|-----------|-------------|----------------|
| `FORMAL` | ponctuation, renvois, numérotation | Faible |
| `STRUCTURAL` | déplacement de disposition, fusion d'articles | Moyenne |
| `SUBSTANTIVE` | modification d'obligation, de droit, de condition | Haute |

### Modèle `ImplementationStatus`

Pour les textes attendant leurs décrets d'application :

```python
ImplementationStatus:
  status_id          : str
  document_id        : str
  provision_id       : str   # optionnel — si à l'échelle d'une disposition
  status             : str   # 'NOT_REQUIRED' | 'PENDING' | 'PARTIAL' | 'IMPLEMENTED' | 'UNKNOWN'
  implementing_texts : list  # IDs des textes d'application publiés
  expected_date      : str   # si connue
  source_url         : str
  last_checked       : str
```

### Modèle `WatchAlert`

```python
WatchAlert:
  alert_id        : str
  alert_type      : str   # 'NEW_VERSION' | 'SUBSTANTIVE_CHANGE' | 'NEW_JURISPRUDENCE'
                          # 'IMPLEMENTATION_PUBLISHED' | 'SOURCE_DRIFT'
  severity        : str   # 'HIGH' | 'MEDIUM' | 'LOW'
  document_id     : str
  version_id      : str   # version déclenchante
  detected_at     : str   # ISO 8601
  diff_id         : str   # optionnel — si lié à un diff
  description     : str
  requires_human_review : bool
```

---

## V0.9 — Accès citoyen — LegalSituation (PRIORITÉ P2)

**Objectif :** Permettre à un utilisateur non juriste de partir d'une situation réelle et d'obtenir une réponse structurée, sourcée et honnête sur ses droits et démarches possibles.

**Prérequis obligatoire :** corpus V0.5 validé + LegalConcept V0.6 opérationnel.

### Modèle `LegalSituation`

```python
LegalSituation:
  situation_id  : str
  description   : str   # formulation libre de l'utilisateur
  domain        : str   # 'housing' | 'employment' | 'family' | 'consumer' | ...
  jurisdiction  : str
  concepts      : list  # LegalConcept IDs extraits
  query_language: str
  created_at    : str
```

### Modèle `LegalProcedure`

```python
LegalProcedure:
  procedure_id      : str
  domain            : str
  jurisdiction      : str
  legal_basis       : list  # version_ids des textes sources
  steps             : list  # ProcedureStep[]
  deadlines         : list  # Deadline[]
  competent_court   : str
  eligibility       : list  # EligibilityCondition[]
  forms_required    : list  # formulaires types
  certified_human   : bool  # True si validé par juriste
  last_verified     : str
  certainty_level   : str   # hérité des invariants JUSLIB
```

### Invariant accès citoyen

```
⚠️ INFORMATION JURIDIQUE ≠ CONSEIL JURIDIQUE INDIVIDUALISÉ

Tout résultat produit par le moteur LegalSituation est obligatoirement accompagné de :
  - la liste des sources (version_id + canonical_content_hash)
  - le niveau de certitude (CERTAIN / INTERPRETED / CONTESTED / UNVERIFIED)
  - l'avertissement : "Cette information ne remplace pas une consultation avec un avocat"
  - l'indicateur de fraîcheur des données utilisées
```

---

## V1.0 — Bibliothèque juridique opérationnelle

**Critères d'entrée en V1.0 (tous obligatoires) :**

| Critère | Mesure |
|---------|--------|
| Corpus réel | ≥ 10 000 documents ingérés, ≥ 1 000 validés humainement |
| Fraîcheur | Synchronisation automatique sur ≥ 4 sources officielles |
| Graphe | ≥ 2 000 relations vérifiées |
| Couverture multi-langues | ≥ 5 langues sur le corpus principal |
| Interopérabilité | ELI/ECLI mappés sur ≥ 80% des documents UE |
| Tests | ≥ 500 tests PASS (synthétiques + réels) |
| Validation humaine | ≥ 10% du corpus en statut `HUMAN_REVIEWED` ou `CERTAIN` |

---

## V2.0 — IA jurisprudentielle avancée

**Condition d'entrée :** V1.0 complète, corpus validé, graphe dense.

### Fonctions prévues

- Détection automatique de divergences interprétatives (niveau 1 : textuelle)
- Alertes de revirement jurisprudentiel avec score de divergence
- RAG juridique (Retrieval-Augmented Generation) sur corpus certifié
- Raisonnement assisté avec chaîne de preuves traçable
- Détection des `OBITER_DICTUM` par modèle NLP entraîné

### Règle immuable IA

```
TOUTE production IA est obligatoirement :
  1. Distinguée de la source normative (production_type ≠ 'source')
  2. Accompagnée de sa chaîne de preuves (version_ids)
  3. Marquée avec son niveau de certitude
  4. Soumise à validation humaine avant passage en CERTAIN
  5. Non présentable comme "conseil juridique"
```

---

## V3.0 — Infrastructure ouverte

- API publique documentée (OpenAPI 3.1)
- Partenariats institutionnels (barreaux, maisons de la justice, universités)
- Processus de certification des données (comité indépendant)
- Gouvernance ouverte du corpus (contributions externes contrôlées)
- `CERTIFIED_100` éventuellement passable à `true` sur des sous-corpus certifiés

---

## Métriques de suivi transversales

À exposer en permanence via `GET /v1/stats` :

```json
{
  "corpus_coverage": {
    "total_documents": N,
    "real_documents": K,
    "synthetic_only": N - K,
    "human_verified_pct": V
  },
  "freshness": {
    "oldest_sync_days": D,
    "sources_active": S,
    "sources_degraded": G
  },
  "integrity": {
    "hash_verified_pct": H,
    "versions_with_canonical_hash": VH
  },
  "graph": {
    "relations_total": R,
    "relations_verified": RV,
    "jurisprudence_with_ratio": J
  },
  "certified_100": false,
  "unique_human_proven": false,
  "debug_mode": true
}
```

---

## Invariants transversaux (non négociables — toutes versions)

1. **Toute information juridique doit avoir une source identifiable** — jamais de texte sans `source_url` + `canonical_content_hash`
2. **Une version historique ne doit jamais être écrasée** — INSERT-only, triggers SQLite
3. **Toute explication reste reliée au texte qu'elle explique** — FK non nullable
4. **Toute modification du corpus est traçable** — `ConnectorRun` + `manifest_hash` + tag Git
5. **Une production IA est toujours distinguable de la source juridique** — `production_type` + `ai_warning` obligatoire
6. **Le système distingue CERTAIN / INTERPRÉTÉ / CONTESTÉ / NON VÉRIFIÉ** — `certainty_level` sur chaque enregistrement
7. **Une traduction n'est jamais une source normative** — `is_normative_source = 0`, contrainte SQL, non dérogeable
8. **`CERTIFIED_100=false` tant que l'AND complet n'est pas atteint** — ne jamais mentir sur l'état du corpus

---

*ROADMAP_JUSLIB.md — v1.0 — 2026-10-04 — Mode DEBUG actif — `CERTIFIED_100=false`*
