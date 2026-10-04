"""
JUSLIB — Corpus tracker and release management.

Gère les releases immuables du corpus juridique JUSLIB.
Chaque release est :
  1. Identifiée par un label YYYY.MM.DD-NNN
  2. Associée à un tag Git annoté corpus/YYYY.MM.DD-NNN
  3. Hashée (SHA-256 de l'index complet) pour intégrité
  4. Jamais modifiable une fois publiée (PUBLISHED)

Invariant fondamental : INSERT-only — les releases publiées sont immuables.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("juslib.versioning.corpus_tracker")


@dataclass
class CorpusRelease:
    """
    Snapshot immuable du corpus JUSLIB à un instant donné.
    Identique à CorpusVersion mais orienté runtime (sans persistance).
    """
    label: str                          # "2026.10.04-001"
    git_tag: str                        # "corpus/2026.10.04-001"
    git_commit_sha: Optional[str]
    corpus_hash: Optional[str]          # SHA-256 de l'index JSON
    document_count: int
    jurisprudence_count: int
    relation_count: int
    jurisdictions: list[str]
    languages: list[str]
    sources: list[str]
    published_at: datetime
    changelog_summary: Optional[str] = None


class CorpusTracker:
    """
    Gestionnaire de versions du corpus JUSLIB.

    Responsabilités :
      1. Calculer le hash d'un corpus (intégrité)
      2. Préparer une release (DRAFT → PUBLISHED)
      3. Créer les tags Git
      4. Enregistrer le changelog
    """

    RELEASES_FILE = "juslib/data/corpus/releases.jsonl"  # Append-only

    def __init__(self, corpus_dir: str = "juslib/data/corpus", debug: bool = True):
        self.corpus_dir = corpus_dir
        self.debug = debug
        self._log = logging.getLogger("juslib.corpus_tracker")
        self._log.setLevel(logging.DEBUG if debug else logging.INFO)
        os.makedirs(corpus_dir, exist_ok=True)

    def compute_corpus_hash(self, index_data: dict) -> str:
        """
        Calcule le SHA-256 de l'index corpus (sérialisé JSON canonique).
        Le JSON canonique utilise sort_keys=True pour la reproductibilité.
        """
        canonical_json = json.dumps(index_data, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        self._log.debug("[CORPUS] hash computed: %s…", h[:16])
        return h

    def generate_version_label(self, existing_labels: list[str]) -> str:
        """
        Génère le prochain label de version pour la date courante.
        Format : YYYY.MM.DD-NNN (incrémente NNN si même date).
        """
        today = datetime.utcnow().strftime("%Y.%m.%d")
        same_day = [l for l in existing_labels if l.startswith(today)]
        rev = len(same_day) + 1
        label = f"{today}-{rev:03d}"
        self._log.debug("[CORPUS] generated label: %s", label)
        return label

    def prepare_release(
        self,
        index_data: dict,
        existing_labels: list[str],
        changelog_summary: Optional[str] = None,
        git_commit_sha: Optional[str] = None,
    ) -> CorpusRelease:
        """
        Prépare une nouvelle release DRAFT.
        Ne publie pas encore — appeler publish_release() ensuite.
        """
        label = self.generate_version_label(existing_labels)
        git_tag = f"corpus/{label}"
        corpus_hash = self.compute_corpus_hash(index_data)

        stats = index_data.get("stats", {})
        release = CorpusRelease(
            label=label,
            git_tag=git_tag,
            git_commit_sha=git_commit_sha,
            corpus_hash=corpus_hash,
            document_count=stats.get("documents", 0),
            jurisprudence_count=stats.get("jurisprudence", 0),
            relation_count=stats.get("relations", 0),
            jurisdictions=index_data.get("jurisdictions", []),
            languages=index_data.get("languages", []),
            sources=index_data.get("sources", []),
            published_at=datetime.utcnow(),
            changelog_summary=changelog_summary,
        )
        self._log.info("[CORPUS] Release préparée: %s (hash=%s…)", label, corpus_hash[:12])
        return release

    def publish_release(
        self,
        release: CorpusRelease,
        releases_file: Optional[str] = None,
    ) -> None:
        """
        Publie la release (DRAFT → PUBLISHED).
        Enregistre dans le fichier JSONL append-only.

        Invariant : jamais d'écrasement — append uniquement.
        """
        target = releases_file or self.RELEASES_FILE
        os.makedirs(os.path.dirname(target), exist_ok=True)

        entry = {
            "label": release.label,
            "git_tag": release.git_tag,
            "git_commit_sha": release.git_commit_sha,
            "corpus_hash": f"sha256:{release.corpus_hash}" if release.corpus_hash else None,
            "document_count": release.document_count,
            "jurisprudence_count": release.jurisprudence_count,
            "relation_count": release.relation_count,
            "jurisdictions": release.jurisdictions,
            "languages": release.languages,
            "sources": release.sources,
            "published_at": release.published_at.isoformat(),
            "changelog_summary": release.changelog_summary,
        }

        # APPEND-ONLY — jamais d'écrasement
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        self._log.info("[CORPUS] Release publiée: %s → %s", release.label, target)

    def load_releases(self, releases_file: Optional[str] = None) -> list[dict]:
        """Charge toutes les releases depuis le fichier JSONL."""
        target = releases_file or self.RELEASES_FILE
        if not os.path.exists(target):
            self._log.debug("[CORPUS] Aucun fichier releases trouvé: %s", target)
            return []
        releases = []
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    releases.append(json.loads(line))
        self._log.debug("[CORPUS] %d releases chargées depuis %s", len(releases), target)
        return releases

    def get_latest_release(self, releases_file: Optional[str] = None) -> Optional[dict]:
        """Retourne la dernière release publiée."""
        releases = self.load_releases(releases_file)
        return releases[-1] if releases else None

    def verify_integrity(self, index_data: dict, expected_hash: str) -> bool:
        """Vérifie l'intégrité d'un index corpus contre un hash attendu."""
        actual = self.compute_corpus_hash(index_data)
        ok = actual == expected_hash
        self._log.debug(
            "[CORPUS] verify_integrity: expected=%s… actual=%s… → %s",
            expected_hash[:12], actual[:12], "OK" if ok else "FAIL",
        )
        return ok
