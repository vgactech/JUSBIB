# JUSLIB — Rapport R002 : Corrections P0 post-audit v0.1.0

**Date :** 2026-10-04  
**Session :** J002 — Corrections P0 suite audit expert R002  
**Commit :** (en cours de création)  
**Version :** 0.1.1  
**Mode DEBUG actif** | `CERTIFIED_100=false`

---

## Contexte

Audit expert reçu (R002) sur JUSLIB v0.1.0 (commit `d1ec32d`).  
Verdict : **NO-GO pour usage juridique professionnel / GO pour V0.2** sous réserve de corrections P0.  
Ce rapport documente chaque correction P0 appliquée.

---

## Résultats tests avant / après

| Version | Tests PASS | Tests FAIL |
|---------|-----------|-----------|
| V0.1.0 (d1ec32d) | 49 | 0 |
| **V0.1.1 (ce commit)** | **69** | **0** |

20 nouveaux tests ajoutés (blocs F et G).

---

## Corrections P0 appliquées

### P0-01 — Sécurisation `/v1/explain` ✅

**Problème R002 :** Un client pouvait fournir un texte libre et recevoir `is_source_text=True` + `production_type=source` + `confidence=1.0`.  
**Correction :**

**AVANT** ([`api/main.py`](../src/juslib/api/main.py) — lignes supprimées) :
```python
class ExplainRequest(BaseModel):
    source_entity_id: str
    text: str  # ← texte libre client accepté
    reading_level: str = "citizen"
```
Retournait `is_source_text=True` si `reading_level="expert"`.

**APRÈS** :
- `POST /v1/explain` → `ExplainFromCorpusRequest` : résout l'ID dans `_CORPUS_REGISTRY`, charge le texte, vérifie le hash. Lève HTTP 404 si l'ID n'existe pas.
- `POST /v1/explain/text` → `ExplainTextRequest` : `expert` interdit par validation Pydantic. `is_source_text=False` forcé. `confidence≤0.5` automatique. Avertissement obligatoire.
- Vérification hash intégrité corpus : si `SHA-256(texte)≠stored_hash` → HTTP 500 `CORPUS_INTEGRITY_FAILURE`.

---

### P0-02 — LegalVersion + LegalProvision ✅

**Problème R002 :** Hiérarchie `LegalDocument → revision` insuffisante pour modéliser abrogation partielle, entrée en vigueur différée, consolidation.

**AVANT :** Champs `revision` + `previous_version_id` dans `LegalDocument`.

**APRÈS** : Nouveau fichier [`src/juslib/models/legal_version.py`](../src/juslib/models/legal_version.py)

```
LegalDocument → LegalProvision → LegalVersion
```

Champs `LegalVersion` : `text`, `valid_from`, `valid_until`, `raw_source_hash`, `canonical_content_hash`, `change_type`, `amending_document_id`, `is_in_force(date)`, `verify_integrity()`.

9 tests F01→F09 PASS.

---

### P0-03 — Séparation raw_source_hash / canonical_content_hash ✅

**Problème R002 :** Un seul champ `source_hash` — impossible de distinguer le hash du HTML brut récupéré du hash du texte normalisé.

**AVANT :** `LegalDocument.source_hash` (un seul hash, usage ambigu).

**APRÈS** dans `LegalVersion` :
```python
raw_source_hash: str        # SHA-256(contenu brut HTTP — avant parsing)
canonical_content_hash: str # SHA-256(texte normalisé — NFC + whitespace collapse)
```

`compute_canonical_hash()` + `verify_integrity()` vérifient la cohérence.  
Test G11 : les deux hashes coexistent et sont différents (contenu HTML brut ≠ texte normalisé).

---

### P0-04 — Suppression du faux `AI_GENERATED` ✅

**Problème R002 :** `_enrich_with_llm()` déclarait `production_type="ai_generated"` sans avoir contacté aucun LLM.

**AVANT** ([`translation/plain_language.py`](../src/juslib/translation/plain_language.py)) :
```python
result.production_type = "ai_generated"  # faux — aucun LLM appelé
```

**APRÈS :**
```python
# Sans BOB_API_KEY → reste RULE_BASED (jamais de faux LLM_GENERATED)
api_key = os.getenv("BOB_API_KEY") or os.getenv("OPENROUTER_API_KEY")
if not api_key:
    return result  # production_type inchangé = rule_based
result.production_type = "llm_generated"  # seulement si clé présente
```

Nouveau `ProductionType` : `RULE_BASED`, `LLM_GENERATED`, `LLM_VALIDATED`, `HUMAN_AUTHORED`, `HUMAN_VALIDATED`.  
`AI_GENERATED` et `AI_VALIDATED` conservés mais **marqués DÉPRÉCIÉ**.  
Tests G01 + G02 PASS.

---

### P0-05 — Légifrance OAuth URLs sandbox / production ✅

