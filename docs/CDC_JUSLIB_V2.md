# JUSLIB — Cahier des charges étendu V2.0

> **Document :** CDC_JUSLIB_V2.md  
> **Version :** 2.0 — 2026-10-04  
> **Statut :** Spécification opérationnelle — Mode DEBUG actif  
> `CERTIFIED_100=false` | `unique_human_proven=false`  
> Base : audit des 5 axes d'impact réel + analyse des exigences manquantes

---

## Préambule — Ce que ce CDC corrige

Le CDC V0.1 décrivait une **architecture d'intégrité documentaire**.  
Le CDC V2.0 étend cette architecture pour en faire une **infrastructure de connaissance juridique exploitable**.

La différence est fondamentale :

| CDC V0.1 | CDC V2.0 |
|----------|----------|
| "Les textes juridiques sont stockés avec un hash" | "Les textes juridiques sont stockés, surveillés, validés et reconstruisibles" |
| "La traduction est liée à une version" | "La traduction signale explicitement les faux amis juridiques inter-systèmes" |
| "Le diff est disponible" | "Le diff distingue changement formel et changement substantiel d'obligation" |
| "Le corpus est versionné" | "La santé du corpus est visible en temps réel avec métriques de confiance" |
| "L'accès grand public est prévu en V1" | "L'accès grand public repose sur une chaîne situation → textes → procédure → sources" |

**Invariant méta :** toute fonction prévue dans ce CDC doit être accompagnée d'un critère de test concret, mesurable et vérifiable. Une fonction non testée n'est pas une fonction.

---

## 1. Périmètre fonctionnel global

### 1.1 Cinq axes d'impact

| Axe | Problème juridique réel | Module principal |
|-----|------------------------|-----------------|
| **A1** — Accès à la justice | Un citoyen ne comprend pas le droit applicable à sa situation | `access_to_justice/` |
| **A2** — Fiabilité des sources | Un corpus juridique peut être périmé ou partiellement erroné sans que l'utilisateur le sache | `corpus_health/` |
| **A3** — Contradictions jurisprudentielles | Deux décisions semblent contradictoires mais ne sont pas correctement analysées | `jurisprudence/` |
| **A4** — Veille juridique | Un texte important change sans que le juriste soit alerté | `watch/` |
| **A5** — Interopérabilité | Un concept juridique traduit littéralement peut trahir son sens dans un autre système de droit | `concepts/` |

### 1.2 Principe de non-substitution

> JUSLIB fournit de l'**information juridique structurée et sourcée**.  
> JUSLIB ne fournit **jamais de conseil juridique individualisé**.  
>
> Cette distinction doit être :
> - enforced dans le code (champ `is_legal_advice = 0`, contrainte SQL non dérogeable)
> - visible dans chaque réponse API
> - documentée dans tout contrat d'utilisation

---

## 2. Axe A1 — Accès à la justice

### 2.1 Problème

L'accès à la justice est limité par deux barrières :
- **Barrière lexicale** : le droit est écrit pour des juristes
- **Barrière procédurale** : connaître le texte ne suffit pas — il faut savoir quoi faire

### 2.2 Nouveaux modèles

#### `LegalSituation`

```
situation_id        : str       UUID JUSLIB
description         : str       formulation libre de l'utilisateur
domain              : str       'housing' | 'employment' | 'family' | 'consumer' | 'criminal' | ...
jurisdiction        : str       juridiction déduite ou précisée
fact_date           : str       date des faits (pour le snapshot temporel)
extracted_concepts  : list      LegalConcept IDs extraits automatiquement
query_language      : str
certainty_level     : str       CERTAIN | INTERPRETED | CONTESTED | UNVERIFIED
created_at          : str       ISO 8601
is_legal_advice     : int       0 — JAMAIS 1 — contrainte SQL CHECK(is_legal_advice = 0)
```

#### `LegalProcedure`

```
procedure_id        : str
domain              : str
jurisdiction        : str
legal_basis         : list      version_ids des textes sources vérifiés
steps               : list      ProcedureStep[]
deadlines           : list      Deadline[]
competent_court     : str
min_amount          : float     seuil minimum si applicable
max_amount          : float     seuil maximum si applicable
eligibility         : list      EligibilityCondition[]
forms_required      : list      formulaires types avec URL officielle
last_verified       : str
certified_human     : bool      True si validé par juriste professionnel
certainty_level     : str
is_legal_advice     : int       0 — contrainte SQL
```

