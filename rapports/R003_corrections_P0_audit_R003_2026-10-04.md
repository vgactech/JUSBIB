# R003 — Corrections audit R003-P0 — JUSLIB v0.1.2

**Date :** 2026-10-04T13:31:40Z  
**Session :** J003  
**Version avant :** 0.1.1 (commit `b55d23f`)  
**Version après :** 0.1.2  
**Tests :** 69/69 → **119/119 PASS** (+50 nouveaux tests R003)  
**Certified_100 :** false  
**unique_human_proven :** false  
**Mode DEBUG :** actif  

---

## Résumé des corrections

L'audit R003 avait identifié 5 problèmes P0 sur le code V0.1.1. Ce rapport documente les corrections appliquées, les fichiers modifiés ligne par ligne, et les résultats de tests.

| Bug | Sévérité | Statut avant | Statut après |
|-----|----------|-------------|--------------|
| P0-A : URLs OAuth Légifrance incorrectes | CRITIQUE | ❌ `oauth.sandbox-aife.economie.gouv.fr` | ✅ `sandbox-oauth.piste.gouv.fr` |
| P0-B : `verify_integrity()` effet de bord | CRITIQUE | ❌ Faux succès garanti | ✅ `_compute_hash_readonly()` |
| P0-C : `source_hash` générique | ÉLEVÉ | ❌ Champ unique | ✅ `raw_source_hash` + `canonical_content_hash` |
| P0-D : `_enrich_with_llm()` mensonge métadonnée | ÉLEVÉ | ❌ `llm_generated` sans appel réel | ✅ `rule_based` conservé jusqu'à Phase 6 |
| P0-E : `_CORPUS_REGISTRY` dict mémoire | ÉLEVÉ | ❌ Pas de FK, pas de persistance | ✅ SQLite JuslibDB (8 tables, INSERT-only) |

---

## P0-A — URLs OAuth Légifrance (CRITIQUE)

### Avant (lignes 43-51 — `src/juslib/connectors/legifranceconnector.py`)

```python
_PISTE_ENVS = {
    "sandbox": {
        "token_url": "https://oauth.sandbox-aife.economie.gouv.fr/api/oauth/token",  # ❌ INCORRECT
        "api_base": "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app",
    },
    "production": {
        "token_url": "https://oauth.aife.economie.gouv.fr/api/oauth/token",           # ❌ INCORRECT
        "api_base": "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app",
    },
}
```

### Après (lignes 42-52 — `src/juslib/connectors/legifranceconnector.py`)

```python
_PISTE_ENVS = {
    "sandbox": {
        "token_url": "https://sandbox-oauth.piste.gouv.fr/api/oauth/token",           # ✅ CORRECT
        "api_base": "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app",
    },
    "production": {
        "token_url": "https://oauth.piste.gouv.fr/api/oauth/token",                   # ✅ CORRECT
        "api_base": "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app",
    },
}
```

**Source vérifiée :** https://developer.aife.economie.gouv.fr/ — documentation officielle PISTE.  
**Connecteur version :** `0.1.1` → `0.1.2`.  
**Tests H01–H06 : 6/6 PASS.**

---

## P0-B — `verify_integrity()` effet de bord (CRITIQUE)

### Description du bug

La méthode `verify_integrity()` dans [`legal_version.py`](../src/juslib/models/legal_version.py) appelait `self.compute_canonical_hash()` qui **écrasait `self.canonical_content_hash`** avant de le comparer. Résultat : tout objet dont le hash était falsifié passait la vérification avec succès (le hash falsifié était recalculé et stocké → comparaison triviale).

### Avant (lignes 103-121 — `src/juslib/models/legal_version.py`)

```python
def verify_integrity(self) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not self.raw_source_hash:
        errors.append("R002-P0-03: raw_source_hash manquant")
    if not self.canonical_content_hash:
        errors.append("R002-P0-03: canonical_content_hash manquant")
    else:
        expected = self.compute_canonical_hash()   # ❌ BUG : écrase avant compare
        if expected != self.canonical_content_hash:
            ...
```

### Après (lignes 118-148 — `src/juslib/models/legal_version.py`)

```python
def _compute_hash_readonly(self) -> str:
    """Calcule sans modifier self.canonical_content_hash (R003-P0-B)."""
    import unicodedata, re
    normalized = unicodedata.normalize("NFC", self.text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def verify_integrity(self) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not self.raw_source_hash:
        errors.append("R003-P0-B: raw_source_hash manquant")
    if not self.canonical_content_hash:
        errors.append("R003-P0-B: canonical_content_hash manquant")
    else:
        stored = self.canonical_content_hash        # ✅ lecture seule
        computed = self._compute_hash_readonly()    # ✅ jamais stocké ici
        if computed != stored:
            errors.append(...)
    return len(errors) == 0, errors
```

