import pytest

from app.rag.ingest import chunk_text


def test_chunk_text_rejects_bad_params():
    with pytest.raises(ValueError):
        chunk_text("some text", size=100, overlap=100)  # overlap == size → would hang
    with pytest.raises(ValueError):
        chunk_text("some text", size=0)
    with pytest.raises(ValueError):
        chunk_text("some text", size=100, overlap=-1)


def test_chunk_text_basic():
    assert chunk_text("") == []
    assert chunk_text("short") == ["short"]
    pieces = chunk_text("x" * 2000, size=800, overlap=100)
    assert pieces and all(len(p) <= 800 for p in pieces)