#### `ProcedureStep`

```
step_id             : str
procedure_id        : str       FK
order_index         : int
action              : str
deadline_days       : int       délai en jours depuis le fait déclencheur
deadline_type       : str       'calendar' | 'working' | 'months'
deadline_basis      : str       version_id de la disposition source
form_url            : str       URL officielle du formulaire
jurisdiction        : str
```

#### `Deadline`

```
deadline_id         : str
procedure_id        : str       FK
label               : str
duration_type       : str       'prescription' | 'forclusion' | 'delai_recours' | 'delai_garde'
duration_value      : int
duration_unit       : str       'days' | 'months' | 'years'
legal_basis         : str       version_id de la disposition source
exceptions          : list      conditions de suspension ou interruption
```

### 2.3 Accessibilité hors-ligne (OHADA prioritaire)

Pour les zones à faible bande passante (17 États OHADA) :

- Export du corpus en bundle hors-ligne (SQLite + JSON compressé)
- API en mode dégradé : pas de temps réel, corpus figé à la date d'export
- Indicateur de version du bundle : `bundle_date` + `corpus_version`
- Avertissement automatique si bundle > 90 jours : "Ces données datent de X — vérifier sur la source officielle"

### 2.4 Exigences testables A1

| ID | Exigence | Test |
|----|----------|------|
| A1-E01 | `LegalSituation` ne peut jamais avoir `is_legal_advice = 1` | Test SQL + test API |
| A1-E02 | `LegalProcedure` contient au minimum 1 `legal_basis` vérifiée | Assertion sur chaque procédure |
| A1-E03 | Toute réponse CITIZEN inclut `certainty_level` et `sources[]` | Test endpoint API |
| A1-E04 | Tout `Deadline` est lié à un `version_id` source | FK non nullable |
| A1-E05 | Bundle hors-ligne inclut `bundle_date` et avertissement si > 90j | Test génération bundle |

---

## 3. Axe A2 — Fiabilité et santé du corpus

### 3.1 Problème

`CERTIFIED_100=false` n'est pas un avertissement suffisant si l'utilisateur ne sait pas :
- Depuis quand les données n'ont pas été vérifiées
- Combien de documents sont dans quel état
- Si le connecteur qui l'alimente fonctionne encore

### 3.2 Modèle `CorpusHealth`

```
source_id              : str
jurisdiction           : str
last_sync_attempted    : str
last_sync_success      : str
last_sync_error        : str       message d'erreur ou None
total_documents        : int
total_versions         : int
docs_unverified        : int
docs_automated_checked : int
docs_human_reviewed    : int
docs_certain           : int
docs_contested         : int
docs_rejected          : int
failure_rate           : float     [0,1]
freshness_days         : int       calculé en temps réel
connector_status       : str       'active' | 'degraded' | 'down' | 'unknown'
```

### 3.3 Workflow de validation humaine

```
NON_VERIFIED
     │  (import automatique)
     ▼
AUTOMATED_CHECKED    ← hash vérifié, structure parsée, période temporelle cohérente
     │  (intervention humaine)
     ▼
HUMAN_REVIEWED
     │
     ├──→ CERTAIN       ← contenu confirmé exact — juriste professionnel
     ├──→ CONTESTED     ← divergence identifiée, signalée
     └──→ REJECTED      ← document erroné (préservé dans l'historique)
```

**Invariant :** jamais de passage automatique `NON_VERIFIED` → `CERTAIN`.

### 3.4 Modèle `HumanValidation`

```
validation_id                  : str
document_id                    : str
version_id                     : str
validator_id                   : str       identifiant pseudonyme
validated_at                   : str
previous_status                : str
new_status                     : str
source_checked                 : str       URL officielle consultée
canonical_hash_at_validation   : str
notes                          : str
is_normative_check             : bool      True = juriste professionnel
```

### 3.5 Validation croisée automatique

À intervalles réguliers (`ConnectorRun` planifié) :

