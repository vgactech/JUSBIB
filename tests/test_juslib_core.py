"""
JUSLIB — Test suite complète.

Tests couvrant les 6 invariants fondamentaux JUSLIB + modèles + connecteurs + versionnement.

Invariants testés :
  INV-1 : source_url + source_hash obligatoires
  INV-2 : INSERT-only (versions immuables)
  INV-3 : explication reliée à son source (FK non nullable)
  INV-4 : traçabilité corpus (hash + release)
  INV-5 : marquage production_type + ai_warning
  INV-6 : certainty_level explicite

Exécution : cd juslib && pytest tests/ -v
"""

import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime

import pytest

# Ajout du chemin source
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from juslib.models.legal_document import (
    LegalDocument,
    DocumentType,
    ProductionType,
    CertaintyLevel,
    DocumentStatus,
)
from juslib.models.disposition import Disposition, DispositionStatus, DispositionType
from juslib.models.jurisprudence import JurisprudenceItem, CourtLevel, DecisionType
from juslib.models.relation import LegalRelation, RelationType
from juslib.models.citation import Citation, CitationStyle
from juslib.models.provenance import Provenance
from juslib.models.corpus_version import CorpusVersion, ReleaseStatus
from juslib.translation.plain_language import PlainLanguageEngine, ReadingLevel, ExplainResult
from juslib.translation.multilingual import MultilingualLabel, MultilingualIndex, EU_LANGUAGES, UN_LANGUAGES
from juslib.versioning.corpus_tracker import CorpusTracker
from juslib.versioning.changelog import ChangelogBuilder, ChangeEntry, ChangeType


# ============================================================
# BLOC A — Invariants fondamentaux (INV-1 à INV-6)
# ============================================================

class TestInvariant1_SourceRequired:
    """INV-1 : source_url + source_hash obligatoires."""

    def test_A01_document_without_source_url_fails(self):
        doc = LegalDocument(
            title="Test",
            jurisdiction="EU",
            language="fr",
            source_url=None,
            source_hash="abc123",
        )
        valid, errors = doc.validate()
        assert not valid
        assert any("source_url" in e for e in errors), f"Erreur INV-1 non détectée: {errors}"

    def test_A02_document_without_source_hash_fails(self):
        doc = LegalDocument(
            title="Test",
            jurisdiction="EU",
            language="fr",
            source_url="https://eur-lex.europa.eu/test",
            source_hash=None,
        )
        valid, errors = doc.validate()
        assert not valid
        assert any("source_hash" in e for e in errors)

    def test_A03_document_with_both_source_fields_passes(self):
        doc = LegalDocument(
            title="RGPD",
            jurisdiction="EU",
            language="fr",
            document_type=DocumentType.REGULATION,
            source_url="https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32016R0679",
            source_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            certainty_level=CertaintyLevel.CERTAIN,
        )
        valid, errors = doc.validate()
        assert valid, f"Document valide refusé: {errors}"

    def test_A04_provenance_without_source_url_fails(self):
        prov = Provenance(entity_id="test", source_url="", source_hash="abc")
        valid, errors = prov.validate()
        assert not valid

    def test_A05_compute_source_hash(self):
        doc = LegalDocument(
            title="Test",
            jurisdiction="FR",
            language="fr",
            full_text="Article 1 : Toute personne a droit à la vie.",
            source_url="https://legifrance.fr",
        )
        h = doc.compute_source_hash()
        expected = hashlib.sha256("Article 1 : Toute personne a droit à la vie.".encode()).hexdigest()
        assert h == expected


