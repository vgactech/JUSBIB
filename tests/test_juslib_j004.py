"""
JUSLIB — Tests corrections J004.

Blocs :
  O — P0-01 : Fermeture injection corpus (ingestion_method + EXPERT interdit sur client)
  P — P0-02 : import hashlib présent (NameError corrigé)
  Q — P0-03 : INSERT strict corpus_entries (plus de OR REPLACE)
  R — P0-04 : Triggers INSERT-only sur toutes les tables historiques
  S — P0-05 : Tests HTTP réels (FastAPI TestClient — chaîne complète)
  T — P1-01 : Chevauchement temporel (rejet + allow_overlap)
  U — P1-02 : version_status (in_force/repealed/suspended)
  V — P1-03 : SourceCapture — provenance brute
  W — P1-04 : UNIQUE ELI/CELEX/ECLI
  X — Non-régression J004

Exécution : cd juslib && pytest tests/test_juslib_j004.py -v
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ============================================================
# BLOC O — P0-01 : Fermeture injection corpus
# ============================================================

class TestCorpusInjectionClosed:
    """O — J004-P0-01 : ingestion_method sépare authentifié vs client."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def test_O01_connector_fetched_ingestion_method(self, db):
        """O01 : index_corpus_entry avec ingestion_method=connector_fetched."""
        doc_id = db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
        )
        db.index_corpus_entry(
            doc_id, "Texte officiel.", "https://eur-lex.europa.eu/rgpd",
            ingestion_method="connector_fetched",
        )
        entry = db.get_corpus_entry(doc_id)
        assert entry["ingestion_method"] == "connector_fetched"

    def test_O02_client_provided_ingestion_method(self, db):
        """O02 : index_corpus_entry avec ingestion_method=client_provided."""
        doc_id = db.insert_document(
            title="Doc client", document_type="law", jurisdiction="FR",
            source_url="https://declare.fr", connector_id="client_import",
            certainty_level="client_provided",
        )
        db.index_corpus_entry(
            doc_id, "Texte client.", "https://declare.fr",
            ingestion_method="client_provided",
        )
        entry = db.get_corpus_entry(doc_id)
        assert entry["ingestion_method"] == "client_provided"

    def test_O03_invalid_ingestion_method_rejected(self, db):
        """O03 : ingestion_method invalide → ValueError."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="test",
        )
        with pytest.raises(ValueError, match="ingestion_method invalide"):
            db.index_corpus_entry(doc_id, "Texte.", "https://test.fr",
                                  ingestion_method="fake_method")

    def test_O04_is_connector_fetched_true(self, db):
        """O04 : is_connector_fetched=True pour entrée connector_fetched."""
        doc_id = db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
        )
        db.index_corpus_entry(
            doc_id, "Texte.", "https://eur-lex.europa.eu/rgpd",
            ingestion_method="connector_fetched",
        )
        assert db.is_connector_fetched(doc_id) is True

    def test_O05_is_connector_fetched_false_for_client(self, db):
        """O05 : is_connector_fetched=False pour entrée client_provided."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="client_import",
            certainty_level="client_provided",
        )
        db.index_corpus_entry(
            doc_id, "Texte client.", "https://test.fr",
            ingestion_method="client_provided",
        )
        assert db.is_connector_fetched(doc_id) is False

    def test_O06_client_provided_certainty_allowed_in_db(self, db):
        """O06 : certainty_level=client_provided accepté en DB."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="client_import",
            certainty_level="client_provided",
        )
        doc = db.get_document(doc_id)
        assert doc["certainty_level"] == "client_provided"


# ============================================================
# BLOC P — P0-02 : import hashlib présent
# ============================================================

class TestHashlibImport:
    """P — J004-P0-02 : hashlib correctement importé dans api/main.py."""

    def test_P01_hashlib_importable_from_api_module(self):
        """P01 : hashlib est importé dans le module API (pas de NameError)."""
        import importlib
        import importlib.util
        # Vérifier que hashlib est dans les imports du fichier
        api_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "juslib", "api", "main.py"
        )
        with open(api_path, "r") as f:
            content = f.read()
        assert "import hashlib" in content, (
            "P0-02 : 'import hashlib' doit être présent dans src/juslib/api/main.py"
        )

    def test_P02_hashlib_present_before_first_use(self):
        """P02 : import hashlib apparaît avant toute utilisation de hashlib.sha256."""
        api_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "juslib", "api", "main.py"
        )
        with open(api_path, "r") as f:
            lines = f.readlines()
        import_line = next(
            (i for i, l in enumerate(lines) if "import hashlib" in l), None
        )
        use_line = next(
            (i for i, l in enumerate(lines) if "hashlib.sha256" in l), None
        )
        assert import_line is not None, "import hashlib absent"
        if use_line is not None:
            assert import_line < use_line, (
                f"import hashlib (ligne {import_line+1}) doit précéder hashlib.sha256 "
                f"(ligne {use_line+1})"
            )


# ============================================================
# BLOC Q — P0-03 : INSERT strict corpus_entries
# ============================================================

class TestInsertStrictCorpusEntries:
    """Q — J004-P0-03 : corpus_entries refuse OR REPLACE — INSERT strict."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def test_Q01_double_insert_raises_integrity_error(self, db):
        """Q01 : insérer deux fois le même juslib_id → IntegrityError."""
        import sqlite3
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        db.index_corpus_entry(doc_id, "Texte v1.", "https://test.fr",
                               ingestion_method="connector_fetched")
        with pytest.raises((sqlite3.IntegrityError, Exception)):
            db.index_corpus_entry(doc_id, "Texte v2 écrase ?", "https://test.fr",
                                   ingestion_method="connector_fetched")

    def test_Q02_original_text_preserved_after_failed_double_insert(self, db):
        """Q02 : après échec du second INSERT, le texte original est conservé."""
        import sqlite3
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        db.index_corpus_entry(doc_id, "Texte original.", "https://test.fr",
                               ingestion_method="connector_fetched")
        try:
            db.index_corpus_entry(doc_id, "Texte malveillant.", "https://test.fr",
                                   ingestion_method="connector_fetched")
        except Exception:
            pass
        entry = db.get_corpus_entry(doc_id)
        assert entry["text_excerpt"] == "Texte original.", (
            "P0-03 : le texte original doit être préservé après tentative d'écrasement"
        )

    def test_Q03_no_insert_or_replace_in_db_source(self):
        """Q03 : la chaîne 'INSERT OR REPLACE INTO corpus_entries' absente du code."""
        db_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "juslib", "db.py"
        )
        with open(db_path, "r") as f:
            content = f.read()
        assert "INSERT OR REPLACE INTO corpus_entries" not in content, (
            "P0-03 : INSERT OR REPLACE INTO corpus_entries ne doit plus apparaître dans db.py"
        )


