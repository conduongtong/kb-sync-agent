# DigitalOcean Scheduled Job Setup

This guide describes how to set up a daily scheduled job on DigitalOcean to run the KB Sync Agent.

## Prerequisites

1. DigitalOcean account
2. Docker image pushed to a registry (Docker Hub, DigitalOcean Container Registry, etc.)
3. OpenAI API key

## Option 1: Using DigitalOcean App Platform Jobs

### Step 1: Create Container Registry (if using DO registry)

```bash
# Build and tag image
docker build -t registry.digitalocean.com/your-registry/kb-sync-agent:latest .

# Push to registry
doctl registry login
docker push registry.digitalocean.com/your-registry/kb-sync-agent:latest
```

### Step 2: Create App Platform Job

1. Go to DigitalOcean App Platform
2. Create new app → "Job" type
3. Configure:
   - **Source**: Container Registry
   - **Image**: `registry.digitalocean.com/your-registry/kb-sync-agent:latest`
   - **Run Command**: `python main.py`
   - **Schedule**: `0 2 * * *` (daily at 2 AM UTC)
4. Add environment variable:
   - `OPENAI_API_KEY`: Your OpenAI API key (mark as encrypted)
5. Deploy

### Step 3: Configure Log Storage

1. In App Platform job settings, enable "Log Draining"
2. Configure to send logs to:
   - DigitalOcean Spaces (S3-compatible)
   - Or external logging service (Datadog, Logtail, etc.)

### Step 4: Access Logs

- View in App Platform dashboard under "Runtime Logs"
- Or access from Spaces/logging service
- Artifacts saved to `artifacts/last_run.json` in container (consider mounting volume or uploading to Spaces)

## Option 2: Using DigitalOcean Droplets with Cron

### Step 1: Provision Droplet

```bash
# Create droplet (Ubuntu 22.04, 1GB RAM minimum)
doctl compute droplet create kb-sync-droplet \
  --size s-1vcpu-1gb \
  --image ubuntu-22-04-x64 \
  --region nyc1 \
  --ssh-keys your-ssh-key-id
```

### Step 2: Install Docker

```bash
ssh root@your-droplet-ip

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Add user to docker group (if not root)
usermod -aG docker $USER
```

### Step 3: Set Up Cron Job

```bash
# Create script
cat > /root/run-kb-sync.sh << 'EOF'
#!/bin/bash
export OPENAI_API_KEY="your_key_here"
docker run --rm \
  -e OPENAI_API_KEY \
  -v /root/kb-sync-data:/app/data \
  -v /root/kb-sync-artifacts:/app/artifacts \
  kb-sync-agent:latest
EOF

chmod +x /root/run-kb-sync.sh

# Add to crontab (daily at 2 AM)
(crontab -l 2>/dev/null; echo "0 2 * * * /root/run-kb-sync.sh >> /var/log/kb-sync.log 2>&1") | crontab -
```

### Step 4: Set Up Log Rotation

```bash
# Configure logrotate
cat > /etc/logrotate.d/kb-sync << 'EOF'
/var/log/kb-sync.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF
```

## Option 3: Using DigitalOcean Functions (Serverless)

Note: Functions have execution time limits, may not be suitable for large scrapes.

1. Package as serverless function
2. Deploy to DigitalOcean Functions
3. Schedule via Cloud Scheduler or external cron service

## Log Artifacts

The job generates `artifacts/last_run.json` with:
- Run timestamp
- Counts: scraped, added, updated, skipped, chunks_uploaded
- Errors (if any)
- Vector store ID

**Recommended**: Upload artifacts to DigitalOcean Spaces or S3 for persistence:

```python
# Add to main.py after artifact generation
import boto3
s3 = boto3.client('s3', endpoint_url='https://nyc3.digitaloceanspaces.com')
s3.upload_file('artifacts/last_run.json', 'your-space', 'kb-sync/last_run.json')
```

## Monitoring

- Set up alerts for job failures
- Monitor OpenAI API usage
- Track article count trends
- Alert if scraped count < 30

## Cost Estimation

- App Platform Job: ~$5-10/month (minimal resources, runs once daily)
- Droplet: ~$6/month (1GB RAM)
- Functions: Pay per execution

## Troubleshooting

- **Job fails**: Check logs in App Platform or `/var/log/kb-sync.log`
- **No articles scraped**: Verify network connectivity, check rate limiting
- **Vector store errors**: Verify OpenAI API key, check API quotas
- **Out of memory**: Increase droplet/app resources