**Tests I01–I07 : 7/7 PASS.** Inclut 10 appels consécutifs idempotents (I05).

---

## P0-C — `source_hash` générique dans `/v1/explain` (ÉLEVÉ)

### Avant (ligne 238 — `src/juslib/api/main.py`)

```python
stored_hash = corpus_entry.get("source_hash", "")   # ❌ champ générique unique
computed_hash = hashlib.sha256(authenticated_text.encode("utf-8")).hexdigest()
```

### Après (lignes 237-249 — `src/juslib/api/main.py`)

```python
stored_canonical_hash = corpus_entry.get("canonical_content_hash") or ""  # ✅ séparé
stored_raw_hash = corpus_entry.get("raw_source_hash") or ""                # ✅ séparé
# Vérification avec NFC + collapse whitespace (cohérent avec LegalVersion)
_normalized = unicodedata.normalize("NFC", authenticated_text)
_normalized = re.sub(r"\s+", " ", _normalized).strip()
computed_canonical = hashlib.sha256(_normalized.encode("utf-8")).hexdigest()
```

**Réponse API mise à jour :** `source_hash_verified` → `raw_source_hash_present` + `canonical_hash_verified`.  
**Tests M01–M02 PASS.**

---

## P0-D — `_enrich_with_llm()` faux marquage (ÉLEVÉ)

### Avant (lignes 252-258 — `src/juslib/translation/plain_language.py`)

```python
# Clé présente → marquage llm_generated + avertissement
result.production_type = "llm_generated"  # ❌ sans appel LLM réel
result.ai_generated_warning = warning
result.confidence = 0.5
# NOTE : l'appel LLM réel sera implémenté en Phase 6
```

### Après (lignes 252-263 — `src/juslib/translation/plain_language.py`)

```python
# Clé présente MAIS appel LLM réel non encore implémenté (Phase 6).
# R003-P0-D : NE PAS marquer llm_generated sans appel réel
self._log.debug("[EXPLAIN] ... rule_based conservé jusqu'à Phase 6")
return result  # ✅ inchangé — rule_based conservé
```

**Tests J01–J04 : 4/4 PASS.** Inclut le cas `BOB_API_KEY` présente → toujours `rule_based`.

---

## P0-E — JuslibDB SQLite (ÉLEVÉ)

### Nouveau fichier créé : `src/juslib/db.py`

**Avant :** `_CORPUS_REGISTRY: dict[str, dict] = {}` — dictionnaire Python en mémoire, perdu à chaque redémarrage, sans FK, sans contraintes.

**Après :** `JuslibDB` — base SQLite avec schéma complet :

```
authorities              : sources faisant autorité (juridictions, organes)
legal_documents          : documents normatifs (ELI/CELEX/ECLI séparés)
legal_provisions         : subdivisions (articles, paragraphes)
legal_versions           : textes exacts par période (INSERT-only strict)
legal_snapshots          : vue corpus à une date (droit applicable)
relation_evidence        : preuves de relations juridiques
translation_records      : traductions vérifiées
corpus_entries           : index corpus (remplace _CORPUS_REGISTRY)
```

**Invariants enforced en base :**

| Invariant | Mécanisme SQLite |
|-----------|-----------------|
| INSERT-only documents | `BEFORE UPDATE` + `BEFORE DELETE` triggers → `RAISE(ABORT, …)` |
| INSERT-only versions | `BEFORE UPDATE` + `BEFORE DELETE` triggers |
| FK réelles | `PRAGMA foreign_keys = ON` + `REFERENCES` dans DDL |
| `source_url NOT NULL` | Contrainte DDL directe |
| `certainty_level` borné | `CHECK (certainty_level IN (…))` |
| `confidence ∈ [0,1]` | `CHECK (confidence >= 0.0 AND confidence <= 1.0)` |

**Snapshot temporel :**
```python
db.get_version_at_date(provision_id, "2019-06-01")
# → version en vigueur à cette date (valid_from ≤ date < valid_until)
db.compute_snapshot(document_id, "2024-01-01")
# → toutes les provisions avec leur version en vigueur ce jour
```

**Identifiants officiels (séparés du JUSLIB-ID interne) :**
```python
db.find_documents_by_identifier(celex_id="32016R0679")   # RGPD par CELEX
db.find_documents_by_identifier(eli_id="http://data.europa.eu/eli/reg/2016/679")
db.find_documents_by_identifier(ecli_id="ECLI:EU:C:2014:317")  # Google Spain
db.find_documents_by_identifier(native_id="LEGITEXT000006070721")  # Code civil
```

**Tests K01–K16, L01–L06, M01–M05 : 27/27 PASS.**

---

## Nouveaux endpoints API