# ============================================================
# BLOC R — P0-04 : Triggers INSERT-only sur toutes les tables
# ============================================================

class TestInsertOnlyAllTables:
    """R — J004-P0-04 : triggers INSERT-only sur toutes les tables historiques."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def _insert_base(self, db):
        """Insère un document + provision + version de base pour les tests."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        prov_id = db.insert_provision(doc_id, number="1")
        ver_id = db.insert_version(
            provision_id=prov_id, document_id=doc_id,
            text="Texte.", valid_from="2020-01-01",
            source_url="https://test.fr/art1",
        )
        return doc_id, prov_id, ver_id

    def test_R01_provisions_insert_only_update_blocked(self, db):
        """R01 : UPDATE sur legal_provisions bloqué."""
        doc_id, prov_id, _ = self._insert_base(db)
        with pytest.raises(Exception) as exc:
            with db.conn() as con:
                con.execute("UPDATE legal_provisions SET number = '99' WHERE provision_id = ?",
                            (prov_id,))
        assert "INSERT-only" in str(exc.value) or "ABORT" in str(exc.value).upper()

    def test_R02_provisions_insert_only_delete_blocked(self, db):
        """R02 : DELETE sur legal_provisions bloqué."""
        doc_id, prov_id, _ = self._insert_base(db)
        with pytest.raises(Exception):
            with db.conn() as con:
                con.execute("DELETE FROM legal_provisions WHERE provision_id = ?", (prov_id,))

    def test_R03_relation_evidence_insert_only(self, db):
        """R03 : UPDATE/DELETE sur relation_evidence bloqués."""
        ev_id = db.insert_relation_evidence(
            "MODIFIES", "src-1", "tgt-1", "https://eur-lex.europa.eu/proof",
        )
        with pytest.raises(Exception):
            with db.conn() as con:
                con.execute("UPDATE relation_evidence SET confidence = 1.0 WHERE evidence_id = ?",
                            (ev_id,))

    def test_R04_translation_records_insert_only(self, db):
        """R04 : UPDATE sur translation_records bloqué."""
        doc_id, prov_id, ver_id = self._insert_base(db)
        tr_id = db.insert_translation(
            ver_id, "fr", "en", "The text.", translation_type="official",
        )
        with pytest.raises(Exception):
            with db.conn() as con:
                con.execute("UPDATE translation_records SET translated_text = 'EVIL' "
                            "WHERE translation_id = ?", (tr_id,))

    def test_R05_corpus_entries_insert_only(self, db):
        """R05 : UPDATE sur corpus_entries bloqué."""
        doc_id, _, _ = self._insert_base(db)
        db.index_corpus_entry(doc_id, "Texte.", "https://test.fr",
                               ingestion_method="connector_fetched")
        with pytest.raises(Exception):
            with db.conn() as con:
                con.execute("UPDATE corpus_entries SET text_excerpt = 'EVIL' "
                            "WHERE juslib_id = ?", (doc_id,))

    def test_R06_source_captures_insert_only(self, db):
        """R06 : UPDATE/DELETE sur source_captures bloqués."""
        doc_id, _, _ = self._insert_base(db)
        cap_id = db.insert_source_capture(
            doc_id, "https://test.fr", hashlib.sha256(b"raw").hexdigest(), "legifrance",
        )
        with pytest.raises(Exception):
            with db.conn() as con:
                con.execute("UPDATE source_captures SET http_status = 999 "
                            "WHERE capture_id = ?", (cap_id,))

    def test_R07_stats_reports_9_tables_with_insert_only(self, db):
        """R07 : stats() déclare 9 tables avec triggers INSERT-only."""
        s = db.stats()
        assert s["tables_with_insert_only_triggers"] == 9, (
            f"Attendu 9 tables INSERT-only, obtenu {s['tables_with_insert_only_triggers']}"
        )