1. Récupérer le texte depuis la source officielle
2. Calculer son hash
3. Comparer avec `canonical_content_hash` stocké
4. Si divergence → déclencher `WatchAlert` type `SOURCE_DRIFT`
5. Passer le statut à `AUTOMATED_CHECKED` en attente de validation humaine

Ce mécanisme détecte les **dérives silencieuses** : texte modifié côté source sans que JUSLIB l'ait ingéré.

### 3.6 Tests de non-régression juridique

Au-delà des tests pytest techniques, des tests qui vérifient qu'un contenu juridique connu est intact :

```python
def test_rgpd_article_5_content_unchanged():
    """Vérifie que l'article 5 RGPD contient bien les 7 principes listés."""
    v = db.get_latest_version(celex_id="32016R0679", provision="5")
    assert "licite" in v["text"] and "loyale" in v["text"]
    assert v["canonical_content_hash"] == EXPECTED_HASH_RGPD_ART5
```

### 3.7 Exigences testables A2

| ID | Exigence | Test |
|----|----------|------|
| A2-E01 | `CorpusHealth.freshness_days` calculé en temps réel, pas en cache | Test avec DB fraîche et date manipulée |
| A2-E02 | `CERTAIN` impossible sans `HumanValidation.is_normative_check=True` | Test SQL + test API |
| A2-E03 | `SOURCE_DRIFT` déclenché si hash source ≠ hash stocké | Test de détection de dérive |
| A2-E04 | `REJECTED` ne supprime pas la version (INSERT-only) | Test d'historique après rejet |
| A2-E05 | `GET /v1/corpus/health` retourne `failure_rate` et `freshness_days` | Test endpoint |

---

## 4. Axe A3 — Contradictions jurisprudentielles

### 4.1 Problème

Une vraie contradiction jurisprudentielle ne peut être détectée que sur des `RATIO_DECIDENDI`, pas sur des `OBITER_DICTUM`. Deux décisions peuvent utiliser des formulations incompatibles sans être réellement contradictoires.

### 4.2 Modèle `JurisprudenceSegment`

```
segment_id     : str
version_id     : str       FK → LegalVersion (de la décision)
segment_type   : str       'RATIO_DECIDENDI' | 'OBITER_DICTUM' | 'PROCEDURAL'
                           'FACTUAL' | 'BACKGROUND' | 'UNKNOWN'
text_excerpt   : str
start_char     : int
end_char       : int
canonical_hash : str
annotated_by   : str       'automated' | identifiant humain
confidence     : float     [0,1] — pour annotations automatiques
```

### 4.3 Niveaux de contradiction

| Niveau | Définition | Affichage |
|--------|------------|-----------|
| **L1 — Textuelle** | Formulations incompatibles détectées | "Divergence textuelle suspectée" |
| **L2 — Interprétative** | Deux juridictions interprètent différemment une même norme | "Divergence interprétative identifiée" |
| **L3 — Revirement** | Une juridiction modifie explicitement une ligne antérieure | "Revirement potentiel — validation requise" |

**Invariant :** jamais de déclaration automatique de "contradiction juridiquement établie". Toujours "suspectée" + `requires_human_review = true`.

### 4.4 Portée temporelle des décisions

Les contradictions apparentes entre deux décisions peuvent résulter de périodes d'application différentes.

```
JurisprudenceSegment.temporal_scope : str   # JSON — période d'application
```

Avant de déclarer une contradiction, le moteur vérifie que les deux décisions s'appliquent à la même période.

### 4.5 Modèle `ContradictionSuspect`

```
suspect_id          : str
segment_a_id        : str       FK → JurisprudenceSegment (RATIO_DECIDENDI)
segment_b_id        : str       FK → JurisprudenceSegment (RATIO_DECIDENDI)
level               : str       'L1' | 'L2' | 'L3'
divergence_score    : float     [0,1]
temporal_overlap    : bool      True si les deux décisions s'appliquent à la même période
requires_review     : bool      True — toujours
status              : str       'SUSPECTED' | 'CONFIRMED' | 'DISMISSED'
reviewed_by         : str       identifiant humain si CONFIRMED/DISMISSED
reviewed_at         : str
```

### 4.6 Exigences testables A3