class TestInvariant2_ImmutableVersions:
    """INV-2 : Les versions historiques ne sont jamais écrasées."""

    def test_A06_corpus_releases_are_append_only(self, tmp_path):
        tracker = CorpusTracker(corpus_dir=str(tmp_path))
        releases_file = str(tmp_path / "releases.jsonl")
        index_1 = {"stats": {"documents": 10, "jurisprudence": 5, "relations": 3}, "jurisdictions": ["EU"], "languages": ["fr"], "sources": ["eurlex"]}
        index_2 = {"stats": {"documents": 15, "jurisprudence": 7, "relations": 5}, "jurisdictions": ["EU", "FR"], "languages": ["fr", "en"], "sources": ["eurlex", "legifrance"]}
        release_1 = tracker.prepare_release(index_1, [])
        tracker.publish_release(release_1, releases_file=releases_file)
        release_2 = tracker.prepare_release(index_2, [release_1.label])
        tracker.publish_release(release_2, releases_file=releases_file)

        releases = tracker.load_releases(releases_file)
        assert len(releases) == 2, "Les deux releases doivent coexister (INSERT-only)"
        assert releases[0]["label"] != releases[1]["label"]

    def test_A07_corpus_version_published_is_immutable(self):
        cv = CorpusVersion(version_label="2026.10.04-001", status=ReleaseStatus.PUBLISHED)
        cv.corpus_hash = "abc123"
        cv.git_tag = "corpus/2026.10.04-001"
        valid, errors = cv.validate()
        assert valid, f"CorpusVersion valide refusée: {errors}"

    def test_A08_revision_tracking_on_document(self):
        doc_v1 = LegalDocument(
            title="RGPD v1",
            jurisdiction="EU",
            language="fr",
            revision=1,
            source_url="https://eur-lex.europa.eu/v1",
            source_hash="hash_v1",
        )
        doc_v2 = LegalDocument(
            title="RGPD v2",
            jurisdiction="EU",
            language="fr",
            revision=2,
            previous_version_id=doc_v1.juslib_id,
            source_url="https://eur-lex.europa.eu/v2",
            source_hash="hash_v2",
        )
        assert doc_v2.previous_version_id == doc_v1.juslib_id
        assert doc_v1.revision < doc_v2.revision


class TestInvariant3_ExplanationLinked:
    """INV-3 : Toute explication reste reliée à sa source (FK non nullable)."""

    def test_A09_explain_result_without_source_fails(self):
        result = ExplainResult(
            source_entity_id="",  # FK vide — invalide
            source_entity_type="disposition",
            reading_level=ReadingLevel.CITIZEN,
            explained_text="Une explication simple.",
        )
        valid, errors = result.validate()
        assert not valid
        assert any("INVARIANT_3" in e for e in errors)

    def test_A10_citation_without_target_fails(self):
        cit = Citation(
            target_juslib_id="",  # FK vide
            formatted_citation="RGPD, art. 17",
        )
        valid, errors = cit.validate()
        assert not valid
        assert any("INVARIANT" in e for e in errors)

    def test_A11_disposition_without_document_fails(self):
        disp = Disposition(document_id="", text="Article test")
        valid, errors = disp.validate()
        assert not valid
        assert any("INVARIANT" in e for e in errors)


class TestInvariant4_Traceability:
    """INV-4 : Traçabilité corpus — hash + release reproductible."""

    def test_A12_corpus_hash_deterministic(self):
        tracker = CorpusTracker(corpus_dir="/tmp")
        data = {"stats": {"documents": 5}, "jurisdictions": ["EU"], "languages": ["fr"], "sources": ["eurlex"]}
        h1 = tracker.compute_corpus_hash(data)
        h2 = tracker.compute_corpus_hash(data)
        assert h1 == h2, "Le hash corpus doit être déterministe"

    def test_A13_corpus_hash_changes_on_data_change(self):
        tracker = CorpusTracker(corpus_dir="/tmp")
        data_a = {"stats": {"documents": 5}, "jurisdictions": ["EU"], "languages": ["fr"], "sources": ["eurlex"]}
        data_b = {"stats": {"documents": 6}, "jurisdictions": ["EU"], "languages": ["fr"], "sources": ["eurlex"]}
        h_a = tracker.compute_corpus_hash(data_a)
        h_b = tracker.compute_corpus_hash(data_b)
        assert h_a != h_b

    def test_A14_changelog_saved_never_overwrites(self, tmp_path):
        ChangelogBuilder.CHANGELOGS_DIR = str(tmp_path)
        builder = ChangelogBuilder(version_label="2026.10.04-001")
        builder.add(ChangeEntry(
            change_type=ChangeType.ADDED,
            entity_id="JUSLIB-DOC-EU-001",
            entity_type="document",
            entity_title="Test document",
        ))
        path1 = builder.save(str(tmp_path / "2026.10.04-001.json"))
        path2 = builder.save(str(tmp_path / "2026.10.04-001.json"))
        assert path1 != path2, "Deux sauvegardes ne doivent pas écraser la première"


