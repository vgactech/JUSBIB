"""
JUSLIB — Corpus version model.

Chaque release du corpus JUSLIB est représentée par un CorpusVersion.
Format : YYYY.MM.DD-NNN (ex: 2026.10.04-001)

Invariants :
  - Un CorpusVersion est immuable une fois publié
  - Le corpus_hash est le SHA-256 de l'index complet du corpus
  - Le git_tag correspond à un tag Git annoté : corpus/YYYY.MM.DD-NNN
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ReleaseStatus(str, Enum):
    DRAFT = "draft"             # En cours de constitution
    PUBLISHED = "published"     # Publié (immuable)
    DEPRECATED = "deprecated"   # Remplacé par une version plus récente
    YANKED = "yanked"           # Retiré (erreur critique — très rare)


@dataclass
class CorpusVersion:
    """
    Release immuable du corpus juridique JUSLIB.

    Un tag Git annoté `corpus/YYYY.MM.DD-NNN` est créé à chaque publication.
    Le corpus_hash permet de vérifier l'intégrité de toute la release.
    """

    version_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version_label: str = ""             # Ex: "2026.10.04-001"
    status: ReleaseStatus = ReleaseStatus.DRAFT

    # --- Contenu ---
    document_count: int = 0
    disposition_count: int = 0
    jurisprudence_count: int = 0
    relation_count: int = 0

    # --- Couverture juridictionnelle ---
    jurisdictions_covered: list[str] = field(default_factory=list)
    languages_covered: list[str] = field(default_factory=list)
    sources_covered: list[str] = field(default_factory=list)

    # --- Intégrité ---
    corpus_hash: Optional[str] = None          # SHA-256 de l'index complet
    git_tag: Optional[str] = None              # Tag Git : "corpus/YYYY.MM.DD-NNN"
    git_commit_sha: Optional[str] = None       # SHA du commit Git correspondant

    # --- Changelog ---
    changelog_summary: Optional[str] = None
    documents_added: int = 0
    documents_modified: int = 0
    documents_repealed: int = 0

    # --- Temporalité ---
    published_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    # --- Validation ---
    validated_by: Optional[str] = None          # Identifiant du validateur
    validation_notes: Optional[str] = None

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.version_label:
            errors.append("version_label obligatoire (format: YYYY.MM.DD-NNN)")
        if self.status == ReleaseStatus.PUBLISHED and not self.corpus_hash:
            errors.append("corpus_hash obligatoire pour une release PUBLISHED")
        if self.status == ReleaseStatus.PUBLISHED and not self.git_tag:
            errors.append("git_tag obligatoire pour une release PUBLISHED")
        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "version_label": self.version_label,
            "status": self.status.value,
            "document_count": self.document_count,
            "disposition_count": self.disposition_count,
            "jurisprudence_count": self.jurisprudence_count,
            "relation_count": self.relation_count,
            "jurisdictions_covered": self.jurisdictions_covered,
            "languages_covered": self.languages_covered,
            "sources_covered": self.sources_covered,
            "corpus_hash": f"sha256:{self.corpus_hash}" if self.corpus_hash else None,
            "git_tag": self.git_tag,
            "git_commit_sha": self.git_commit_sha,
            "changelog_summary": self.changelog_summary,
            "documents_added": self.documents_added,
            "documents_modified": self.documents_modified,
            "documents_repealed": self.documents_repealed,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat(),
            "validated_by": self.validated_by,
        }
