"""
Chunking and vector store upload for articles.
"""

import io
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import tiktoken
from openai import OpenAI
import requests

# Chunking parameters
TARGET_TOKENS = 600  # Target tokens per chunk (400-700 range)
OVERLAP_TOKENS = 100  # Overlap between chunks
MIN_CHUNK_TOKENS = 200  # Minimum chunk size
MAX_CHUNK_TOKENS = 800  # Maximum chunk size

# Embedding model
EMBEDDING_MODEL = "text-embedding-3-small"


class ArticleUploader:
    def __init__(self, api_key: Optional[str] = None, vector_store_id: Optional[str] = None):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.vector_store_id = vector_store_id
        self.encoding = tiktoken.encoding_for_model("gpt-4")
        
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))
    
    def _split_by_heading(self, markdown: str) -> List[Dict[str, str]]:
        """Split markdown into sections by H2/H3 headings."""
        sections = []
        current_section = {"heading": "", "content": ""}
        
        lines = markdown.split("\n")
        
        for line in lines:
            # Check if line is a heading (H2 or H3)
            heading_match = re.match(r"^(##|###)\s+(.+)$", line)
            
            if heading_match:
                # Save previous section if it has content
                if current_section["content"].strip():
                    sections.append(current_section)
                
                # Start new section
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                current_section = {
                    "heading": heading_text,
                    "heading_level": level,
                    "content": line + "\n"
                }
            else:
                current_section["content"] += line + "\n"
        
        # Add last section
        if current_section["content"].strip():
            sections.append(current_section)
        
        return sections
    
    def _split_into_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs."""
        # Split by double newlines
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]
    
    def _create_chunks(self, markdown: str, article_slug: str, source_url: str) -> List[Dict]:
        """
        Chunk markdown content into ~400-700 token chunks with 100 token overlap.
        
        Strategy:
        1. Split by H2/H3 boundaries
        2. For each section, split into paragraphs
        3. Combine paragraphs to target token size
        4. Add overlap between chunks
        """
        chunks = []
        
        # Split by headings first
        sections = self._split_by_heading(markdown)
        
        # If no headings, treat entire content as one section
        if not sections:
            sections = [{"heading": "", "content": markdown}]
        
        for section_idx, section in enumerate(sections):
            heading = section.get("heading", "")
            content = section["content"]
            
            # Split section into paragraphs
            paragraphs = self._split_into_paragraphs(content)
            
            current_chunk = []
            current_tokens = 0
            chunk_index = 0
            
            for para in paragraphs:
                para_tokens = self._count_tokens(para)
                
                # If paragraph itself is too large, split it
                if para_tokens > MAX_CHUNK_TOKENS:
                    # Save current chunk if exists
                    if current_chunk:
                        chunk_text = "\n\n".join(current_chunk)
                        chunks.append({
                            "text": chunk_text,
                            "tokens": current_tokens,
                            "heading": heading,
                            "chunk_index": chunk_index,
                            "article_slug": article_slug,
                            "source_url": source_url
                        })
                        chunk_index += 1
                        current_chunk = []
                        current_tokens = 0
                    
                    # Split large paragraph into sentences
                    sentences = re.split(r'[.!?]+\s+', para)
                    for sent in sentences:
                        sent_tokens = self._count_tokens(sent)
                        if current_tokens + sent_tokens > TARGET_TOKENS and current_chunk:
                            chunk_text = "\n\n".join(current_chunk)
                            chunks.append({
                                "text": chunk_text,
                                "tokens": current_tokens,
                                "heading": heading,
                                "chunk_index": chunk_index,
                                "article_slug": article_slug,
                                "source_url": source_url
                            })
                            chunk_index += 1
                            
                            # Start new chunk with overlap
                            overlap_text = "\n\n".join(current_chunk[-2:]) if len(current_chunk) >= 2 else current_chunk[-1] if current_chunk else ""
                            overlap_tokens = self._count_tokens(overlap_text)
                            if overlap_tokens > OVERLAP_TOKENS:
                                # Trim overlap to target size
                                overlap_words = overlap_text.split()
                                target_words = int(OVERLAP_TOKENS * len(overlap_words) / overlap_tokens)
                                overlap_text = " ".join(overlap_words[-target_words:])
                            
                            current_chunk = [overlap_text, sent] if overlap_text else [sent]
                            current_tokens = self._count_tokens("\n\n".join(current_chunk))
                        else:
                            current_chunk.append(sent)
                            current_tokens += sent_tokens
                
                # Check if adding this paragraph would exceed target
                elif current_tokens + para_tokens > TARGET_TOKENS and current_chunk:
                    # Save current chunk
                    chunk_text = "\n\n".join(current_chunk)
                    if current_tokens >= MIN_CHUNK_TOKENS:
                        chunks.append({
                            "text": chunk_text,
                            "tokens": current_tokens,
                            "heading": heading,
                            "chunk_index": chunk_index,
                            "article_slug": article_slug,
                            "source_url": source_url
                        })
                        chunk_index += 1
                    
                    # Start new chunk with overlap
                    overlap_text = "\n\n".join(current_chunk[-1:]) if current_chunk else ""
                    overlap_tokens = self._count_tokens(overlap_text)
                    if overlap_tokens > OVERLAP_TOKENS:
                        overlap_words = overlap_text.split()
                        target_words = int(OVERLAP_TOKENS * len(overlap_words) / overlap_tokens)
                        overlap_text = " ".join(overlap_words[-target_words:])
                    
                    current_chunk = [overlap_text, para] if overlap_text else [para]
                    current_tokens = self._count_tokens("\n\n".join(current_chunk))
                else:
                    # Add to current chunk
                    current_chunk.append(para)
                    current_tokens += para_tokens
            
            # Save remaining chunk
            if current_chunk and current_tokens >= MIN_CHUNK_TOKENS:
                chunk_text = "\n\n".join(current_chunk)
                chunks.append({
                    "text": chunk_text,
                    "tokens": current_tokens,
                    "heading": heading,
                    "chunk_index": chunk_index,
                    "article_slug": article_slug,
                    "source_url": source_url
                })
        
        return chunks
    
    def _get_or_create_vector_store(self) -> str:
        """Get existing vector store ID or create a new one."""
        api_key = self.client.api_key or os.getenv("OPENAI_API_KEY")
        base_url = self.client.base_url or "https://api.openai.com/v1"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2"
        }
        
        if self.vector_store_id:
            # Verify it exists
            try:
                response = requests.get(
                    f"{base_url}/vector_stores/{self.vector_store_id}",
                    headers=headers,
                    timeout=10
                )
                if response.status_code == 200:
                    return self.vector_store_id
            except Exception:
                pass
        
        # Create new vector store using REST API
        response = requests.post(
            f"{base_url}/vector_stores",
            headers=headers,
            json={"name": "OptiSigns Knowledge Base"},
            timeout=10
        )
        
        if response.status_code not in [200, 201]:
            raise Exception(
                f"Failed to create vector store: {response.status_code} - {response.text}"
            )
        
        vector_store = response.json()
        return vector_store["id"]
    
    def upload_article(self, article_slug: str, markdown_path: Path, metadata: Dict) -> int:
        """
        Upload a single article to vector store.
        
        Returns:
            Number of chunks uploaded
        """
        # Read markdown file
        with open(markdown_path, "r", encoding="utf-8") as f:
            markdown_content = f.read()
        
        # Create chunks
        chunks = self._create_chunks(
            markdown_content,
            article_slug,
            metadata.get("source_url", "")
        )
        
        if not chunks:
            return 0
        
        # Get or create vector store
        vector_store_id = self._get_or_create_vector_store()
        self.vector_store_id = vector_store_id
        
        # Upload chunks as files
        uploaded_count = 0
        
        for chunk in chunks:
            try:
                # Create a file-like object from chunk text
                chunk_text = chunk["text"]
                chunk_bytes = chunk_text.encode("utf-8")
                chunk_file = io.BytesIO(chunk_bytes)
                chunk_file.name = f"{article_slug}_chunk_{chunk['chunk_index']}.md"
                
                # Create file
                file_response = self.client.files.create(
                    file=chunk_file,
                    purpose="assistants"
                )
                
                # Add file to vector store using REST API
                api_key = self.client.api_key or os.getenv("OPENAI_API_KEY")
                base_url = self.client.base_url or "https://api.openai.com/v1"
                
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "OpenAI-Beta": "assistants=v2"
                }
                
                response = requests.post(
                    f"{base_url}/vector_stores/{vector_store_id}/files",
                    headers=headers,
                    json={"file_id": file_response.id},
                    timeout=10
                )
                
                if response.status_code not in [200, 201]:
                    raise Exception(
                        f"Failed to add file to vector store: {response.status_code} - {response.text}"
                    )
                
                uploaded_count += 1
            except Exception as e:
                print(f"Error uploading chunk {chunk['chunk_index']} of {article_slug}: {e}")
        
        return uploaded_count
    
    def upload_articles(self, articles_to_upload: Dict[str, Dict], articles_dir: Path) -> Dict[str, int]:
        """
        Upload multiple articles to vector store.
        
        Returns:
            Dict mapping article_slug to number of chunks uploaded
        """
        chunk_counts = {}
        
        for slug, metadata in articles_to_upload.items():
            md_file = articles_dir / f"{slug}.md"
            
            if not md_file.exists():
                print(f"Warning: Markdown file not found for {slug}")
                continue
            
            print(f"Uploading {slug}...")
            chunk_count = self.upload_article(slug, md_file, metadata)
            chunk_counts[slug] = chunk_count
            print(f"  Uploaded {chunk_count} chunks")
        
        return chunk_counts