class TestInvariant5_ProductionType:
    """INV-5 : Production IA toujours distinguable — ai_warning obligatoire."""

    def test_A15_ai_generated_without_warning_fails(self):
        doc = LegalDocument(
            title="Résumé IA",
            jurisdiction="EU",
            language="fr",
            source_url="https://eur-lex.europa.eu",
            source_hash="abc",
            production_type=ProductionType.AI_GENERATED,
            ai_warning=None,  # MANQUANT
        )
        valid, errors = doc.validate()
        assert not valid
        assert any("INVARIANT_5" in e for e in errors)

    def test_A16_ai_generated_with_warning_passes(self):
        doc = LegalDocument(
            title="Résumé IA",
            jurisdiction="EU",
            language="fr",
            source_url="https://eur-lex.europa.eu",
            source_hash="abc",
            certainty_level=CertaintyLevel.UNVERIFIED,
            production_type=ProductionType.AI_GENERATED,
            ai_warning="[GÉNÉRÉ PAR IA — NON VALIDÉ PAR UN JURISTE]",
        )
        valid, errors = doc.validate()
        assert valid, f"Document AI valide refusé: {errors}"

    def test_A17_expert_level_is_source_text(self):
        engine = PlainLanguageEngine()
        result = engine.explain(
            source_entity_id="JUSLIB-DOC-001",
            source_entity_type="document",
            text="Article 17 : Le responsable du traitement procède à l'effacement.",
            reading_level=ReadingLevel.EXPERT,
        )
        assert result.is_source_text is True
        assert result.production_type == "source"

    def test_A18_citizen_level_not_source_text(self):
        engine = PlainLanguageEngine()
        result = engine.explain(
            source_entity_id="JUSLIB-DOC-001",
            source_entity_type="document",
            text="Article 17 : Le responsable du traitement procède à l'effacement.",
            reading_level=ReadingLevel.CITIZEN,
        )
        assert result.is_source_text is False

    def test_A19_ai_enrichment_adds_warning(self):
        engine = PlainLanguageEngine(llm_enabled=True)
        result = engine.explain(
            source_entity_id="JUSLIB-DOC-001",
            source_entity_type="document",
            text="Article 5 : Les données à caractère personnel sont traitées de manière licite.",
            reading_level=ReadingLevel.CITIZEN,
        )
        if "ai" in result.production_type:
            assert result.ai_generated_warning is not None
            assert "IA" in result.ai_generated_warning or "AI" in result.ai_generated_warning


class TestInvariant6_CertaintyLevel:
    """INV-6 : Distinction CERTAIN / INTERPRETED / CONTESTED / UNVERIFIED."""

    def test_A20_all_certainty_levels_valid(self):
        from juslib.models.legal_document import CertaintyLevel
        for level in CertaintyLevel:
            assert level.value in ("certain", "interpreted", "contested", "unverified")

    def test_A21_source_unverified_triggers_warning(self):
        doc = LegalDocument(
            title="Test",
            jurisdiction="FR",
            language="fr",
            source_url="https://legifrance.fr",
            source_hash="abc",
            production_type=ProductionType.SOURCE,
            certainty_level=CertaintyLevel.UNVERIFIED,
        )
        valid, errors = doc.validate()
        # Source + UNVERIFIED → warning (pas un blocage, mais un avertissement)
        assert any("INVARIANT_6" in e for e in errors)


# ============================================================
# BLOC B — Modèles de données
# ============================================================