| ID | Exigence | Test |
|----|----------|------|
| A3-E01 | Contradiction détectable uniquement sur `RATIO_DECIDENDI` | Test : `OBITER_DICTUM` ne génère pas de `ContradictionSuspect` |
| A3-E02 | `ContradictionSuspect.requires_review` toujours `True` à la création | Invariant SQL |
| A3-E03 | Deux décisions sur des périodes non chevauchantes ne génèrent pas de suspect | Test temporel |
| A3-E04 | `CONFIRMED` requiert un `reviewed_by` non vide | Test validation humaine |

---

## 5. Axe A4 — Veille juridique

### 5.1 Problème

Un diff textuel brut ne permet pas de prioriser la lecture. Un juriste a besoin de savoir si un changement modifie une obligation, un droit ou simplement une référence.

### 5.2 Catégorisation des diffs

```
LegalDiffEntry:
  diff_id              : str
  version_from_id      : str
  version_to_id        : str
  change_category      : str   'FORMAL' | 'STRUCTURAL' | 'SUBSTANTIVE'
  change_type          : str   'ADDITION' | 'DELETION' | 'MODIFICATION' | 'RENUMBERING'
  affected_text_from   : str
  affected_text_to     : str
  interpretation_hint  : str   ex: "'peut' → 'doit' : création d'obligation"
  requires_review      : bool  True si SUBSTANTIVE
  diff_hash            : str   hash du diff pour traçabilité
```

| Catégorie | Exemples | Priorité |
|-----------|----------|---------|
| `FORMAL` | ponctuation, casse, renvois | Basse |
| `STRUCTURAL` | renumérotation, fusion/scission d'articles | Moyenne |
| `SUBSTANTIVE` | "peut" → "doit", ajout/suppression d'obligation | Haute |

### 5.3 Modèle `ImplementationStatus`

```
status_id            : str
document_id          : str
provision_id         : str       optionnel
status               : str       'NOT_REQUIRED' | 'PENDING' | 'PARTIAL' | 'IMPLEMENTED' | 'UNKNOWN'
implementing_texts   : list      version_ids des textes d'application publiés
expected_date        : str       si connue
official_deadline    : str       délai légal d'application si prescrit
source_url           : str
last_checked         : str
```

### 5.4 Modèle `WatchAlert`

```
alert_id             : str
alert_type           : str   'NEW_VERSION' | 'SUBSTANTIVE_CHANGE' | 'NEW_JURISPRUDENCE'
                             'IMPLEMENTATION_PUBLISHED' | 'SOURCE_DRIFT' | 'CONNECTOR_DOWN'
severity             : str   'HIGH' | 'MEDIUM' | 'LOW'
document_id          : str
version_id           : str
detected_at          : str   ISO 8601
diff_id              : str   optionnel
description          : str
requires_human_review: bool
acknowledged         : bool
acknowledged_by      : str
acknowledged_at      : str
```

### 5.5 Fréquence de synchronisation par source

| Source | Fréquence maximale | Notes |
|--------|-------------------|-------|
| EUR-Lex (SPARQL) | Quotidienne | API publique sans limite documentée |
| Légifrance (PISTE) | Quotidienne | OAuth2 — respecter les quotas |
| HUDOC (CEDH) | Hebdomadaire | Pas d'API temps réel officielle |
| CanLII | Hebdomadaire | Accord requis pour accès intensif |
| OHADA | Mensuelle | Site institutionnel — pas d'API dédiée |
| ONU ODS | Mensuelle | Archive — peu de mises à jour fréquentes |

### 5.6 Exigences testables A4

| ID | Exigence | Test |
|----|----------|------|
| A4-E01 | `SUBSTANTIVE` génère `requires_review = True` | Invariant |
| A4-E02 | `WatchAlert` sévérité `HIGH` pour `SUBSTANTIVE_CHANGE` | Test de classification |
| A4-E03 | `ImplementationStatus.PENDING` déclenche alerte si `expected_date` dépassée | Test de date |
| A4-E04 | `ConnectorRun` en échec → `WatchAlert` type `CONNECTOR_DOWN` | Test de failure |

---

## 6. Axe A5 — Interopérabilité entre juridictions

### 6.1 Problème