**Problème R002 :** OAuth URL mixait sandbox (`sandbox-oauth.piste.gouv.fr`) et API production (`api.piste.gouv.fr`). Incohérent.

**AVANT** ([`connectors/legifranceconnector.py`](../src/juslib/connectors/legifranceconnector.py)) :
```python
PISTE_TOKEN_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"  # sandbox
PISTE_API_BASE  = "https://api.piste.gouv.fr/..."                        # production ← MÉLANGE
```

**APRÈS :**
```python
_PISTE_ENVS = {
    "sandbox":    {"token_url": "https://oauth.sandbox-aife.economie.gouv.fr/...",
                   "api_base":  "https://sandbox-api.piste.gouv.fr/..."},
    "production": {"token_url": "https://oauth.aife.economie.gouv.fr/...",
                   "api_base":  "https://api.piste.gouv.fr/..."},
}
# Sélection via LEGIFRANCE_PISTE_ENV=sandbox|production
```

Tests G03 + G04 PASS.

---

### P0-06 — CanLII reclassifié en source secondaire ✅

**Problème R002 :** CanLII présenté comme source officielle alors qu'il indique lui-même que ses copies ne sont pas nécessairement dotées d'une valeur officielle.

**AVANT :** README : « Sources officielles couvertes — CanLII ».

**APRÈS :**
- `SOURCE_CLASSIFICATION = "SECONDARY_AGGREGATOR"` ajouté dans [`CanLIIConnector`](../src/juslib/connectors/canlii_connector.py)
- Docstring corrigée avec références aux vraies sources officielles canadiennes (laws-lois.justice.gc.ca, legisquebec.gouv.qc.ca)

Test G05 PASS.

---

### P0-07 — OHADA → ohada.org (institutionnel) ✅

**Problème R002 :** Le connecteur utilisait `ohada.com` (site tiers non institutionnel). L'OHADA publie sur `ohada.org`.

**AVANT :** `OHADA_BASE_URL = "https://www.ohada.com"`

**APRÈS :** `OHADA_BASE_URL = "https://www.ohada.org"`  
`OHADA_ACTES_BASE = "https://www.ohada.org/actes-uniformes"` (URL officielle réelle)  
`OHADA_JO_BASE = "https://www.ohada.org/journal-officiel"` (Journal Officiel OHADA ajouté)

Test G06 PASS.

---

### P0-08 — Versionnement : bug max+1 + UUID changelog ✅

**Problème 1 R002 :** `generate_version_label()` utilisait `len(same_day)+1` — une séquence `[001, 003]` aurait généré `003` de nouveau.

**AVANT :**
```python
rev = len(same_day) + 1  # bug : count au lieu de max
```

**APRÈS :**
```python
next_rev = (max(revisions) + 1) if revisions else 1  # max existant + 1
```

**Problème 2 R002 :** Suffixe changelog horodaté à la seconde → collision possible.

**AVANT :** `f"_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"`

**APRÈS :** `f"_{uuid.uuid4().hex[:12]}"` (12 chars hex = 48 bits d'entropie)

Tests G07 + G08 PASS.

---

### P0-09 — `LegalRelation.confidence` défaut = 0.0 ✅

**Problème R002 :** Une relation auto-créée recevait `confidence=1.0` (certitude maximale), ce qui est dangereux.

**AVANT :** `confidence: float = 1.0`

**APRÈS :** `confidence: float = 0.0` + documentation des valeurs recommandées :
- `1.0` = relation officielle explicite dans le texte
- `0.8` = établie par doctrine / jurisprudence constante
- `0.5` = probable mais non confirmée
- `0.0` = non vérifiée / extraite automatiquement (défaut)

Tests G09 + G10 PASS.

---

## Éléments P0 reconnus mais adressés partiellement

| Point R002 | État V0.1.1 |
|------------|-------------|
| FK réelles en base de données | Prévu V0.2 (SQLite + SQLAlchemy) |
| Persistance réelle | Prévu V0.2 — `_CORPUS_REGISTRY` mémoire en attendant |
| Tests API + tests réseau | Prévu V0.2 |
| `RelationEvidence` | Prévu V0.2 |
| `Authority` | Prévu V0.2 |
| `TranslationRecord` | Prévu V0.2 |
| Manifest de release signé | Prévu V0.2 |
| Moteur recherche FTS5 | Prévu V0.2 |

---

## Éléments P0 honnêtement non adressés dans V0.1.1

1. **EUR-Lex** : langues disponibles par document (pas génériques) — correction dans le connecteur nécessite requête SPARQL par document → V0.2
2. **`/v1/search`** : retourne toujours `results=[]` — moteur FTS5 requis → V0.2
3. **Signature de release** : manifest non signé — signature GPG/Ed25519 → V0.2

---

*Rapport R002 — JUSLIB v0.1.1 — 2026-10-04 — Mode DEBUG — CERTIFIED_100=false*