# ============================================================
# BLOC S — P0-05 : Tests HTTP réels (FastAPI TestClient)
# ============================================================

class TestAPIHTTP:
    """S — J004-P0-05 : tests HTTP réels via FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        """Client HTTP + DB fraîche en mémoire."""
        from fastapi.testclient import TestClient
        from juslib.api.main import app, _db
        # Réinitialiser la DB pour chaque test
        _db._connection = None
        _db._init_db()
        return TestClient(app)

    def test_S01_health_endpoint(self, client):
        """S01 : GET /v1/health retourne 200."""
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_S02_ingest_connector_endpoint(self, client):
        """S02 : POST /v1/corpus/ingest avec connecteur officiel → 200."""
        payload = {
            "title": "RGPD",
            "document_type": "regulation",
            "jurisdiction": "EU",
            "source_url": "https://eur-lex.europa.eu/rgpd",
            "connector_id": "eurlex",
            "connector_version": "0.1.2",
            "text_excerpt": "La personne concernée a le droit d'obtenir l'effacement.",
            "raw_bytes_hash": hashlib.sha256(b"raw rgpd bytes").hexdigest(),
            "http_status": 200,
        }
        resp = client.post("/v1/corpus/ingest", json=payload)
        assert resp.status_code == 200, f"Statut inattendu : {resp.status_code} — {resp.text}"
        data = resp.json()
        assert data["status"] == "ingested"
        assert data["ingestion_method"] == "connector_fetched"
        assert data["expert_level_accessible"] is True
        assert "juslib_id" in data
        assert "capture_id" in data

    def test_S03_import_client_endpoint(self, client):
        """S03 : POST /v1/corpus/import/unverified → expert_level_accessible=False."""
        payload = {
            "title": "Doc client",
            "document_type": "law",
            "jurisdiction": "FR",
            "source_url": "https://declare.fr/doc",
            "text_excerpt": "Texte fourni par le client.",
        }
        resp = client.post("/v1/corpus/import/unverified", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingestion_method"] == "client_provided"
        assert data["expert_level_accessible"] is False
        assert "warning" in data

    def test_S04_explain_expert_on_connector_fetched_ok(self, client):
        """S04 : /v1/explain niveau EXPERT sur document connector_fetched → 200."""
        # Ingestion via connecteur
        ingest_payload = {
            "title": "RGPD Art 17",
            "document_type": "regulation",
            "jurisdiction": "EU",
            "source_url": "https://eur-lex.europa.eu/rgpd",
            "connector_id": "eurlex",
            "connector_version": "0.1.2",
            "text_excerpt": "La personne concernée a le droit d'obtenir l'effacement des données.",
            "raw_bytes_hash": hashlib.sha256(b"rgpd raw").hexdigest(),
        }
        ingest_resp = client.post("/v1/corpus/ingest", json=ingest_payload)
        assert ingest_resp.status_code == 200
        juslib_id = ingest_resp.json()["juslib_id"]

        # Explication niveau EXPERT
        explain_payload = {
            "source_entity_id": juslib_id,
            "source_entity_type": "document",
            "reading_level": "expert",
            "language": "fr",
        }
        resp = client.post("/v1/explain", json=explain_payload)
        assert resp.status_code == 200, f"EXPERT doit être autorisé : {resp.text}"
        data = resp.json()
        assert data["is_source_text"] is True
        assert data["corpus_authenticated"] is True

    def test_S05_explain_expert_on_client_provided_forbidden(self, client):
        """S05 : /v1/explain niveau EXPERT sur document client_provided → 403."""
        # Import client
        import_payload = {
            "title": "Doc client",
            "document_type": "law",
            "jurisdiction": "FR",
            "source_url": "https://fake.fr",
            "text_excerpt": "Texte client non authentifié.",
        }
        import_resp = client.post("/v1/corpus/import/unverified", json=import_payload)
        assert import_resp.status_code == 200
        juslib_id = import_resp.json()["juslib_id"]

        # Tentative niveau EXPERT → doit être rejeté
        explain_payload = {
            "source_entity_id": juslib_id,
            "source_entity_type": "document",
            "reading_level": "expert",
            "language": "fr",
        }
        resp = client.post("/v1/explain", json=explain_payload)
        assert resp.status_code == 403, (
            f"P0-01 : EXPERT doit être interdit sur client_provided — "
            f"obtenu {resp.status_code}: {resp.text}"
        )
        assert "EXPERT_LEVEL_FORBIDDEN_ON_CLIENT_PROVIDED" in resp.text

    def test_S06_explain_citizen_on_client_provided_allowed(self, client):
        """S06 : /v1/explain niveau CITIZEN sur document client_provided → 200."""
        import_payload = {
            "title": "Doc client",
            "document_type": "law",
            "jurisdiction": "FR",
            "source_url": "https://fake.fr",
            "text_excerpt": "Texte client.",
        }
        import_resp = client.post("/v1/corpus/import/unverified", json=import_payload)
        juslib_id = import_resp.json()["juslib_id"]

        explain_payload = {
            "source_entity_id": juslib_id,
            "source_entity_type": "document",
            "reading_level": "citizen",
            "language": "fr",
        }
        resp = client.post("/v1/explain", json=explain_payload)
        assert resp.status_code == 200

    def test_S07_explain_unknown_id_returns_404(self, client):
        """S07 : /v1/explain avec ID inexistant → 404."""
        resp = client.post("/v1/explain", json={
            "source_entity_id": "JUSLIB-DOC-EU-INEXISTANT",
            "source_entity_type": "document",
            "reading_level": "citizen",
        })
        assert resp.status_code == 404

    def test_S08_db_stats_endpoint(self, client):
        """S08 : GET /v1/db/stats → 200 avec toutes les clés."""
        resp = client.get("/v1/db/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert "source_captures" in data
        assert data["insert_only_enforced"] is True

    def test_S09_corpus_ingest_client_provided_certainty_rejected(self, client):
        """S09 : /v1/corpus/ingest avec certainty_level=client_provided → 400."""
        payload = {
            "title": "Test", "document_type": "law", "jurisdiction": "FR",
            "source_url": "https://test.fr", "connector_id": "legifrance",
            "connector_version": "0.1.0",
            "text_excerpt": "Texte.", "raw_bytes_hash": hashlib.sha256(b"x").hexdigest(),
            "certainty_level": "client_provided",  # interdit ici
        }
        resp = client.post("/v1/corpus/ingest", json=payload)
        assert resp.status_code == 400
        assert "INVALID_CERTAINTY_FOR_CONNECTOR_INGEST" in resp.text

    def test_S10_explain_text_expert_level_rejected(self, client):
        """S10 : /v1/explain/text avec reading_level=expert → 422 (validation Pydantic)."""
        resp = client.post("/v1/explain/text", json={
            "source_entity_id": "test",
            "source_entity_type": "document",
            "text": "Texte quelconque.",
            "reading_level": "expert",
        })
        assert resp.status_code == 422


# ============================================================
# BLOC T — P1-01 : Chevauchement temporel
# ============================================================

class TestTemporalOverlap:
    """T — J004-P1-01 : chevauchement temporel détecté et rejeté."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def _base(self, db):
        doc_id = db.insert_document(
            title="T", document_type="law", jurisdiction="FR",
            source_url="https://t.fr", connector_id="legifrance",
        )
        prov_id = db.insert_provision(doc_id, number="1")
        return doc_id, prov_id

    def test_T01_overlap_detected_open_open(self, db):
        """T01 : deux versions ouvertes → chevauchement détecté."""
        doc_id, prov_id = self._base(db)
        db.insert_version(prov_id, doc_id, "v1", "2018-01-01", "https://t.fr/v1")
        with pytest.raises(ValueError, match="P1-01"):
            db.insert_version(prov_id, doc_id, "v2", "2020-01-01", "https://t.fr/v2")

    def test_T02_no_overlap_closed_then_open(self, db):
        """T02 : première version fermée + deuxième ouverte → pas de chevauchement."""
        doc_id, prov_id = self._base(db)
        db.insert_version(prov_id, doc_id, "v1", "2018-01-01", "https://t.fr/v1",
                          valid_until="2021-01-01")
        ver2 = db.insert_version(prov_id, doc_id, "v2", "2021-01-01", "https://t.fr/v2",
                                  revision=2)
        assert ver2 is not None

    def test_T03_no_overlap_two_closed_non_overlapping(self, db):
        """T03 : deux périodes fermées non chevauchantes → OK."""
        doc_id, prov_id = self._base(db)
        db.insert_version(prov_id, doc_id, "v1", "2018-01-01", "https://t.fr/v1",
                          valid_until="2019-01-01")
        ver2 = db.insert_version(prov_id, doc_id, "v2", "2020-01-01", "https://t.fr/v2",
                                  valid_until="2021-01-01")
        assert ver2 is not None

    def test_T04_allow_overlap_bypasses_check(self, db):
        """T04 : allow_overlap=True permet le chevauchement intentionnel."""
        doc_id, prov_id = self._base(db)
        db.insert_version(prov_id, doc_id, "v1", "2018-01-01", "https://t.fr/v1")
        ver2 = db.insert_version(prov_id, doc_id, "v2", "2020-01-01", "https://t.fr/v2",
                                  allow_overlap=True)
        assert ver2 is not None

    def test_T05_overlap_on_closed_then_closed_overlapping(self, db):
        """T05 : deux périodes fermées mais chevauchantes → rejeté."""
        doc_id, prov_id = self._base(db)
        db.insert_version(prov_id, doc_id, "v1", "2018-01-01", "https://t.fr/v1",
                          valid_until="2022-01-01")
        with pytest.raises(ValueError, match="P1-01"):
            db.insert_version(prov_id, doc_id, "v2", "2020-01-01", "https://t.fr/v2",
                               valid_until="2023-01-01")

    def test_T06_find_overlapping_version_returns_details(self, db):
        """T06 : _find_overlapping_version retourne la version conflit."""
        doc_id, prov_id = self._base(db)
        ver1 = db.insert_version(prov_id, doc_id, "v1", "2018-01-01", "https://t.fr/v1")
        conflict = db._find_overlapping_version(prov_id, "2020-01-01", None)
        assert conflict is not None
        assert conflict["version_id"] == ver1


