#!/bin/sh
set -e
# Keys live in the data volume so encrypted files and sessions survive container rebuilds.
KEYS=/data/keys.env
if [ ! -f "$KEYS" ]; then
  python -c "from cryptography.fernet import Fernet; import secrets; print('FINSONA_STORAGE_KEY=' + Fernet.generate_key().decode()); print('FINSONA_SECRET_KEY=' + secrets.token_urlsafe(48))" > "$KEYS"
  chmod 600 "$KEYS"
fi
# Explicit env vars win over the generated ones.
: "${FINSONA_STORAGE_KEY:=$(sed -n 's/^FINSONA_STORAGE_KEY=//p' "$KEYS")}"
: "${FINSONA_SECRET_KEY:=$(sed -n 's/^FINSONA_SECRET_KEY=//p' "$KEYS")}"
export FINSONA_STORAGE_KEY FINSONA_SECRET_KEY
# Seed the demo case on first start (also seeds the LLM cache shipped in data/llm_cache.json).
if [ ! -f /data/finsona.db ]; then
  [ -f /app/data/llm_cache.json ] && [ ! -f "$FINSONA_LLM_CACHE_FILE" ] && cp /app/data/llm_cache.json "$FINSONA_LLM_CACHE_FILE"
  python -m app.seed
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