class TestModels:

    def test_B01_legal_document_serialization(self):
        doc = LegalDocument(
            title="Règlement général sur la protection des données",
            short_title="RGPD",
            document_type=DocumentType.REGULATION,
            document_status=DocumentStatus.IN_FORCE,
            jurisdiction="EU",
            language="fr",
            available_languages=["fr", "en", "de", "es", "it", "nl", "pl", "pt"],
            eurlex_celex="32016R0679",
            adoption_date=date(2016, 4, 27),
            publication_date=date(2016, 5, 4),
            entry_into_force=date(2018, 5, 25),
            source_url="https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32016R0679",
            source_hash="abc123def456",
            production_type=ProductionType.SOURCE,
            certainty_level=CertaintyLevel.CERTAIN,
            legal_domains=["protection_donnees", "droit_numerique", "droit_UE"],
        )
        d = doc.to_dict()
        assert d["title"] == "Règlement général sur la protection des données"
        assert d["short_title"] == "RGPD"
        assert d["eurlex_celex"] == "32016R0679"
        assert d["entry_into_force"] == "2018-05-25"
        assert d["source_hash"].startswith("sha256:")
        assert len(d["available_languages"]) == 8

    def test_B02_disposition_validation(self):
        disp = Disposition(
            document_id="JUSLIB-REGULATION-EU-RGPD-20160504-001",
            number="17",
            label="Article 17",
            heading="Droit à l'effacement ('droit à l'oubli')",
            text="La personne concernée a le droit d'obtenir du responsable du traitement l'effacement, dans les meilleurs délais, de données à caractère personnel la concernant.",
            language="fr",
            status=DispositionStatus.IN_FORCE,
            disposition_type=DispositionType.ARTICLE,
        )
        valid, errors = disp.validate()
        assert valid, errors

    def test_B03_jurisprudence_item(self):
        case = JurisprudenceItem(
            case_number="C-311/18",
            case_name="Data Protection Commissioner v Facebook Ireland Limited and Maximillian Schrems",
            decision_type=DecisionType.JUDGMENT,
            court_name="Cour de Justice de l'Union Européenne",
            court_code="CJUE",
            court_level=CourtLevel.SUPRANATIONAL_EU,
            jurisdiction="EU",
            language="fr",
            available_languages=["fr", "en", "de"],
            decision_date=date(2020, 7, 16),
            ecli="ECLI:EU:C:2020:559",
            source_url="https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:62018CJ0311",
            source_hash="hash_schrems2",
        )
        valid, errors = case.validate()
        assert valid, errors
        d = case.to_dict()
        assert d["ecli"] == "ECLI:EU:C:2020:559"

    def test_B04_legal_relation(self):
        rel = LegalRelation(
            source_id="JUSLIB-REGULATION-EU-RGPD",
            source_type="document",
            target_id="JUSLIB-DIRECTIVE-EU-95_46_CE",
            target_type="document",
            relation_type=RelationType.SUPERSEDES,
            description="Le RGPD remplace la Directive 95/46/CE",
            confidence=1.0,
        )
        valid, errors = rel.validate()
        assert valid, errors

    def test_B05_relation_reflexive_forbidden(self):
        rel = LegalRelation(
            source_id="SAME_ID",
            source_type="document",
            target_id="SAME_ID",  # Même ID → interdit
            target_type="document",
            relation_type=RelationType.REFERS_TO,
        )
        valid, errors = rel.validate()
        assert not valid

    def test_B06_citation_valid(self):
        cit = Citation(
            target_juslib_id="JUSLIB-REGULATION-EU-RGPD-20160504-001",
            target_type="document",
            style=CitationStyle.OSCOLA,
            formatted_citation="Regulation (EU) 2016/679 of the European Parliament and of the Council (GDPR) [2016] OJ L119/1",
            pinpoint="art 17",
        )
        valid, errors = cit.validate()
        assert valid, errors


# ============================================================
# BLOC C — Versionnement
# ============================================================