Agréger France + UE + Canada + OHADA sans couche de correspondance conceptuelle produit une simple juxtaposition de textes, pas une bibliothèque comparable.

### 6.2 Modèle `LegalConcept`

```
concept_id             : str
canonical_label        : str    EN — libellé de référence
definition             : str
legal_system           : str    'civil_law' | 'common_law' | 'mixed' | 'religious' | 'customary'
jurisdiction           : str
domain                 : str    'contract' | 'tort' | 'property' | 'procedural' | 'criminal' | ...
source_url             : str    définition officielle de référence
canonical_content_hash : str
```

### 6.3 Modèle `ConceptTerm`

```
term_id      : str
concept_id   : str    FK
language     : str    'fr' | 'en' | 'ar' | 'es' | 'pt' | ...
term         : str
term_type    : str    'preferred' | 'synonym' | 'false_friend' | 'broader' | 'narrower'
note         : str    avertissement obligatoire si term_type = 'false_friend'
```

### 6.4 Modèle `ConceptEquivalence`

```
equivalence_id     : str
concept_a_id       : str    FK → LegalConcept
concept_b_id       : str    FK → LegalConcept
equivalence_level  : str    'EXACT' | 'FUNCTIONAL' | 'PARTIAL' | 'ANALOGOUS' | 'NO_EQUIVALENT'
direction          : str    'bidirectional' | 'a_to_b' | 'b_to_a'
limitations        : str    description des limites de l'équivalence
source_url         : str
validated_by       : str    identifiant validateur humain obligatoire
```

### 6.5 Identifiants normalisés

```
LegalIdentifier:
  identifier_id   : str
  juslib_id       : str    FK interne JUSLIB
  standard        : str    'ELI' | 'ECLI' | 'CELEX' | 'HUDOC' | 'CANLII' | 'OHADA_REF' | 'DOI'
  value           : str
  verified        : bool   cross-vérifié avec source officielle
  verified_at     : str
  verified_by     : str
```

**Règle absolue :** l'identifiant JUSLIB interne ne remplace jamais un identifiant officiel. Les deux coexistent. La correspondance est traçable et vérifiable.

### 6.6 Avertissements de traduction juridique

Pour toute traduction (`TranslationRecord`) dont la `target_language` implique un changement de système juridique :

```python
translation_warning : str   # "Attention : ce terme peut ne pas avoir d'équivalent exact
                            # dans le système de droit cible. Voir ConceptEquivalence."
concept_equivalence_id : str  # FK si disponible
```

### 6.7 Exigences testables A5

| ID | Exigence | Test |
|----|----------|------|
| A5-E01 | `ConceptEquivalence` ne peut être validé sans `validated_by` non vide | Invariant |
| A5-E02 | `false_friend` requiert un `note` explicatif non vide | Contrainte SQL |
| A5-E03 | ELI/ECLI mappés ne remplacent pas le `juslib_id` — les deux coexistent | Test de coexistence |
| A5-E04 | Traduction inter-système déclenche `translation_warning` si `ConceptTerm.term_type = 'false_friend'` | Test API |

---

## 7. Gouvernance du corpus

### 7.1 Comité de validation

Tout passage de `AUTOMATED_CHECKED` à `CERTAIN` requiert :
- Un validateur avec `is_normative_check=True` (juriste professionnel)
- Une source officielle consultée et loggée dans `source_checked`
- Un `canonical_hash_at_validation` correspondant au hash stocké

### 7.2 Contributions externes (V3.0)

