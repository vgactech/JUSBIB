"""
JUSLIB — Corpus changelog builder.

Enregistre les modifications du corpus entre deux releases :
  - Documents ajoutés
  - Documents abrogés / supprimés
  - Documents modifiés (amendés)
  - Relations nouvelles / supprimées

Format de sortie : JSON structuré + Markdown lisible.
Invariant : un changelog ne supprime jamais les entrées précédentes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ChangeType(str, Enum):
    """Type de modification dans le corpus."""
    ADDED = "added"           # Nouveau document / nouvelle décision
    AMENDED = "amended"       # Texte modifié (nouvelle version)
    REPEALED = "repealed"     # Texte abrogé
    SUPERSEDED = "superseded" # Remplacé par un autre texte
    CORRECTED = "corrected"   # Erratum / correction matérielle
    INDEXED = "indexed"       # Nouvellement indexé (existait déjà mais absent du corpus)
    RELATION_ADDED = "relation_added"
    RELATION_REMOVED = "relation_removed"


@dataclass
class ChangeEntry:
    """Entrée individuelle dans le changelog du corpus."""
    change_type: ChangeType
    entity_id: str                         # juslib_id de l'entité concernée
    entity_type: str                       # "document" | "jurisprudence" | "relation"
    entity_title: Optional[str] = None    # Titre lisible
    jurisdiction: Optional[str] = None
    language: Optional[str] = None
    description: Optional[str] = None     # Description de la modification
    previous_version_id: Optional[str] = None  # ID de la version précédente
    effective_date: Optional[str] = None  # Date d'effet juridique
    corpus_version: Optional[str] = None  # Version du corpus

    def to_dict(self) -> dict:
        return {
            "change_type": self.change_type.value,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "entity_title": self.entity_title,
            "jurisdiction": self.jurisdiction,
            "language": self.language,
            "description": self.description,
            "previous_version_id": self.previous_version_id,
            "effective_date": self.effective_date,
            "corpus_version": self.corpus_version,
        }


class ChangelogBuilder:
    """
    Constructeur de changelog pour les releases JUSLIB.

    Exemple d'utilisation :
        builder = ChangelogBuilder(version_label="2026.10.04-001")
        builder.add(ChangeEntry(
            change_type=ChangeType.ADDED,
            entity_id="JUSLIB-REGULATION-EU-...",
            entity_type="document",
            entity_title="Règlement UE 2024/123",
        ))
        builder.save("juslib/data/corpus/changelogs/2026.10.04-001.json")
    """

    CHANGELOGS_DIR = "juslib/data/corpus/changelogs"

    def __init__(self, version_label: str):
        self.version_label = version_label
        self.entries: list[ChangeEntry] = []
        self.created_at = datetime.utcnow()
        os.makedirs(self.CHANGELOGS_DIR, exist_ok=True)

    def add(self, entry: ChangeEntry) -> None:
        """Ajoute une entrée au changelog."""
        entry.corpus_version = self.version_label
        self.entries.append(entry)

    def summary(self) -> dict:
        """Retourne un résumé statistique du changelog."""
        counts: dict[str, int] = {}
        for entry in self.entries:
            ct = entry.change_type.value
            counts[ct] = counts.get(ct, 0) + 1
        return {
            "version_label": self.version_label,
            "total_changes": len(self.entries),
            "by_type": counts,
            "created_at": self.created_at.isoformat(),
        }

    def to_dict(self) -> dict:
        return {
            "version_label": self.version_label,
            "created_at": self.created_at.isoformat(),
            "summary": self.summary(),
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_markdown(self) -> str:
        """Génère un changelog lisible en Markdown."""
        lines = [
            f"# JUSLIB Changelog — {self.version_label}",
            f"_Généré le {self.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}_",
            "",
            "## Résumé",
        ]
        s = self.summary()
        for change_type, count in s.get("by_type", {}).items():
            lines.append(f"- **{change_type}** : {count} entrée(s)")
        lines.append("")

        # Grouper par type
        by_type: dict[str, list[ChangeEntry]] = {}
        for entry in self.entries:
            t = entry.change_type.value
            by_type.setdefault(t, []).append(entry)

        for change_type, entries in sorted(by_type.items()):
            lines.append(f"## {change_type.upper()}")
            for e in entries:
                title = e.entity_title or e.entity_id
                jur = f" [{e.jurisdiction}]" if e.jurisdiction else ""
                desc = f" — {e.description}" if e.description else ""
                lines.append(f"- `{e.entity_id}`{jur} — {title}{desc}")
            lines.append("")

        return "\n".join(lines)

    def save(self, path: Optional[str] = None) -> str:
        """
        Sauvegarde le changelog (JSON + Markdown).
        Invariant : jamais d'écrasement — si le fichier existe, append une version.
        """
        target_dir = self.CHANGELOGS_DIR
        json_path = path or os.path.join(target_dir, f"{self.version_label}.json")
        md_path = json_path.replace(".json", ".md")

        # Jamais d'écrasement
        if os.path.exists(json_path):
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            json_path = json_path.replace(".json", f"_{timestamp}.json")
            md_path = md_path.replace(".md", f"_{timestamp}.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())

        return json_path
