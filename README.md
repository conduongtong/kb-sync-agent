# KB Sync Agent

A knowledge base synchronization agent that scrapes OptiSigns support articles, converts them to Markdown, detects changes, and uploads to OpenAI Vector Store for use with Assistants.

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.sample` to `.env` and set `OPENAI_API_KEY`
4. (Optional) Set `ZENDESK_API_KEY` and `ZENDESK_EMAIL` for authenticated Zendesk API access
   - If provided, uses authenticated Zendesk API (better rate limits, access to private articles)
   - If not provided, uses public Zendesk Help Center API (no authentication needed)
5. (Optional) Set `ARTICLE_LIMIT` to limit number of articles scraped (useful for testing)

## Running Locally

```bash
python main.py
```

The script will:
- Scrape articles from support.optisigns.com (≥30 articles)
- Convert to clean Markdown files in `data/articles/`
- Detect new/updated articles using SHA256 hash comparison
- Upload only changed articles to OpenAI Vector Store
- Generate `artifacts/last_run.json` with run statistics

## Running with Docker

```bash
docker build -t kb-sync-agent:latest .
docker run --rm -e OPENAI_API_KEY=your_key_here kb-sync-agent:latest
```

To limit articles (e.g., for testing):
```bash
docker run --rm -e OPENAI_API_KEY=your_key_here -e ARTICLE_LIMIT=10 kb-sync-agent:latest
```

Or use Makefile:
```bash
make docker-build
make docker-run
```

## Chunking Strategy

Articles are chunked using the following strategy:
- Split by H2/H3 heading boundaries to preserve semantic structure
- For each section, combine paragraphs to target 400-700 tokens per chunk
- Add 100 token overlap between chunks to maintain context
- Preserve heading context in chunk metadata for better retrieval

This approach ensures:
- Chunks are semantically coherent (respect heading boundaries)
- Appropriate size for embedding models (400-700 tokens)
- Context preservation via overlap
- Better retrieval accuracy with heading metadata

## Playground Setup

1. Run `main.py` to create/update the vector store
2. Check `artifacts/last_run.json` for `vector_store_id`
3. Run `python playground_check.py` to create an assistant and test
4. Or manually:
   - Go to [OpenAI Playground](https://platform.openai.com/playground)
   - Create Assistant with system prompt from `optibot_system_prompt.txt`
   - Attach the vector store from step 2
   - Ask: "How do I add a YouTube video?"
   - Verify response includes "Article URL:" citations (max 3)

See `docs/playground_screenshot.png` for example.

## Job Logs

Last run artifact: `artifacts/last_run.json`

For scheduled jobs, see `digitalocean_job_setup.md` for deployment instructions.

## Testing

```bash
python3 -m pytest tests/test_scrape_and_upload.py -v
```

Runs smoke tests for scraping, markdown conversion, chunking, and hash computation.