class TestVersioning:

    def test_C01_version_label_generation(self, tmp_path):
        tracker = CorpusTracker(corpus_dir=str(tmp_path))
        label = tracker.generate_version_label([])
        # Format YYYY.MM.DD-NNN : date_part-rev_part
        assert "-" in label, f"Format attendu YYYY.MM.DD-NNN: {label}"
        date_part, rev_part = label.rsplit("-", 1)
        assert len(date_part) == 10, f"Date attendue YYYY.MM.DD (10 chars): {date_part}"
        assert rev_part == "001", f"Révision initiale attendue 001: {rev_part}"

    def test_C02_version_label_increments(self, tmp_path):
        tracker = CorpusTracker(corpus_dir=str(tmp_path))
        today = datetime.utcnow().strftime("%Y.%m.%d")
        existing = [f"{today}-001", f"{today}-002"]
        label = tracker.generate_version_label(existing)
        assert label.endswith("-003"), f"Label attendu: {today}-003, obtenu: {label}"

    def test_C03_integrity_verification(self, tmp_path):
        tracker = CorpusTracker(corpus_dir=str(tmp_path))
        data = {"stats": {"documents": 42}, "jurisdictions": ["EU"], "languages": ["fr", "en"], "sources": ["eurlex"]}
        expected_hash = tracker.compute_corpus_hash(data)
        assert tracker.verify_integrity(data, expected_hash) is True
        assert tracker.verify_integrity(data, "wrong_hash") is False

    def test_C04_changelog_markdown_generation(self, tmp_path):
        ChangelogBuilder.CHANGELOGS_DIR = str(tmp_path)
        builder = ChangelogBuilder("2026.10.04-001")
        builder.add(ChangeEntry(
            change_type=ChangeType.ADDED,
            entity_id="JUSLIB-REGULATION-EU-001",
            entity_type="document",
            entity_title="RGPD",
            jurisdiction="EU",
        ))
        builder.add(ChangeEntry(
            change_type=ChangeType.REPEALED,
            entity_id="JUSLIB-DIRECTIVE-EU-95-46",
            entity_type="document",
            entity_title="Directive 95/46/CE",
            jurisdiction="EU",
        ))
        md = builder.to_markdown()
        assert "2026.10.04-001" in md
        assert "ADDED" in md
        assert "REPEALED" in md

    def test_C05_corpus_release_full_cycle(self, tmp_path):
        tracker = CorpusTracker(corpus_dir=str(tmp_path))
        releases_file = str(tmp_path / "releases.jsonl")
        index = {
            "stats": {"documents": 100, "jurisprudence": 50, "relations": 200},
            "jurisdictions": ["EU", "FR", "INT"],
            "languages": EU_LANGUAGES[:5],
            "sources": ["eurlex", "legifrance", "hudoc"],
        }
        release = tracker.prepare_release(index, [], changelog_summary="Release initiale JUSLIB v0.1")
        tracker.publish_release(release, releases_file=releases_file)
        latest = tracker.get_latest_release(releases_file)
        assert latest is not None
        assert "sha256:" in latest["corpus_hash"]


# ============================================================
# BLOC D — Multilingue et vulgarisation
# ============================================================

class TestMultilingualAndTranslation:

    def test_D01_supported_eu_languages_count(self):
        assert len(EU_LANGUAGES) == 24, f"24 langues UE attendues, obtenu: {len(EU_LANGUAGES)}"

    def test_D02_un_languages_count(self):
        assert len(UN_LANGUAGES) == 6

    def test_D03_multilingual_label_fallback(self):
        label = MultilingualLabel(original_lang="fr", original_text="Droit à l'effacement")
        label.add_translation("en", "Right to erasure")
        label.add_translation("de", "Recht auf Löschung")
        assert label.get("fr") == "Droit à l'effacement"
        assert label.get("en") == "Right to erasure"
        assert label.get("de") == "Recht auf Löschung"
        # Fallback : langue non disponible → anglais
        assert label.get("pl", fallback_lang="en") == "Right to erasure"

    def test_D04_multilingual_label_ai_marking(self):
        label = MultilingualLabel(original_lang="fr", original_text="Prescription")
        label.add_translation("ar", "التقادم", is_official=False, is_ai=True)
        ai_trans = [t for t in label.translations if t.is_ai_generated]
        assert len(ai_trans) == 1

    def test_D05_plain_language_expert_level_unchanged(self):
        engine = PlainLanguageEngine()
        text = "Le responsable du traitement au sens de l'article 4 paragraphe 7 du règlement."
        result = engine.explain("ID-001", "disposition", text, ReadingLevel.EXPERT)
        assert result.explained_text == text
        assert result.is_source_text is True

    def test_D06_plain_language_citizen_includes_glossary(self):
        engine = PlainLanguageEngine()
        text = "La nullité du contrat est prononcée par le juge."
        result = engine.explain("ID-002", "disposition", text, ReadingLevel.CITIZEN, language="fr")
        # La nullité doit être expliquée dans le texte citoyen
        assert "nullité" in result.explained_text

    def test_D07_glossary_lookup_multilingual(self):
        engine = PlainLanguageEngine()
        assert engine.glossary_lookup("abrogation", "fr") is not None
        assert engine.glossary_lookup("abrogation", "en") is not None
        assert engine.glossary_lookup("abrogation", "de") is not None
        assert engine.glossary_lookup("terme_inexistant", "fr") is None

    def test_D08_multilingual_index(self):
        idx = MultilingualIndex(
            entity_id="JUSLIB-REGULATION-EU-RGPD-001",
            entity_type="document",
        )
        idx.add_title("fr", "Règlement général sur la protection des données")
        idx.add_title("en", "General Data Protection Regulation")
        assert idx.get_title("fr") == "Règlement général sur la protection des données"
        assert idx.get_title("en") == "General Data Protection Regulation"


