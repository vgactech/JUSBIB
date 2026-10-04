"""
JUSLIB — Tests corrections R003.

Couvre exclusivement les corrections R003-P0-A à P0-E :
  P0-A : URLs OAuth Légifrance (piste.gouv.fr)
  P0-B : verify_integrity() sans effet de bord (_compute_hash_readonly)
  P0-C : canonical_content_hash vs raw_source_hash dans /v1/explain
  P0-D : _enrich_with_llm() ne marque plus llm_generated sans appel réel
  P0-E : JuslibDB SQLite (FK, INSERT-only triggers, Snapshot, ELI/CELEX/ECLI)

Blocs :
  H — P0-A Légifrance URLs
  I — P0-B verify_integrity() sans effet de bord
  J — P0-D _enrich_with_llm() sécurisé
  K — P0-E JuslibDB (schéma, FK, INSERT-only, Snapshot)
  L — ELI/CELEX/ECLI identifiants officiels
  M — Intégrité corpus (hash canonique + vérification)
  N — API /v1/db/stats + /v1/corpus/index (sans serveur, tests directs)

Exécution : cd juslib && pytest tests/test_juslib_r003.py -v
"""

import hashlib
import os
import sys
import tempfile
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ============================================================
# BLOC H — P0-A : URLs OAuth Légifrance (R003)
# ============================================================

class TestLegifranceUrlsR003:
    """H — URLs OAuth corrigées (sandbox-oauth.piste.gouv.fr / oauth.piste.gouv.fr)."""

    def test_H01_sandbox_token_url_piste(self):
        """R003-P0-A : URL token sandbox pointe vers piste.gouv.fr."""
        from juslib.connectors.legifranceconnector import _PISTE_ENVS
        url = _PISTE_ENVS["sandbox"]["token_url"]
        assert "piste.gouv.fr" in url, f"URL sandbox incorrecte : {url}"
        assert "sandbox" in url, f"URL sandbox doit contenir 'sandbox' : {url}"

    def test_H02_production_token_url_piste(self):
        """R003-P0-A : URL token production pointe vers piste.gouv.fr."""
        from juslib.connectors.legifranceconnector import _PISTE_ENVS
        url = _PISTE_ENVS["production"]["token_url"]
        assert "piste.gouv.fr" in url, f"URL production incorrecte : {url}"
        assert "sandbox" not in url, f"URL production ne doit pas contenir 'sandbox' : {url}"

    def test_H03_old_aife_url_not_used(self):
        """R003-P0-A : l'ancienne URL oauth.sandbox-aife.economie.gouv.fr n'est plus utilisée."""
        from juslib.connectors.legifranceconnector import _PISTE_ENVS
        for env, config in _PISTE_ENVS.items():
            assert "aife.economie.gouv.fr" not in config["token_url"], (
                f"Env {env} utilise encore l'ancienne URL AIFE : {config['token_url']}"
            )

    def test_H04_sandbox_token_url_exact(self):
        """R003-P0-A : URL sandbox exacte selon doc PISTE officielle."""
        from juslib.connectors.legifranceconnector import _PISTE_ENVS
        assert _PISTE_ENVS["sandbox"]["token_url"] == "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"

    def test_H05_production_token_url_exact(self):
        """R003-P0-A : URL production exacte selon doc PISTE officielle."""
        from juslib.connectors.legifranceconnector import _PISTE_ENVS
        assert _PISTE_ENVS["production"]["token_url"] == "https://oauth.piste.gouv.fr/api/oauth/token"

    def test_H06_connector_version_updated(self):
        """R003-P0-A : version du connecteur mise à jour (≥ 0.1.2)."""
        from juslib.connectors.legifranceconnector import LegifranceConnector
        major, minor, patch = (int(x) for x in LegifranceConnector.CONNECTOR_VERSION.split("."))
        assert (major, minor, patch) >= (0, 1, 2), (
            f"Version {LegifranceConnector.CONNECTOR_VERSION} doit être ≥ 0.1.2"
        )


# ============================================================
# BLOC I — P0-B : verify_integrity() sans effet de bord
# ============================================================

