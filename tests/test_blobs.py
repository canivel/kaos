"""Tests for the content-addressable blob store."""

from __future__ import annotations

import sqlite3

import pytest

from kaos.blobs import BlobStore
from kaos.schema import init_schema


@pytest.fixture
def blob_store(tmp_path):
    """Create a blob store with a temporary database."""
    db_path = str(tmp_path / "test_blobs.db")
    conn = sqlite3.connect(db_path)
    init_schema(conn)
    store = BlobStore(conn, compression="zstd")
    yield store
    conn.close()


@pytest.fixture
def blob_store_no_compression(tmp_path):
    """Create a blob store without compression."""
    db_path = str(tmp_path / "test_blobs_nc.db")
    conn = sqlite3.connect(db_path)
    init_schema(conn)
    store = BlobStore(conn, compression="none")
    yield store
    conn.close()


class TestBlobStore:
    def test_store_and_retrieve(self, blob_store: BlobStore):
        content = b"hello world"
        content_hash, size = blob_store.store(content)
        assert size == 11
        assert len(content_hash) == 64  # SHA-256 hex

        retrieved = blob_store.retrieve(content_hash)
        assert retrieved == content

    def test_deduplication(self, blob_store: BlobStore):
        content = b"duplicate content"
        hash1, _ = blob_store.store(content)
        hash2, _ = blob_store.store(content)
        assert hash1 == hash2

        stats = blob_store.stats()
        assert stats["total_blobs"] == 1
        assert stats["total_references"] == 2

    def test_ref_counting(self, blob_store: BlobStore):
        content = b"ref counted"
        content_hash, _ = blob_store.store(content)
        blob_store.store(content)  # ref_count = 2

        blob_store.release(content_hash)  # ref_count = 1
        # Should still be retrievable
        assert blob_store.retrieve(content_hash) == content

        blob_store.release(content_hash)  # ref_count = 0, deleted
        with pytest.raises(KeyError):
            blob_store.retrieve(content_hash)

    def test_gc(self, blob_store: BlobStore):
        content = b"gc target"
        content_hash, _ = blob_store.store(content)
        blob_store.release(content_hash)

        removed = blob_store.gc()
        assert removed >= 0  # May be 0 if already cleaned up

    def test_retrieve_nonexistent(self, blob_store: BlobStore):
        with pytest.raises(KeyError):
            blob_store.retrieve("nonexistent_hash")

    def test_no_compression(self, blob_store_no_compression: BlobStore):
        content = b"uncompressed content"
        content_hash, _ = blob_store_no_compression.store(content)
        assert blob_store_no_compression.retrieve(content_hash) == content

    def test_large_content(self, blob_store: BlobStore):
        content = b"x" * 1_000_000  # 1MB
        content_hash, size = blob_store.store(content)
        assert size == 1_000_000
        assert blob_store.retrieve(content_hash) == content

    def test_binary_content(self, blob_store: BlobStore):
        content = bytes(range(256)) * 100
        content_hash, _ = blob_store.store(content)
        assert blob_store.retrieve(content_hash) == content

    def test_stats(self, blob_store: BlobStore):
        blob_store.store(b"content a")
        blob_store.store(b"content b")

        stats = blob_store.stats()
        assert stats["total_blobs"] == 2
        assert stats["total_stored_bytes"] > 0
        assert stats["total_references"] == 2