# ============================================================
# BLOC U — P1-02 : version_status
# ============================================================

class TestVersionStatus:
    """U — J004-P1-02 : version_status distingue in_force/repealed/suspended."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def _base(self, db):
        doc_id = db.insert_document(
            title="T", document_type="law", jurisdiction="FR",
            source_url="https://t.fr", connector_id="legifrance",
        )
        prov_id = db.insert_provision(doc_id, number="1")
        return doc_id, prov_id

    def test_U01_in_force_default_status(self, db):
        """U01 : version_status par défaut = in_force."""
        doc_id, prov_id = self._base(db)
        ver_id = db.insert_version(prov_id, doc_id, "Texte.", "2018-01-01", "https://t.fr/v1")
        v = db.get_version_at_date(prov_id, "2020-01-01")
        assert v is not None
        assert v["version_status"] == "in_force"

    def test_U02_repealed_not_returned_by_get_version_at_date(self, db):
        """U02 : version REPEALED n'est pas retournée par get_version_at_date."""
        doc_id, prov_id = self._base(db)
        from juslib.db import VERSION_STATUS_REPEALED
        db.insert_version(prov_id, doc_id, "Texte abrogé.", "2018-01-01", "https://t.fr/v1",
                          version_status=VERSION_STATUS_REPEALED, allow_overlap=True)
        v = db.get_version_at_date(prov_id, "2020-01-01")
        assert v is None, "Une version REPEALED ne doit pas être retournée comme applicable"

    def test_U03_get_version_status_at_date_returns_repealed(self, db):
        """U03 : get_version_status_at_date retourne le statut REPEALED pour l'audit."""
        doc_id, prov_id = self._base(db)
        from juslib.db import VERSION_STATUS_REPEALED
        db.insert_version(prov_id, doc_id, "Texte abrogé.", "2018-01-01", "https://t.fr/v1",
                          version_status=VERSION_STATUS_REPEALED, allow_overlap=True)
        status = db.get_version_status_at_date(prov_id, "2020-01-01")
        assert status["status"] == "repealed"
        assert status["is_applicable"] is False

    def test_U04_suspended_not_returned_as_applicable(self, db):
        """U04 : version SUSPENDED n'est pas retournée comme applicable."""
        doc_id, prov_id = self._base(db)
        from juslib.db import VERSION_STATUS_SUSPENDED
        db.insert_version(prov_id, doc_id, "Texte suspendu.", "2018-01-01", "https://t.fr/v1",
                          version_status=VERSION_STATUS_SUSPENDED, allow_overlap=True)
        v = db.get_version_at_date(prov_id, "2020-01-01")
        assert v is None

    def test_U05_snapshot_includes_version_status(self, db):
        """U05 : compute_snapshot inclut version_status dans chaque provision."""
        doc_id, prov_id = self._base(db)
        db.insert_version(prov_id, doc_id, "Texte.", "2018-01-01", "https://t.fr/v1")
        snap = db.compute_snapshot(doc_id, "2020-01-01")
        assert len(snap) == 1
        assert "version_status" in snap[0]
        assert snap[0]["version_status"] == "in_force"


