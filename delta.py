"""
Delta detection for articles - identifies new, updated, and unchanged articles.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple


class DeltaDetector:
    def __init__(self, index_file: str = "data/index.json"):
        self.index_file = Path(index_file)
        self.index = self._load_index()
    
    def _load_index(self) -> Dict:
        """Load article index."""
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def detect_changes(self, scraped_articles: Dict[str, Dict]) -> Tuple[List[str], List[str], List[str]]:
        """
        Detect new, updated, and unchanged articles.
        
        Returns:
            (new_slugs, updated_slugs, unchanged_slugs)
        """
        new_slugs = []
        updated_slugs = []
        unchanged_slugs = []
        
        for slug, metadata in scraped_articles.items():
            old_metadata = self.index.get(slug)
            
            if not old_metadata:
                # New article
                new_slugs.append(slug)
            else:
                # Check if hash changed
                old_hash = old_metadata.get("hash", "")
                new_hash = metadata.get("hash", "")
                
                if old_hash != new_hash:
                    # Updated article
                    updated_slugs.append(slug)
                else:
                    # Unchanged
                    unchanged_slugs.append(slug)
        
        return new_slugs, updated_slugs, unchanged_slugs
    
    def get_articles_to_upload(self, scraped_articles: Dict[str, Dict]) -> Dict[str, Dict]:
        """Get articles that need to be uploaded (new or updated)."""
        new_slugs, updated_slugs, _ = self.detect_changes(scraped_articles)
        
        to_upload = {}
        for slug in new_slugs + updated_slugs:
            to_upload[slug] = scraped_articles[slug]
        
        return to_upload

