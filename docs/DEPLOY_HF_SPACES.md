# 🐳 Deploying `hermify-mcp` to Hugging Face Spaces

While `hermify-mcp` is designed to run locally via `uvx` for private agent memory, you can deploy it to Hugging Face Spaces to create a **Shared Team Brain** or a **Public Demo**. 

By hosting it on HF Spaces, multiple agents (or multiple users) can connect to the same centralized, dataset-backed memory and skill library via HTTP.

## Why Docker?
Hugging Face Spaces natively supports Docker. Using a Dockerfile gives you 100% control over the CLI environment, ensures your `hermify serve` command runs exactly as it does locally, and allows you to mount persistent storage for your local DuckDB buffer.

---

## Step 1: Create the Hugging Face Space

1. Go to [Hugging Face Spaces](https://huggingface.co/new-space) and log in.
2. **Space name:** Choose a name (e.g., `hermify-team-brain`).
3. **SDK:** Select **Docker** (Crucial: do not select Gradio or Streamlit).
4. **Docker template:** Select **Blank**.
5. **Hardware:** Choose the free **CPU Basic** tier (MCP servers are lightweight).
6. **Visibility:** Public or Private.
7. Click **Create Space**.

---

## Step 2: Add the Dockerfile

In the root of your `hermify-mcp` repository, ensure you have a `Dockerfile`. Here is the optimized, production-ready Dockerfile using `uv` for lightning-fast builds:

```dockerfile
FROM python:3.11-slim

# Install uv for lightning-fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    HERMIFY_HOME=/data/.hermify

WORKDIR /app
COPY . .

# Install dependencies
RUN uv sync --frozen

EXPOSE 7860

# Run the CLI directly in HTTP mode
CMD ["uv", "run", "hermify", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "7860"]
```

---

## Step 3: Configure Secrets (Crucial for HF Sync)

Your server needs an `HF_TOKEN` to push/pull datasets from the Hugging Face Hub. **Never hardcode this in your Dockerfile.**

1. In your newly created HF Space, go to the **Settings** tab.
2. Scroll down to **Variables and secrets**.
3. Click **New secret**.
4. **Name:** `HF_TOKEN`
5. **Value:** Paste your Hugging Face Access Token (requires "Write" access to Datasets).
6. Click **Save**.

---

## Step 4: Push the Code to the Space

Deploy your code to the Space using Git.

```bash
# 1. Clone your newly created Space repository
git clone https://huggingface.co/spaces/YOUR_USERNAME/hermify-team-brain
cd hermify-team-brain

# 2. Copy your hermify-mcp source code into this directory
cp -r ~/path/to/your/hermify-mcp/* .
cp -r ~/path/to/your/hermify-mcp/.* . 2>/dev/null 

# 3. Clean up local caches
rm -rf .venv .pytest_cache .mypy_cache .ruff_cache

# 4. Commit and push
git add .
git commit -m "feat: initial docker deployment for hermify-mcp"
git push
```

HF will detect the `Dockerfile`, build the image, and deploy it. Watch the **Logs** tab to see it boot up.

---

## Step 5: Enable Persistent Storage (Optional but Recommended)

By default, HF Spaces containers are ephemeral. If the Space restarts, the local `hermify.db` (DuckDB) file will be wiped. 

Because of our architecture, **this is mostly fine**: the source of truth is the Hugging Face Dataset. On startup, an agent can simply call `sync_pull` to download the latest Parquet shards back into the local DuckDB buffer.

However, if you want the Space to retain the DuckDB buffer across restarts without needing to pull:
1. Go to your Space **Settings**.
2. Scroll to **Persistent Storage** (Note: This is a paid feature on HF, usually ~$5/month).
3. Enable it and mount it to `/data`.
4. Because we set `ENV HERMIFY_HOME=/data/.hermify` in the Dockerfile, your DuckDB file will automatically be saved to the persistent volume!

---

## Next Steps: Connect Your Agents

Once your Space status turns **Running** (green), your centralized brain is live! 

Refer to the [README](../README.md#option-b-shared-team-brain-hugging-face-spaces--remote-http) to see how to configure your local agents (Claude Desktop, Cursor, etc.) to connect to this URL.