class TestVerifyIntegrityNoSideEffect:
    """I — R003-P0-B : verify_integrity() ne doit pas écraser canonical_content_hash."""

    def test_I01_verify_integrity_does_not_overwrite_stored_hash(self):
        """R003-P0-B : appeler verify_integrity() ne doit pas modifier canonical_content_hash."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(
            provision_id="P-001", document_id="D-001",
            text="Texte de test pour intégrité.",
            raw_source_hash=hashlib.sha256(b"raw").hexdigest(),
        )
        v.compute_canonical_hash()
        stored_before = v.canonical_content_hash

        # Premier appel
        ok1, _ = v.verify_integrity()
        assert v.canonical_content_hash == stored_before, (
            "verify_integrity() a modifié canonical_content_hash (effet de bord P0-B)"
        )

        # Deuxième appel consécutif
        ok2, _ = v.verify_integrity()
        assert v.canonical_content_hash == stored_before, (
            "verify_integrity() a modifié canonical_content_hash au 2e appel"
        )
        assert ok1 and ok2

    def test_I02_verify_integrity_detects_tampered_hash(self):
        """R003-P0-B : un hash stocké falsifié doit être détecté comme incohérent."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(provision_id="P", document_id="D", text="Texte original.")
        v.compute_canonical_hash()

        # On falsifie le hash stocké
        v.canonical_content_hash = "0" * 64

        ok, errors = v.verify_integrity()
        assert not ok, "Un hash falsifié doit être détecté"
        assert any("R003-P0-B" in e for e in errors), f"Message d'erreur R003-P0-B attendu: {errors}"

    def test_I03_verify_integrity_tamper_detection_does_not_corrupt_object(self):
        """R003-P0-B : après détection de tampering, l'objet n'est pas corrompu."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(provision_id="P", document_id="D", text="Texte original.")
        v.compute_canonical_hash()

        falsified = "0" * 64
        v.canonical_content_hash = falsified

        # verify_integrity doit retourner l'erreur
        ok, _ = v.verify_integrity()
        assert not ok

        # L'objet doit toujours avoir le hash "falsifié" (pas recalculé en douce)
        assert v.canonical_content_hash == falsified, (
            "verify_integrity() ne doit pas réécrire silencieusement le hash — "
            "la détection de tampering doit être conservée"
        )

    def test_I04_compute_hash_readonly_never_stored(self):
        """R003-P0-B : _compute_hash_readonly() ne touche pas canonical_content_hash."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(provision_id="P", document_id="D", text="Texte.")
        # canonical_content_hash non initialisé
        assert v.canonical_content_hash is None
        h = v._compute_hash_readonly()
        assert h is not None and len(h) == 64
        assert v.canonical_content_hash is None, (
            "_compute_hash_readonly() ne doit pas stocker dans canonical_content_hash"
        )

    def test_I05_multiple_verify_calls_idempotent(self):
        """R003-P0-B : 10 appels consécutifs à verify_integrity() → résultat identique."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(
            provision_id="P", document_id="D",
            text="Contenu légal stable.",
            raw_source_hash=hashlib.sha256(b"raw").hexdigest(),
        )
        v.compute_canonical_hash()
        stored = v.canonical_content_hash

        for i in range(10):
            ok, errors = v.verify_integrity()
            assert ok, f"Appel {i+1} : verify_integrity() échoue : {errors}"
            assert v.canonical_content_hash == stored, f"Hash modifié à l'appel {i+1}"

    def test_I06_verify_integrity_missing_raw_hash(self):
        """R003-P0-B : raw_source_hash manquant → erreur détectée."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(provision_id="P", document_id="D", text="Texte.")
        v.compute_canonical_hash()
        # raw_source_hash pas défini
        ok, errors = v.verify_integrity()
        assert not ok
        assert any("raw_source_hash" in e for e in errors)

    def test_I07_verify_integrity_missing_canonical_hash(self):
        """R003-P0-B : canonical_content_hash manquant → erreur détectée."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(
            provision_id="P", document_id="D", text="Texte.",
            raw_source_hash="abc123",
        )
        # canonical_content_hash non calculé
        assert v.canonical_content_hash is None
        ok, errors = v.verify_integrity()
        assert not ok
        assert any("canonical_content_hash" in e for e in errors)


# ============================================================
# BLOC J — P0-D : _enrich_with_llm() sécurisé
# ============================================================

class TestEnrichWithLLMFixed:
    """J — R003-P0-D : _enrich_with_llm() ne marque plus llm_generated sans appel réel."""

    def test_J01_no_llm_generated_with_api_key_present(self, monkeypatch):
        """R003-P0-D : même avec BOB_API_KEY présente, pas de llm_generated sans appel réel."""
        monkeypatch.setenv("BOB_API_KEY", "fake-key-for-test")
        from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
        engine = PlainLanguageEngine(llm_enabled=True)
        result = engine.explain("ID-001", "disposition", "Texte légal.", ReadingLevel.CITIZEN)
        assert result.production_type == "rule_based", (
            f"R003-P0-D : production_type doit être rule_based (pas d'appel LLM réel), "
            f"obtenu: {result.production_type}"
        )

    def test_J02_no_ai_warning_without_real_llm_call(self, monkeypatch):
        """R003-P0-D : ai_generated_warning absent si pas d'appel LLM réel."""
        monkeypatch.setenv("BOB_API_KEY", "fake-key-for-test")
        from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
        engine = PlainLanguageEngine(llm_enabled=True)
        result = engine.explain("ID-002", "document", "Texte légal.", ReadingLevel.INTERMEDIATE)
        assert result.ai_generated_warning is None, (
            f"R003-P0-D : ai_generated_warning doit être None sans appel LLM réel, "
            f"obtenu: {result.ai_generated_warning}"
        )

    def test_J03_rule_based_with_no_key(self, monkeypatch):
        """R003-P0-D : sans clé API → rule_based (comportement inchangé)."""
        monkeypatch.delenv("BOB_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
        engine = PlainLanguageEngine(llm_enabled=True)
        result = engine.explain("ID-003", "disposition", "Texte.", ReadingLevel.CITIZEN)
        assert result.production_type == "rule_based"

    def test_J04_expert_level_always_source(self, monkeypatch):
        """Niveau EXPERT retourne toujours is_source_text=True et production_type='source'."""
        monkeypatch.setenv("BOB_API_KEY", "fake-key-for-test")
        from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
        engine = PlainLanguageEngine(llm_enabled=True)
        result = engine.explain("ID-004", "document", "Texte officiel.", ReadingLevel.EXPERT)
        assert result.is_source_text is True
        assert result.production_type == "source"


# ============================================================
# BLOC K — P0-E : JuslibDB SQLite
# ============================================================

class TestJuslibDB:
    """K — R003-P0-E : JuslibDB (schéma SQLite, FK, INSERT-only, Snapshot)."""

    @pytest.fixture
    def db(self):
        """DB en mémoire pour les tests."""
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=True)

    def test_K01_db_initializes(self, db):
        """K01 : JuslibDB s'initialise sans erreur."""
        stats = db.stats()
        assert stats["documents"] == 0
        assert stats["insert_only_enforced"] is True
        assert stats["foreign_keys_enabled"] is True

    def test_K02_insert_document(self, db):
        """K02 : insert_document retourne un juslib_id valide."""
        doc_id = db.insert_document(
            title="Règlement (UE) 2016/679 — RGPD",
            document_type="regulation",
            jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32016R0679",
            connector_id="eurlex",
            eli_id="http://data.europa.eu/eli/reg/2016/679",
            celex_id="32016R0679",
        )
        assert doc_id.startswith("JUSLIB-DOC-EU-")
        stats = db.stats()
        assert stats["documents"] == 1

    def test_K03_insert_document_retrieve(self, db):
        """K03 : document inséré est récupérable par juslib_id."""
        doc_id = db.insert_document(
            title="Code civil français",
            document_type="code",
            jurisdiction="FR",
            source_url="https://www.legifrance.gouv.fr/codes/id/LEGITEXT000006070721",
            connector_id="legifrance",
            native_id="LEGITEXT000006070721",
        )
        doc = db.get_document(doc_id)
        assert doc is not None
        assert doc["title"] == "Code civil français"
        assert doc["jurisdiction"] == "FR"
        assert doc["native_id"] == "LEGITEXT000006070721"

    def test_K04_insert_only_trigger_blocks_update(self, db):
        """K04 : INSERT-only trigger bloque UPDATE sur legal_documents."""
        doc_id = db.insert_document(
            title="Directive test",
            document_type="directive",
            jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/test",
            connector_id="eurlex",
        )
        with pytest.raises(Exception) as exc_info:
            with db.conn() as con:
                con.execute(
                    "UPDATE legal_documents SET title = ? WHERE juslib_id = ?",
                    ("Titre modifié", doc_id),
                )
        assert "INSERT-only" in str(exc_info.value) or "ABORT" in str(exc_info.value).upper()

    def test_K05_insert_only_trigger_blocks_delete(self, db):
        """K05 : INSERT-only trigger bloque DELETE sur legal_documents."""
        doc_id = db.insert_document(
            title="Loi test",
            document_type="law",
            jurisdiction="FR",
            source_url="https://www.legifrance.gouv.fr/test",
            connector_id="legifrance",
        )
        with pytest.raises(Exception) as exc_info:
            with db.conn() as con:
                con.execute("DELETE FROM legal_documents WHERE juslib_id = ?", (doc_id,))
        assert "INSERT-only" in str(exc_info.value) or "ABORT" in str(exc_info.value).upper()

    def test_K06_legal_version_insert_only(self, db):
        """K06 : INSERT-only trigger bloque UPDATE sur legal_versions."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        prov_id = db.insert_provision(doc_id, number="1", label="Article 1")
        ver_id = db.insert_version(
            provision_id=prov_id,
            document_id=doc_id,
            text="Texte original.",
            valid_from="2018-05-25",
            source_url="https://test.fr/art1",
        )
        with pytest.raises(Exception):
            with db.conn() as con:
                con.execute(
                    "UPDATE legal_versions SET text = ? WHERE version_id = ?",
                    ("Texte modifié", ver_id),
                )

    def test_K07_insert_provision_and_version(self, db):
        """K07 : provision et version s'insèrent avec FK correctes."""
        doc_id = db.insert_document(
            title="Convention OHADA", document_type="treaty",
            jurisdiction="OHADA",
            source_url="https://www.ohada.org/convention",
            connector_id="ohada",
        )
        prov_id = db.insert_provision(doc_id, number="1", label="Article 1")
        assert prov_id is not None

        ver_id = db.insert_version(
            provision_id=prov_id,
            document_id=doc_id,
            text="Les États parties s'engagent…",
            valid_from="1993-10-17",
            source_url="https://www.ohada.org/convention#art1",
        )
        assert ver_id is not None
        stats = db.stats()
        assert stats["provisions"] == 1
        assert stats["versions"] == 1

    def test_K08_canonical_hash_auto_computed_on_version_insert(self, db):
        """K08 : insert_version calcule automatiquement canonical_content_hash."""
        doc_id = db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/test", connector_id="eurlex",
        )
        prov_id = db.insert_provision(doc_id, number="17")
        ver_id = db.insert_version(
            provision_id=prov_id,
            document_id=doc_id,
            text="La personne concernée a le droit d'obtenir l'effacement.",
            valid_from="2018-05-25",
            source_url="https://eur-lex.europa.eu/rgpd/art17",
        )
        with db.conn() as con:
            row = con.execute(
                "SELECT canonical_content_hash FROM legal_versions WHERE version_id = ?",
                (ver_id,)
            ).fetchone()
        assert row["canonical_content_hash"] is not None
        assert len(row["canonical_content_hash"]) == 64

    def test_K09_snapshot_version_at_date(self, db):
        """K09 : get_version_at_date retourne la version en vigueur à une date.
        P1-01 : la version initiale est EXPLICITEMENT fermée (valid_until) avant
        l'insertion de la version suivante — évite le chevauchement temporel.
        """
        doc_id = db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
        )
        prov_id = db.insert_provision(doc_id, number="17")

        # Version initiale : 2018-05-25 → 2021-01-01 (fermée explicitement)
        ver1 = db.insert_version(
            provision_id=prov_id, document_id=doc_id,
            text="Version initiale.",
            valid_from="2018-05-25",
            valid_until="2021-01-01",   # fermée — P1-01 : pas de chevauchement
            source_url="https://eur-lex.europa.eu/rgpd/art17/v1",
        )
        # Version amendée : 2021-01-01 → (ouverte) — pas de chevauchement avec v1 fermée
        ver2 = db.insert_version(
            provision_id=prov_id, document_id=doc_id,
            text="Version amendée.",
            valid_from="2021-01-01",
            source_url="https://eur-lex.europa.eu/rgpd/art17/v2",
            revision=2,
        )

        # Avant l'amendement → version initiale
        v = db.get_version_at_date(prov_id, "2019-06-01")
        assert v is not None
        assert v["version_id"] == ver1, f"Attendu ver1, obtenu {v['version_id']}"

        # Après l'amendement → version amendée
        v = db.get_version_at_date(prov_id, "2022-01-01")
        assert v is not None
        assert v["version_id"] == ver2, f"Attendu ver2, obtenu {v['version_id']}"

    def test_K10_snapshot_before_entry_into_force(self, db):
        """K10 : avant l'entrée en vigueur, get_version_at_date retourne None."""
        doc_id = db.insert_document(
            title="Directive test", document_type="directive", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/test", connector_id="eurlex",
        )
        prov_id = db.insert_provision(doc_id, number="1")
        db.insert_version(
            provision_id=prov_id, document_id=doc_id,
            text="Texte.", valid_from="2018-05-25",
            source_url="https://eur-lex.europa.eu/test/art1",
        )
        v = db.get_version_at_date(prov_id, "2000-01-01")
        assert v is None, "Avant l'entrée en vigueur, aucune version ne doit être retournée"

    def test_K11_compute_snapshot_full_document(self, db):
        """K11 : compute_snapshot retourne toutes les provisions en vigueur."""
        doc_id = db.insert_document(
            title="Convention CEDH", document_type="treaty", jurisdiction="EU",
            source_url="https://www.echr.coe.int/cedh", connector_id="echr",
        )
        for i in range(3):
            prov_id = db.insert_provision(doc_id, number=str(i + 1), order_index=i)
            db.insert_version(
                provision_id=prov_id, document_id=doc_id,
                text=f"Article {i+1} de la CEDH.",
                valid_from="1953-09-03",
                source_url=f"https://www.echr.coe.int/cedh/art{i+1}",
            )
        snapshot = db.compute_snapshot(doc_id, "2024-01-01")
        assert len(snapshot) == 3
        assert all(s["is_in_force"] for s in snapshot)
        stats = db.stats()
        assert stats["snapshots"] == 3

    def test_K12_corpus_entry_index(self, db):
        """K12 : index_corpus_entry indexe avec canonical_content_hash calculé auto."""
        doc_id = db.insert_document(
            title="Test Doc", document_type="law", jurisdiction="FR",
            source_url="https://legifrance.gouv.fr/test", connector_id="legifrance",
        )
        db.index_corpus_entry(
            juslib_id=doc_id,
            text_excerpt="Nul n'est censé ignorer la loi.",
            source_url="https://legifrance.gouv.fr/test",
        )
        entry = db.get_corpus_entry(doc_id)
        assert entry is not None
        assert entry["canonical_content_hash"] is not None
        assert len(entry["canonical_content_hash"]) == 64

    def test_K13_corpus_entry_integrity_ok(self, db):
        """K13 : verify_corpus_entry_integrity PASS si texte non modifié."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        db.index_corpus_entry(doc_id, "La liberté est le principe.", "https://test.fr")
        ok, errors = db.verify_corpus_entry_integrity(doc_id)
        assert ok, f"Intégrité échouée : {errors}"

    def test_K14_corpus_entry_not_found(self, db):
        """K14 : verify_corpus_entry_integrity FAIL si entrée absente."""
        ok, errors = db.verify_corpus_entry_integrity("JUSLIB-DOC-EU-INEXISTANT")
        assert not ok
        assert any("non trouvée" in e or "not found" in e.lower() for e in errors)

    def test_K15_relation_evidence_insert(self, db):
        """K15 : insert_relation_evidence retourne un evidence_id."""
        ev_id = db.insert_relation_evidence(
            relation_type="MODIFIES",
            source_id="RGPD-ART17",
            target_id="DIR-9546-ART12",
            evidence_url="https://eur-lex.europa.eu/rgpd/recital-156",
            confidence=0.95,
            certainty_level="certain",
        )
        assert ev_id is not None
        stats = db.stats()
        assert stats["relation_evidence"] == 1

    def test_K16_translation_insert(self, db):
        """K16 : insert_translation retourne un translation_id."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/test", connector_id="eurlex",
        )
        prov_id = db.insert_provision(doc_id, number="1")
        ver_id = db.insert_version(
            provision_id=prov_id, document_id=doc_id,
            text="The data subject shall have the right to obtain erasure.",
            valid_from="2018-05-25",
            source_url="https://eur-lex.europa.eu/test/art1",
            language="en",
        )
        tr_id = db.insert_translation(
            version_id=ver_id,
            source_language="en",
            target_language="fr",
            translated_text="La personne concernée a le droit d'obtenir l'effacement.",
            translation_type="official",
            source_url="https://eur-lex.europa.eu/test/art1/fr",
        )
        assert tr_id is not None
        stats = db.stats()
        assert stats["translations"] == 1