# ============================================================
# BLOC V — P1-03 : SourceCapture
# ============================================================

class TestSourceCapture:
    """V — J004-P1-03 : chaîne de provenance brute."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def test_V01_insert_source_capture(self, db):
        """V01 : insert_source_capture retourne un capture_id."""
        doc_id = db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
        )
        cap_id = db.insert_source_capture(
            doc_id,
            "https://eur-lex.europa.eu/rgpd",
            hashlib.sha256(b"raw html bytes").hexdigest(),
            "eurlex",
            http_status=200,
            content_type="text/html; charset=UTF-8",
            raw_bytes_length=42000,
            connector_version="0.1.2",
            etag='"abc123"',
        )
        assert cap_id is not None
        stats = db.stats()
        assert stats["source_captures"] == 1

    def test_V02_get_source_captures(self, db):
        """V02 : get_source_captures retourne toutes les captures pour un document."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        db.insert_source_capture(
            doc_id, "https://test.fr",
            hashlib.sha256(b"v1").hexdigest(), "legifrance",
            http_status=200,
        )
        db.insert_source_capture(
            doc_id, "https://test.fr",
            hashlib.sha256(b"v2").hexdigest(), "legifrance",
            http_status=200,
        )
        captures = db.get_source_captures(doc_id)
        assert len(captures) == 2

    def test_V03_source_capture_insert_only(self, db):
        """V03 : UPDATE sur source_captures bloqué par trigger INSERT-only."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        cap_id = db.insert_source_capture(
            doc_id, "https://test.fr",
            hashlib.sha256(b"raw").hexdigest(), "legifrance",
        )
        with pytest.raises(Exception):
            with db.conn() as con:
                con.execute("UPDATE source_captures SET http_status = 999 "
                            "WHERE capture_id = ?", (cap_id,))

    def test_V04_raw_bytes_hash_stored_correctly(self, db):
        """V04 : raw_bytes_hash stocké et récupérable."""
        doc_id = db.insert_document(
            title="Test", document_type="law", jurisdiction="FR",
            source_url="https://test.fr", connector_id="legifrance",
        )
        expected_hash = hashlib.sha256(b"official content bytes").hexdigest()
        db.insert_source_capture(
            doc_id, "https://test.fr", expected_hash, "legifrance",
        )
        captures = db.get_source_captures(doc_id)
        assert captures[0]["raw_bytes_hash"] == expected_hash

    def test_V05_capture_distinct_from_canonical_hash(self, db):
        """V05 : raw_bytes_hash (contenu brut) ≠ canonical_content_hash (texte normalisé)."""
        from juslib.db import _compute_canonical_hash, _compute_raw_hash
        raw_html = b"<html><p>La  libert&eacute; est le  principe.</p></html>"
        clean_text = "La liberté est le principe."
        raw_h = _compute_raw_hash(raw_html)
        canonical_h = _compute_canonical_hash(clean_text)
        assert raw_h != canonical_h


# ============================================================
# BLOC W — P1-04 : UNIQUE ELI/CELEX/ECLI
# ============================================================

class TestUniqueIdentifiers:
    """W — J004-P1-04 : contraintes UNIQUE sur eli_id, celex_id, ecli_id."""

    @pytest.fixture
    def db(self):
        from juslib.db import JuslibDB
        return JuslibDB(db_path=None, debug=False)

    def test_W01_unique_eli_id(self, db):
        """W01 : deux documents avec le même eli_id → IntegrityError."""
        import sqlite3
        db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
            eli_id="http://data.europa.eu/eli/reg/2016/679",
        )
        with pytest.raises((sqlite3.IntegrityError, Exception)) as exc_info:
            db.insert_document(
                title="Faux RGPD", document_type="regulation", jurisdiction="EU",
                source_url="https://fake.eu/rgpd", connector_id="eurlex",
                eli_id="http://data.europa.eu/eli/reg/2016/679",  # doublon
            )
        assert "UNIQUE" in str(exc_info.value).upper() or "unique" in str(exc_info.value).lower()

    def test_W02_unique_celex_id(self, db):
        """W02 : deux documents avec le même celex_id → IntegrityError."""
        import sqlite3
        db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
            celex_id="32016R0679",
        )
        with pytest.raises((sqlite3.IntegrityError, Exception)):
            db.insert_document(
                title="Autre doc", document_type="directive", jurisdiction="EU",
                source_url="https://eur-lex.europa.eu/other", connector_id="eurlex",
                celex_id="32016R0679",  # doublon
            )

    def test_W03_unique_ecli_id(self, db):
        """W03 : deux documents avec le même ecli_id → IntegrityError."""
        import sqlite3
        db.insert_document(
            title="CJUE Google Spain", document_type="jurisprudence", jurisdiction="EU",
            source_url="https://curia.europa.eu/C-131-12", connector_id="eurlex",
            ecli_id="ECLI:EU:C:2014:317",
        )
        with pytest.raises((sqlite3.IntegrityError, Exception)):
            db.insert_document(
                title="Faux arrêt", document_type="jurisprudence", jurisdiction="EU",
                source_url="https://fake.eu/arr", connector_id="eurlex",
                ecli_id="ECLI:EU:C:2014:317",  # doublon
            )

    def test_W04_null_eli_allows_multiple_documents(self, db):
        """W04 : eli_id=NULL autorisé pour plusieurs documents (UNIQUE ne bloque pas NULL)."""
        doc1 = db.insert_document(
            title="Doc1", document_type="law", jurisdiction="FR",
            source_url="https://test.fr/1", connector_id="legifrance",
            eli_id=None,
        )
        doc2 = db.insert_document(
            title="Doc2", document_type="law", jurisdiction="FR",
            source_url="https://test.fr/2", connector_id="legifrance",
            eli_id=None,
        )
        assert doc1 != doc2

    def test_W05_distinct_eli_ok(self, db):
        """W05 : deux ELI distincts → OK."""
        doc1 = db.insert_document(
            title="RGPD", document_type="regulation", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/rgpd", connector_id="eurlex",
            eli_id="http://data.europa.eu/eli/reg/2016/679",
        )
        doc2 = db.insert_document(
            title="NIS2", document_type="directive", jurisdiction="EU",
            source_url="https://eur-lex.europa.eu/nis2", connector_id="eurlex",
            eli_id="http://data.europa.eu/eli/dir/2022/2555",
        )
        assert doc1 != doc2


# ============================================================
# BLOC X — Non-régression J004
# ============================================================

class TestNonRegressionJ004:
    """X — Vérification que J004 ne casse pas les comportements précédents."""

    def test_X01_version_string_updated(self):
        """X01 : version JUSLIB mise à jour à 0.1.3."""
        from juslib import __version__
        major, minor, patch = (int(x) for x in __version__.split("."))
        assert (major, minor, patch) >= (0, 1, 3), f"Version {__version__} < 0.1.3"

    def test_X02_db_has_source_captures_table(self):
        """X02 : JuslibDB possède la table source_captures."""
        from juslib.db import JuslibDB
        db = JuslibDB()
        stats = db.stats()
        assert "source_captures" in stats

    def test_X03_version_status_constants_exported(self):
        """X03 : constantes VERSION_STATUS_* exportées depuis db."""
        from juslib.db import (
            VERSION_STATUS_IN_FORCE, VERSION_STATUS_REPEALED,
            VERSION_STATUS_SUSPENDED, VERSION_STATUS_NOT_YET,
            VERSION_STATUS_PARTIAL_REPEAL,
        )
        assert VERSION_STATUS_IN_FORCE == "in_force"
        assert VERSION_STATUS_REPEALED == "repealed"
        assert VERSION_STATUS_SUSPENDED == "suspended"

    def test_X04_certainty_client_provided_constant(self):
        """X04 : CERTAINTY_CLIENT_PROVIDED exporté."""
        from juslib.db import CERTAINTY_CLIENT_PROVIDED
        assert CERTAINTY_CLIENT_PROVIDED == "client_provided"

    def test_X05_single_version_no_overlap_check(self):
        """X05 : première version (provision vide) insérée sans erreur."""
        from juslib.db import JuslibDB
        db = JuslibDB()
        doc_id = db.insert_document(
            title="T", document_type="law", jurisdiction="FR",
            source_url="https://t.fr", connector_id="legifrance",
        )
        prov_id = db.insert_provision(doc_id, number="1")
        ver_id = db.insert_version(
            prov_id, doc_id, "Texte.", "2020-01-01", "https://t.fr/v1"
        )
        assert ver_id is not None
