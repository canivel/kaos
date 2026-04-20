"""Obsidian vault exporter — render a KAOS database as a wikilinked markdown vault.

Usage (Python)::

    from kaos.obsidian import VaultExporter
    VaultExporter("project.db", "~/vaults/kaos-eng").export_all()

Usage (CLI)::

    kaos obsidian export --vault ~/vaults/kaos-eng --db project.db

The exporter is one-way and re-runnable: running it again against the same
vault refreshes the notes without disturbing Obsidian's own state (.obsidian/
cache, workspace layout). Pass --clean to wipe the vault before export.
"""

from kaos.obsidian.exporter import VaultExporter

__all__ = ["VaultExporter"]