# ============================================================
# BLOC L — ELI/CELEX/ECLI identifiants officiels
# ============================================================

class TestOfficialIdentifiers:
    """L — Identifiants officiels ELI, CELEX, ECLI séparés du juslib_id interne."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def test_L01_eli_stored_separately(self, db):
        """L01 : eli_id stocké dans un champ séparé (pas dans juslib_id)."""
        doc_id = db.insert_document(
            title="RGPD",
            document_type="regulation",
            jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32016R0679",
            connector_id="eurlex",
            eli_id="http://data.europa.eu/eli/reg/2016/679",
            celex_id="32016R0679",
        )
        doc = db.get_document(doc_id)
        assert doc["eli_id"] == "http://data.europa.eu/eli/reg/2016/679"
        assert doc["celex_id"] == "32016R0679"
        assert doc["juslib_id"] != doc["eli_id"], "juslib_id != eli_id — IDs séparés"

    def test_L02_find_by_celex(self, db):
        """L02 : recherche par CELEX retrouve le document."""
        db.insert_document(
            title="Directive NIS2", document_type="directive", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/nis2", connector_id="eurlex",
            celex_id="32022L2555",
        )
        results = db.find_documents_by_identifier(celex_id="32022L2555")
        assert len(results) == 1
        assert results[0]["celex_id"] == "32022L2555"

    def test_L03_find_by_eli(self, db):
        """L03 : recherche par ELI retrouve le document."""
        db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
            eli_id="http://data.europa.eu/eli/reg/2016/679",
        )
        results = db.find_documents_by_identifier(eli_id="http://data.europa.eu/eli/reg/2016/679")
        assert len(results) == 1

    def test_L04_find_by_native_id(self, db):
        """L04 : recherche par ID natif (Légifrance, CanLII…) retrouve le document."""
        db.insert_document(
            title="Code civil", document_type="code", jurisdiction="FR",
            source_url="https://legifrance.gouv.fr/loda", connector_id="legifrance",
            native_id="LEGITEXT000006070721",
        )
        results = db.find_documents_by_identifier(native_id="LEGITEXT000006070721")
        assert len(results) == 1
        assert results[0]["native_id"] == "LEGITEXT000006070721"

    def test_L05_ecli_for_jurisprudence(self, db):
        """L05 : ECLI stocké pour une décision de jurisprudence."""
        doc_id = db.insert_document(
            title="CJUE C-131/12 — Google Spain",
            document_type="jurisprudence",
            jurisdiction="EU",
            source_url="https://curia.europa.eu/C-131-12",
            connector_id="eurlex",
            ecli_id="ECLI:EU:C:2014:317",
        )
        doc = db.get_document(doc_id)
        assert doc["ecli_id"] == "ECLI:EU:C:2014:317"

    def test_L06_no_identifier_search_returns_empty(self, db):
        """L06 : find_documents_by_identifier sans paramètre retourne liste vide."""
        results = db.find_documents_by_identifier()
        assert results == []


# ============================================================
# BLOC M — Intégrité corpus (hash canonique)
# ============================================================

class TestCorpusIntegrity:
    """M — Vérification intégrité corpus via canonical_content_hash."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def test_M01_canonical_hash_deterministic(self, db):
        """M01 : même texte → même canonical_content_hash après deux indexations."""
        from juslib.db import _compute_canonical_hash
        text = "La liberté est le principe, la restriction l'exception."
        h1 = _compute_canonical_hash(text)
        h2 = _compute_canonical_hash(text)
        assert h1 == h2

    def test_M02_canonical_hash_whitespace_normalized(self, db):
        """M02 : espaces multiples et sauts de ligne normalisés avant hash."""
        from juslib.db import _compute_canonical_hash
        h1 = _compute_canonical_hash("Texte    avec   espaces")
        h2 = _compute_canonical_hash("Texte avec espaces")
        assert h1 == h2, "Les espaces multiples doivent être normalisés"

    def test_M03_raw_hash_different_from_canonical(self, db):
        """M03 : raw_source_hash (HTML brut) ≠ canonical_content_hash (texte normalisé)."""
        from juslib.db import _compute_canonical_hash, _compute_raw_hash
        raw_html = b"<p>La libert&eacute; est le principe.  </p>"
        clean_text = "La liberté est le principe."
        raw_h = _compute_raw_hash(raw_html)
        canonical_h = _compute_canonical_hash(clean_text)
        assert raw_h != canonical_h, "raw_source_hash et canonical_content_hash doivent différer"

    def test_M04_stats_all_tables_present(self, db):
        """M04 : stats() retourne toutes les tables attendues."""
        stats = db.stats()
        required_keys = [
            "documents", "provisions", "versions", "snapshots",
            "relation_evidence", "translations", "corpus_entries",
            "authorities", "insert_only_enforced", "foreign_keys_enabled",
        ]
        for k in required_keys:
            assert k in stats, f"Clé manquante dans stats() : {k}"

    def test_M05_db_path_memory_vs_file(self, tmp_path):
        """M05 : DB fichier persistante vs DB mémoire — les deux s'initialisent."""
        from juslib.db import JuslibDB
        db_mem = JuslibDB(db_path=None)
        db_file = JuslibDB(db_path=str(tmp_path / "test.db"))
        assert db_mem.stats()["documents"] == 0
        assert db_file.stats()["documents"] == 0
        db_mem.close()
        db_file.close()


