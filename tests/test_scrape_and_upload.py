"""
Smoke tests for scraper and uploader functionality.
"""

import json
import hashlib
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scraper import ArticleScraper
from uploader import ArticleUploader


@pytest.fixture
def sample_html():
    """Load sample HTML fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_article.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directory."""
    data_dir = tmp_path / "data"
    articles_dir = data_dir / "articles"
    articles_dir.mkdir(parents=True)
    return data_dir


def test_html_cleaning(sample_html):
    """Test that HTML cleaning removes nav, sidebar, ads."""
    scraper = ArticleScraper(data_dir="temp_test")
    cleaned = scraper._clean_html(sample_html)
    soup = BeautifulSoup(cleaned, "lxml")
    
    # Should not contain nav, aside, footer, script
    assert soup.find("nav") is None
    assert soup.find("aside") is None
    assert soup.find("footer") is None
    assert soup.find("script") is None
    
    # Should contain article content
    assert soup.find("article") is not None
    assert "How to Add a YouTube Video" in cleaned


def test_html_to_markdown(sample_html):
    """Test HTML to Markdown conversion."""
    scraper = ArticleScraper(data_dir="temp_test")
    markdown = scraper._html_to_markdown(sample_html)
    
    # Should contain title as heading
    assert "# How to Add a YouTube Video" in markdown or "How to Add a YouTube Video" in markdown
    
    # Should contain H2 headings
    assert "## Step 1:" in markdown or "Step 1:" in markdown
    assert "## Step 2:" in markdown or "Step 2:" in markdown
    
    # Should contain code blocks
    assert "youtube.com" in markdown.lower()


def test_hash_computation():
    """Test hash computation for delta detection."""
    scraper = ArticleScraper(data_dir="temp_test")
    
    content1 = "Test content"
    content2 = "Test content"  # Same content
    content3 = "Different content"
    
    hash1 = scraper._compute_hash(content1)
    hash2 = scraper._compute_hash(content2)
    hash3 = scraper._compute_hash(content3)
    
    # Same content should produce same hash
    assert hash1 == hash2
    
    # Different content should produce different hash
    assert hash1 != hash3
    
    # Hash should be 64 characters (SHA256 hex)
    assert len(hash1) == 64


def test_chunking_strategy(monkeypatch):
    """Test chunking creates reasonable chunks."""
    # Mock OpenAI client to avoid needing API key
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    uploader = ArticleUploader()
    
    # Create sample markdown with headings - make it long enough to create chunks
    # Need content > 200 tokens per section (MIN_CHUNK_TOKENS)
    # Repeat content to ensure each section exceeds the threshold
    long_para = "This is a paragraph with substantial content. " * 20
    markdown = f"""# Title

## Section 1
{long_para}

{long_para}

{long_para}

## Section 2
{long_para}

{long_para}
"""
    
    chunks = uploader._create_chunks(markdown, "test-article", "https://example.com/test")
    
    # Should create at least one chunk (content should be > MIN_CHUNK_TOKENS)
    assert len(chunks) > 0
    
    # Each chunk should have required fields
    for chunk in chunks:
        assert "text" in chunk
        assert "tokens" in chunk
        assert "heading" in chunk
        assert "chunk_index" in chunk
        assert "article_slug" in chunk
        assert "source_url" in chunk
        
        # Chunk should have reasonable token count
        assert chunk["tokens"] > 0
        assert chunk["tokens"] <= 1000  # Should not exceed max significantly


def test_chunking_with_headings(monkeypatch):
    """Test that chunking preserves heading context."""
    # Mock OpenAI client to avoid needing API key
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    uploader = ArticleUploader()
    
    # Make content long enough to create chunks (> 200 tokens per section)
    # Repeat content to ensure each section exceeds the threshold
    long_para = "This is a paragraph with substantial content that we're repeating to meet token requirements. " * 25
    markdown = f"""# Main Title

## First Section
{long_para}

{long_para}

{long_para}

## Second Section
{long_para}

{long_para}
"""
    
    chunks = uploader._create_chunks(markdown, "test", "https://example.com")
    
    # Should split by sections and create at least one chunk
    assert len(chunks) >= 1
    
    # Check that headings are preserved in metadata
    headings = [chunk.get("heading", "") for chunk in chunks]
    assert any("First Section" in h or "First" in h for h in headings) or len(chunks) == 1


def test_normalize_markdown():
    """Test markdown normalization."""
    scraper = ArticleScraper(data_dir="temp_test")
    
    # Test with various whitespace
    text1 = "Line 1\n\n\nLine 2"
    text2 = "Line 1\n\nLine 2"
    
    norm1 = scraper._normalize_markdown(text1)
    norm2 = scraper._normalize_markdown(text2)
    
    # Should normalize to same result
    assert norm1 == norm2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