Ajoutés dans `src/juslib/api/main.py` :

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/v1/corpus/index` | POST | Indexe un document normatif dans SQLite |
| `/v1/corpus/snapshot/{id}` | GET | Droit applicable à une date (`?on_date=YYYY-MM-DD`) |
| `/v1/db/stats` | GET | Statistiques base de données |

---

## Résultats des tests

### Suite R003 (nouveaux)
```
tests/test_juslib_r003.py — 50 tests
  H (P0-A Légifrance)     :  6/6  PASS
  I (P0-B verify_integrity):  7/7  PASS
  J (P0-D _enrich_with_llm):  4/4  PASS
  K (P0-E JuslibDB)        : 16/16 PASS
  L (ELI/CELEX/ECLI)       :  6/6  PASS
  M (Intégrité corpus)     :  5/5  PASS
  N (Non-régression R003)  :  6/6  PASS
```

### Suite complète

```
tests/test_juslib_core.py : 69/69  PASS (zéro régression)
tests/test_juslib_r003.py : 50/50  PASS (nouveaux)
─────────────────────────────────
TOTAL                     : 119/119 PASS en 1.60s
```

---

## Fichiers modifiés

| Fichier | Type | Modification |
|---------|------|-------------|
| `src/juslib/__init__.py` | Modifié | version `0.1.1` → `0.1.2`, doc R003-P0 |
| `src/juslib/connectors/legifranceconnector.py` | Modifié | P0-A : URLs OAuth piste.gouv.fr |
| `src/juslib/models/legal_version.py` | Modifié | P0-B : `_compute_hash_readonly()` + `verify_integrity()` |
| `src/juslib/translation/plain_language.py` | Modifié | P0-D : `_enrich_with_llm()` sans marquage llm_generated |
| `src/juslib/api/main.py` | Modifié | P0-C + P0-E + 3 nouveaux endpoints |
| `src/juslib/db.py` | NOUVEAU | JuslibDB SQLite complet (420 lignes) |
| `tests/test_juslib_r003.py` | NOUVEAU | 50 tests H→N |
| `tests/test_juslib_core.py` | Modifié | F05 : message d'erreur `R002-P0-03 OR R003-P0-B` |

---

## Limites documentées (honnêteté)

1. **Phase 6 LLM non implémentée :** `_enrich_with_llm()` retourne systématiquement `rule_based` jusqu'à l'implémentation réelle de l'appel IBM Bob CLI (Phase 6). Le code est structurellement prêt.

2. **FTS5 non implémenté :** `/v1/search` retourne toujours `results: []`. La recherche full-text SQLite FTS5 est prévue en Phase 7.

3. **CanLII usage restreint :** Conditions d'utilisation CanLII interdisent l'ingestion massive (décision judiciaire CanLII vs Caseway AI, nov. 2024). Usage limité à la découverte/résolution d'identifiants.

4. **DB `:memory:` par défaut :** En production, configurer `JUSLIB_DB_PATH=data/corpus/juslib.db` pour la persistance. Le défaut `:memory:` est adapté aux tests uniquement.

5. **Snapshot audit :** Les snapshots sont actuellement calculés à la demande et enregistrés dans `legal_snapshots`. Un index pré-calculé sera utile à l'échelle (Phase 8).

---

## État d'avancement global JUSLIB

| Module | État | Notes |
|--------|------|-------|
| Modèles canoniques (7) | ✅ DONE | `LegalDocument`, `LegalVersion`, `Disposition`, `Jurisprudence`, `Relation`, `Citation`, `Provenance` |
| Connecteurs (6) | ✅ DONE | EUR-Lex, Légifrance (P0-A corrigé), HUDOC, CanLII, OHADA, ONU |
| Moteur vulgarisation | ✅ DONE | 3 niveaux, glossaire 8 langues, P0-D corrigé |
| Versionnement corpus | ✅ DONE | CorpusTracker, ChangelogBuilder |
| LegalVersion temporel | ✅ DONE | P0-B corrigé, `_compute_hash_readonly()` |
| JuslibDB SQLite | ✅ DONE | 8 tables, FK, INSERT-only, Snapshot |
| ELI/CELEX/ECLI | ✅ DONE | Champs séparés, recherche multi-ID |
| API FastAPI v1 | ✅ DONE | 10 endpoints |
| FTS5 recherche | ⏳ Phase 7 | |
| RelationEvidence complète | ⏳ Phase 8 | Schéma présent, moteur de déduction manquant |
| LegalDiff | ⏳ Phase 9 | |
| CI GitHub Actions | ⏳ Phase 10 | |

**Avancement estimé MVP : 68%**

---

*Rapport produit automatiquement — Mode DEBUG actif — CERTIFIED_100=false*  
*Ne pas écraser ce rapport — PROTOCOLE JUSLIB invariant-2*