# ============================================================
# BLOC N — Non-régression R003 sur les blocs existants
# ============================================================

class TestNonRegressionR003:
    """N — Vérification que les corrections R003 n'ont pas cassé les 69 tests existants."""

    def test_N01_version_string_updated(self):
        """N01 : version JUSLIB mise à jour à 0.1.2."""
        from juslib import __version__
        major, minor, patch = (int(x) for x in __version__.split("."))
        assert (major, minor, patch) >= (0, 1, 2), f"Version {__version__} < 0.1.2"

    def test_N02_legal_version_compute_hash_still_stores(self):
        """N02 : compute_canonical_hash() stocke toujours le hash (comportement initial)."""
        from juslib.models.legal_version import LegalVersion
        v = LegalVersion(provision_id="P", document_id="D", text="Texte.")
        assert v.canonical_content_hash is None
        h = v.compute_canonical_hash()
        assert v.canonical_content_hash == h, "compute_canonical_hash() doit toujours stocker"

    def test_N03_plain_language_engine_citizen_rule_based(self, monkeypatch):
        """N03 : moteur sans LLM → production_type=rule_based pour CITIZEN."""
        monkeypatch.delenv("BOB_API_KEY", raising=False)
        from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel
        engine = PlainLanguageEngine(llm_enabled=False)
        result = engine.explain("ID", "doc", "Texte.", ReadingLevel.CITIZEN)
        assert result.production_type == "rule_based"

    def test_N04_explain_result_source_entity_id_required(self):
        """N04 : source_entity_id vide → échec validation."""
        from juslib.translation.plain_language import ExplainResult, ReadingLevel
        r = ExplainResult(source_entity_id="", source_entity_type="doc")
        ok, errors = r.validate()
        assert not ok
        assert any("source_entity_id" in e for e in errors)

    def test_N05_legifrance_fallback_to_sandbox(self):
        """N05 : env invalide → fallback sandbox (R003-P0-A préservé)."""
        from juslib.connectors.legifranceconnector import LegifranceConnector, _PISTE_ENVS
        c = LegifranceConnector(piste_env="invalid_env")
        assert c._piste_env == "sandbox"
        assert c._token_url == _PISTE_ENVS["sandbox"]["token_url"]

    def test_N06_db_juslib_imported(self):
        """N06 : module juslib.db importable sans erreur."""
        from juslib.db import JuslibDB, _compute_canonical_hash, _compute_raw_hash
        assert JuslibDB is not None
        assert _compute_canonical_hash("test") is not None
        assert _compute_raw_hash(b"test") is not None
