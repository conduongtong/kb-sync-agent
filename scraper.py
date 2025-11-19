"""
Scraper for OptiSigns support articles.
Attempts Zendesk Help Center API first, falls back to web scraping.
"""

import json
import os
import re
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

# Rate limiting: 1 request per second
RATE_LIMIT_DELAY = 1.0
BASE_URL = "https://support.optisigns.com"
API_BASE = f"{BASE_URL}/api/v2/help_center"


class ArticleScraper:
    def __init__(self, data_dir: str = "data", article_limit: Optional[int] = None):
        self.data_dir = Path(data_dir)
        self.articles_dir = self.data_dir / "articles"
        self.index_file = self.data_dir / "index.json"
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        
        # Article limit (from env var or parameter, default None = no limit)
        if article_limit is None:
            article_limit = os.getenv("ARTICLE_LIMIT")
            if article_limit:
                try:
                    article_limit = int(article_limit)
                except ValueError:
                    article_limit = None
        self.article_limit = article_limit
        
        # Load existing index
        self.index = self._load_index()
        
        # Session for requests
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        # Set up Zendesk authentication if credentials are provided
        zendesk_email = os.getenv("ZENDESK_EMAIL")
        zendesk_api_key = os.getenv("ZENDESK_API_KEY")
        
        if zendesk_email and zendesk_api_key:
            # Zendesk API uses email/token authentication
            self.session.auth = (f"{zendesk_email}/token", zendesk_api_key)
            print("Using Zendesk API authentication")
        else:
            print("No Zendesk credentials provided, using public API")
        
        self.last_request_time = 0
        
    def _load_index(self) -> Dict:
        """Load article index from JSON file."""
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def _save_index(self):
        """Save article index to JSON file."""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2, ensure_ascii=False)
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = time.time()
    
    def _normalize_markdown(self, text: str) -> str:
        """Normalize markdown for consistent hashing."""
        # Remove extra whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # Strip leading/trailing whitespace
        return text.strip()
    
    def _compute_hash(self, content: str) -> str:
        """Compute SHA256 hash of normalized content."""
        normalized = self._normalize_markdown(content)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    
    def _clean_html(self, html: str) -> str:
        """Clean HTML by removing navigation, sidebars, ads."""
        soup = BeautifulSoup(html, "lxml")
        
        # Remove common navigation/sidebar elements
        for selector in [
            "nav", "header", "footer", "aside",
            ".nav", ".navbar", ".sidebar", ".menu",
            ".ad", ".advertisement", ".ads",
            "script", "style"
        ]:
            for elem in soup.select(selector):
                elem.decompose()
        
        # Remove elements with common ad/nav classes
        for elem in soup.find_all(class_=re.compile(r"(nav|menu|sidebar|ad|cookie)", re.I)):
            elem.decompose()
        
        return str(soup)
    
    def _html_to_markdown(self, html: str, base_url: str = BASE_URL) -> str:
        """Convert HTML to clean Markdown."""
        cleaned = self._clean_html(html)
        soup = BeautifulSoup(cleaned, "lxml")
        
        # Convert relative links to absolute
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.startswith("/"):
                link["href"] = urljoin(base_url, href)
        
        # Convert images
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if src.startswith("/"):
                img["src"] = urljoin(base_url, src)
        
        # Convert to markdown
        md_text = md(str(soup), heading_style="ATX", bullets="-")
        
        return self._normalize_markdown(md_text)
    
    def _fetch_article_api(self, article_id: int) -> Optional[Dict]:
        """Fetch article from Zendesk API."""
        url = f"{API_BASE}/articles/{article_id}.json"
        self._rate_limit()
        
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get("article")
        except Exception as e:
            print(f"API fetch failed for article {article_id}: {e}")
        
        return None
    
    def _fetch_article_web(self, article_url: str) -> Optional[Dict]:
        """Scrape article from web page."""
        self._rate_limit()
        
        try:
            response = self.session.get(article_url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "lxml")
                
                # Try to find article content
                article_body = soup.find("article") or soup.find(class_=re.compile(r"article|content|body", re.I))
                if not article_body:
                    article_body = soup.find("main") or soup.find("body")
                
                if article_body:
                    html_content = str(article_body)
                    title = soup.find("h1") or soup.find("title")
                    title_text = title.get_text().strip() if title else "Untitled"
                    
                    # Try to find slug from URL
                    slug = urlparse(article_url).path.strip("/").split("/")[-1] or "unknown"
                    
                    return {
                        "title": title_text,
                        "body": html_content,
                        "html_url": article_url,
                        "slug": slug
                    }
        except Exception as e:
            print(f"Web scrape failed for {article_url}: {e}")
        
        return None
    
    def _get_article_list_api(self) -> List[Dict]:
        """Get article list from Zendesk API."""
        articles = []
        page = 1
        per_page = 100
        
        while True:
            url = f"{API_BASE}/articles.json?per_page={per_page}&page={page}"
            self._rate_limit()
            
            try:
                response = self.session.get(url, timeout=10)
                if response.status_code != 200:
                    break
                
                data = response.json()
                page_articles = data.get("articles", [])
                if not page_articles:
                    break
                
                articles.extend(page_articles)
                
                # Check if there are more pages
                if len(page_articles) < per_page:
                    break
                
                page += 1
            except Exception as e:
                print(f"API list fetch failed at page {page}: {e}")
                break
        
        return articles
    
    def _get_article_list_web(self) -> List[str]:
        """Get article URLs by scraping sitemap or category pages."""
        article_urls = []
        
        # Try to find sitemap
        sitemap_urls = [
            f"{BASE_URL}/sitemap.xml",
            f"{BASE_URL}/sitemap",
        ]
        
        for sitemap_url in sitemap_urls:
            self._rate_limit()
            try:
                response = self.session.get(sitemap_url, timeout=10)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "xml")
                    for loc in soup.find_all("loc"):
                        url = loc.get_text()
                        if "/articles/" in url or "/hc/" in url:
                            article_urls.append(url)
                    if article_urls:
                        break
            except Exception:
                continue
        
        # If no sitemap, try category pages
        if not article_urls:
            category_urls = [
                f"{BASE_URL}/en-us",
                f"{BASE_URL}/categories",
            ]
            
            for cat_url in category_urls:
                self._rate_limit()
                try:
                    response = self.session.get(cat_url, timeout=10)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "lxml")
                        for link in soup.find_all("a", href=True):
                            href = link["href"]
                            if "/articles/" in href or "/hc/" in href:
                                full_url = urljoin(BASE_URL, href)
                                if full_url not in article_urls:
                                    article_urls.append(full_url)
                except Exception:
                    continue
        
        return article_urls[:50]  # Limit to 50 for initial scrape
    
    def scrape_articles(self) -> Dict[str, Dict]:
        """Scrape all articles and return metadata."""
        print("Fetching article list...")
        
        # Try API first
        api_articles = self._get_article_list_api()
        
        if api_articles and len(api_articles) >= 30:
            print(f"Found {len(api_articles)} articles via API")
            articles_to_process = api_articles
            use_api = True
        else:
            print("API not available or insufficient articles, falling back to web scraping")
            article_urls = self._get_article_list_web()
            print(f"Found {len(article_urls)} article URLs via web scraping")
            articles_to_process = article_urls
            use_api = False
        
        # Apply article limit if set
        if self.article_limit and len(articles_to_process) > self.article_limit:
            print(f"Limiting to {self.article_limit} articles (found {len(articles_to_process)})")
            articles_to_process = articles_to_process[:self.article_limit]
        
        scraped = {}
        
        for i, item in enumerate(articles_to_process, 1):
            if use_api:
                article_id = item.get("id")
                article_data = self._fetch_article_api(article_id)
                if not article_data:
                    continue
                
                title = article_data.get("title", "Untitled")
                body_html = article_data.get("body", "")
                slug = article_data.get("slug", f"article-{article_id}")
                source_url = article_data.get("html_url", f"{BASE_URL}/articles/{article_id}")
                last_modified = article_data.get("updated_at")
            else:
                article_url = item if isinstance(item, str) else item.get("url", "")
                article_data = self._fetch_article_web(article_url)
                if not article_data:
                    continue
                
                title = article_data.get("title", "Untitled")
                body_html = article_data.get("body", "")
                slug = article_data.get("slug", "unknown")
                source_url = article_data.get("html_url", article_url)
                last_modified = None
            
            # Convert to markdown
            markdown_content = self._html_to_markdown(body_html, BASE_URL)
            
            # Add title as H1 if not present
            if not markdown_content.startswith("#"):
                markdown_content = f"# {title}\n\n{markdown_content}"
            
            # Compute hash
            content_hash = self._compute_hash(markdown_content)
            
            # Save markdown file
            md_file = self.articles_dir / f"{slug}.md"
            with open(md_file, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            
            # Store metadata
            scraped[slug] = {
                "source_url": source_url,
                "last_modified": last_modified,
                "hash": content_hash,
                "scrape_time": datetime.utcnow().isoformat() + "Z",
                "title": title
            }
            
            print(f"[{i}/{len(articles_to_process)}] Scraped: {slug} - {title[:50]}")
        
        # Note: Index is NOT updated here - it's updated in main.py after delta detection
        # This allows delta detection to compare against the old index
        
        return scraped


if __name__ == "__main__":
    scraper = ArticleScraper()
    articles = scraper.scrape_articles()
    print(f"\nScraped {len(articles)} articles")