Avant d'accepter une contribution externe au corpus :
- Vérification de la source (URL officielle)
- Calcul du hash et comparaison
- Statut initial : `NON_VERIFIED` (jamais `CERTAIN` d'office)
- Audit de la contribution dans `ConnectorRun` avec `contributor_id`

### 7.3 Politique de rétention

- Les versions `REJECTED` sont conservées dans la table `legal_versions` avec `version_status = 'rejected'`
- Elles ne sont jamais retournées dans les endpoints de corpus actif
- Elles restent accessibles via l'API d'audit historique (`/v1/version/{id}/history`)

---

## 8. Indicateurs de qualité globaux

Ces indicateurs doivent être mesurables en permanence via l'API et dans le tableau de bord :

| Indicateur | Formule | Seuil V1.0 |
|------------|---------|------------|
| **Coverage** | `real_docs / total_docs` | ≥ 80% |
| **Freshness** | max(`freshness_days` par source) | ≤ 30 jours |
| **Integrity** | `hash_verified / total_versions` | ≥ 95% |
| **Authority** | `official_source_docs / total_docs` | 100% |
| **Validation** | `human_reviewed / total_docs` | ≥ 10% en V1.0 |
| **Temporal completeness** | `docs_with_valid_from / total_versions` | ≥ 90% |
| **Relationship coverage** | `docs_with_relations / total_docs` | ≥ 20% en V1.0 |

---

## 9. API — nouveaux endpoints prévus

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/v1/corpus/health` | Santé corpus toutes sources |
| `GET` | `/v1/corpus/health/{source_id}` | Santé d'une source |
| `POST` | `/v1/situation` | Créer une LegalSituation |
| `GET` | `/v1/situation/{id}` | Récupérer une LegalSituation avec textes associés |
| `GET` | `/v1/procedure/{domain}/{jurisdiction}` | Procédure applicable |
| `GET` | `/v1/concept/{concept_id}` | Concept juridique + termes + équivalences |
| `GET` | `/v1/concept/search?q={term}&lang={lang}` | Recherche de concepts |
| `POST` | `/v1/validation` | Enregistrer une HumanValidation |
| `GET` | `/v1/diff/{from_id}/{to_id}` | Diff juridique catégorisé |
| `GET` | `/v1/diff/{from_id}/{to_id}/substantive` | Seulement les changements SUBSTANTIVE |
| `GET` | `/v1/alerts` | WatchAlerts actives |
| `GET` | `/v1/alerts/{document_id}` | Alertes pour un document |
| `GET` | `/v1/jurisprudence/{version_id}/segments` | Segments ratio/obiter |
| `GET` | `/v1/contradiction/suspects` | ContradictionSuspect ouverts |
| `GET` | `/v1/implementation/{document_id}` | Statut des décrets d'application |
| `GET` | `/v1/stats` | Métriques de qualité globales |
| `GET` | `/v1/identifier/{juslib_id}/external` | ELI/ECLI/CELEX mappés |

---

## 10. Exigences transversales non fonctionnelles

### 10.1 Performance

| Endpoint | Latence cible (corpus ≤ 100k documents) |
|----------|----------------------------------------|
| `GET /v1/version/{id}` | < 50ms |
| `GET /v1/snapshot/{doc_id}?on_date=...` | < 200ms |
| `GET /v1/search?q=...` | < 500ms (FTS5) |
| `GET /v1/corpus/health` | < 1s |

### 10.2 Sécurité

- Aucune donnée personnelle dans le corpus juridique
- Les `validator_id` sont des pseudonymes — pas d'identité réelle stockée
- Les `WatchAlert` ne contiennent jamais d'information sensible sur l'utilisateur final
- Les clés d'API (connecteurs) ne transitent jamais dans les réponses

### 10.3 Observabilité

- Chaque `ConnectorRun` est loggé en JSON dans `logs/`
- Chaque `HumanValidation` est enregistrée et non modifiable
- Chaque `WatchAlert` a un `detected_at` non modifiable
- `CERTIFIED_100=false` reste dans tous les en-têtes de réponse API tant que l'AND complet n'est pas atteint

---

## 11. Critères d'acceptation généraux

Un module est considéré **opérationnel** (et non simplement "prévu") quand :

1. Les modèles de données sont implémentés avec leurs contraintes SQL
2. Les triggers INSERT-only s'appliquent aux nouvelles tables versionnées
3. Les endpoints API retournent les données attendues avec les invariants respectés
4. ≥ 5 tests automatisés couvrent les cas normaux ET les cas d'invariant (interdictions)
5. Au moins un jeu de données **réelles** (pas synthétiques) a été ingéré et tracé
6. Le `certainty_level` est présent sur chaque enregistrement retourné
7. L'`ai_warning` est présent si `production_type ≠ 'source'`

---

*CDC_JUSLIB_V2.md — v2.0 — 2026-10-04 — Mode DEBUG actif — `CERTIFIED_100=false`*