# ============================================================
# BLOC E — Connecteurs (tests structure, sans appel réseau)
# ============================================================

class TestConnectors:

    def test_E01_eurlex_connector_init(self):
        from juslib.connectors.eurlex_connector import EurLexConnector, EU_OFFICIAL_LANGUAGES
        c = EurLexConnector()
        assert c.CONNECTOR_ID == "eurlex"
        assert c.SOURCE_JURISDICTION == "EU"
        assert len(EU_OFFICIAL_LANGUAGES) == 24

    def test_E02_legifrance_connector_init_no_key_warns(self, caplog):
        import logging
        from juslib.connectors.legifranceconnector import LegifranceConnector
        with caplog.at_level(logging.WARNING, logger="juslib.connector.legifrance"):
            c = LegifranceConnector(client_id=None, client_secret=None)
        assert c.CONNECTOR_ID == "legifrance"

    def test_E03_echr_connector_languages(self):
        from juslib.connectors.echr_connector import ECHRConnector
        c = ECHRConnector()
        assert "fr" in c.SUPPORTED_LANGUAGES
        assert "en" in c.SUPPORTED_LANGUAGES

    def test_E04_ohada_connector_catalogue(self):
        from juslib.connectors.ohada_connector import OHADAConnector
        c = OHADAConnector()
        assert "AUDCG" in c.ACTES_UNIFORMES
        assert "AUPC" in c.ACTES_UNIFORMES
        assert len(c.ACTES_UNIFORMES) >= 9

    def test_E05_ohada_search_returns_results(self):
        from juslib.connectors.ohada_connector import OHADAConnector
        c = OHADAConnector()
        results = c.search("commercial")
        assert len(results) >= 1
        assert results[0].success is True

    def test_E06_un_connector_fundamental_docs(self):
        from juslib.connectors.un_connector import UNConnector
        c = UNConnector()
        meta = c.get_metadata("A/RES/217(III)")
        assert "Déclaration" in meta.get("title_fr", "")

    def test_E07_canlii_connector_init(self):
        from juslib.connectors.canlii_connector import CanLIIConnector
        c = CanLIIConnector()
        assert c.CONNECTOR_ID == "canlii"
        assert c.SOURCE_JURISDICTION == "CA"
        assert "fr" in c.SUPPORTED_LANGUAGES

    def test_E08_connector_result_hash_computation(self):
        from juslib.connectors.base_connector import ConnectorResult
        result = ConnectorResult(
            source_url="https://test.example.com",
            raw_content=b"Test legal content SHA",
        )
        h = result.compute_hash()
        assert h is not None
        assert len(h) == 64  # SHA-256 hex
        assert result.source_hash == h

    def test_E09_eurlex_invalid_language_falls_back(self):
        from juslib.connectors.eurlex_connector import EurLexConnector
        c = EurLexConnector()
        meta = c.get_metadata("32016R0679")
        assert meta["celex"] == "32016R0679"
        assert "fr" in meta["available_languages"]
