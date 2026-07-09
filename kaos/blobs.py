"""Content-addressable blob store with SHA-256 deduplication and zstd compression."""

from __future__ import annotations

import hashlib
import sqlite3

import zstandard as zstd


class BlobStore:
    """Manages content-addressable blob storage with dedup and compression."""

    def __init__(self, conn, compression: str = "zstd"):
        # `conn` may be a live sqlite3.Connection OR a zero-arg callable that
        # returns the current thread's connection. The callable form lets the
        # store resolve a thread-local connection instead of pinning the one
        # present at construction time (which would split cross-thread writes
        # across two connections).
        self._conn_ref = conn
        self.use_compression = compression == "zstd"
        if self.use_compression:
            self._compressor = zstd.ZstdCompressor(level=3)
            self._decompressor = zstd.ZstdDecompressor()

    @property
    def conn(self) -> sqlite3.Connection:
        # NB: sqlite3.Connection is itself callable, so discriminate by type
        # rather than callable() — a raw Connection is returned as-is; a getter
        # callable is invoked to resolve the current thread's connection.
        ref = self._conn_ref
        return ref if isinstance(ref, sqlite3.Connection) else ref()

    def store(self, content: bytes) -> tuple[str, int]:
        """Store content, returning (content_hash, size). Deduplicates automatically."""
        content_hash = hashlib.sha256(content).hexdigest()
        size = len(content)

        existing = self.conn.execute(
            "SELECT ref_count FROM blobs WHERE content_hash = ?", (content_hash,)
        ).fetchone()

        if existing:
            self.conn.execute(
                "UPDATE blobs SET ref_count = ref_count + 1 WHERE content_hash = ?",
                (content_hash,),
            )
        else:
            if self.use_compression:
                stored_content = self._compressor.compress(content)
                compressed = 1
            else:
                stored_content = content
                compressed = 0

            self.conn.execute(
                "INSERT INTO blobs (content_hash, content, compressed, ref_count) "
                "VALUES (?, ?, ?, 1)",
                (content_hash, stored_content, compressed),
            )

        return content_hash, size

    def retrieve(self, content_hash: str) -> bytes:
        """Retrieve content by hash. Raises KeyError if not found."""
        row = self.conn.execute(
            "SELECT content, compressed FROM blobs WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()

        if not row:
            raise KeyError(f"Blob not found: {content_hash}")

        content, compressed = row
        if compressed:
            return self._decompressor.decompress(content)
        return bytes(content)

    def release(self, content_hash: str) -> None:
        """Decrement ref count. Deletes blob when ref_count reaches 0."""
        self.conn.execute(
            "UPDATE blobs SET ref_count = ref_count - 1 WHERE content_hash = ?",
            (content_hash,),
        )
        self.conn.execute(
            "DELETE FROM blobs WHERE content_hash = ? AND ref_count <= 0",
            (content_hash,),
        )

    def gc(self) -> int:
        """Garbage collect orphaned blobs. Returns number of blobs removed."""
        cursor = self.conn.execute(
            "DELETE FROM blobs WHERE ref_count <= 0"
        )
        return cursor.rowcount

    def stats(self) -> dict:
        """Return blob store statistics."""
        row = self.conn.execute(
            "SELECT COUNT(*), SUM(LENGTH(content)), SUM(ref_count) FROM blobs"
        ).fetchone()
        return {
            "total_blobs": row[0] or 0,
            "total_stored_bytes": row[1] or 0,
            "total_references": row[2] or 0,
        }
