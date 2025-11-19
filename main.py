"""
Main entrypoint for KB sync agent.
Orchestrates: scrape → detect delta → upload only new/updated articles.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from delta import DeltaDetector
from scraper import ArticleScraper
from uploader import ArticleUploader

# Load environment variables
load_dotenv()


def main():
    """Main orchestration function."""
    errors = []
    counts = {
        "scraped": 0,
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "chunks_uploaded": 0
    }
    
    try:
        # Check for required API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("ERROR: OPENAI_API_KEY not set in environment")
            sys.exit(1)
        
        print("=" * 60)
        print("OptiSigns KB Sync Agent")
        print("=" * 60)
        
        # Step 1: Scrape articles
        print("\n[1/3] Scraping articles...")
        scraper = ArticleScraper()
        scraped_articles = scraper.scrape_articles()
        counts["scraped"] = len(scraped_articles)
        
        if counts["scraped"] < 30:
            print(f"WARNING: Only {counts['scraped']} articles scraped (target: ≥30)")
        
        # Step 2: Detect changes
        print("\n[2/3] Detecting changes...")
        detector = DeltaDetector()
        new_slugs, updated_slugs, unchanged_slugs = detector.detect_changes(scraped_articles)
        counts["added"] = len(new_slugs)
        counts["updated"] = len(updated_slugs)
        counts["skipped"] = len(unchanged_slugs)
        
        print(f"  New: {counts['added']}")
        print(f"  Updated: {counts['updated']}")
        print(f"  Unchanged: {counts['skipped']}")
        
        # Step 3: Upload new/updated articles
        articles_to_upload = detector.get_articles_to_upload(scraped_articles)
        uploader = None
        
        if articles_to_upload:
            print(f"\n[3/3] Uploading {len(articles_to_upload)} articles to vector store...")
            uploader = ArticleUploader(api_key=api_key)
            articles_dir = Path("data/articles")
            
            chunk_counts = uploader.upload_articles(articles_to_upload, articles_dir)
            counts["chunks_uploaded"] = sum(chunk_counts.values())
            
            print(f"\nUpload summary:")
            for slug, chunk_count in chunk_counts.items():
                print(f"  {slug}: {chunk_count} chunks")
        else:
            print("\n[3/3] No articles to upload (all up to date)")
        
        # Update index with all scraped articles (after delta detection and upload)
        # This ensures next run can properly detect changes
        index_file = Path("data/index.json")
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                index = json.load(f)
        else:
            index = {}
        
        # Update index with all scraped articles
        index.update(scraped_articles)
        
        # Save updated index
        index_file.parent.mkdir(parents=True, exist_ok=True)
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        
        # Generate artifacts
        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(exist_ok=True)
        
        run_artifact = {
            "run_time": datetime.utcnow().isoformat() + "Z",
            "counts": {
                "scraped": counts["scraped"],
                "added": counts["added"],
                "updated": counts["updated"],
                "skipped": counts["skipped"],
                "chunks_uploaded": counts["chunks_uploaded"]
            },
            "errors": errors,
            "vector_store_id": uploader.vector_store_id if uploader else None
        }
        
        artifact_file = artifacts_dir / "last_run.json"
        with open(artifact_file, "w", encoding="utf-8") as f:
            json.dump(run_artifact, f, indent=2)
        
        print("\n" + "=" * 60)
        print("Summary:")
        print(f"  Articles scraped: {counts['scraped']}")
        print(f"  Articles added: {counts['added']}")
        print(f"  Articles updated: {counts['updated']}")
        print(f"  Articles skipped: {counts['skipped']}")
        print(f"  Chunks uploaded: {counts['chunks_uploaded']}")
        print(f"  Artifact saved: {artifact_file}")
        if uploader and uploader.vector_store_id:
            print(f"  Vector Store ID: {uploader.vector_store_id}")
        print("=" * 60)
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 1
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        errors.append(str(e))
        
        # Save artifact even on error
        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(exist_ok=True)
        run_artifact = {
            "run_time": datetime.utcnow().isoformat() + "Z",
            "counts": counts,
            "errors": errors
        }
        artifact_file = artifacts_dir / "last_run.json"
        with open(artifact_file, "w", encoding="utf-8") as f:
            json.dump(run_artifact, f, indent=2)
        
        return 1


if __name__ == "__main__":
    sys.exit(main())
