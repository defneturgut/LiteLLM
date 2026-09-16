# Personal Improvements (Defne Turgut)

This fork is `BerriAI/litellm` at tag `v1.97.0` (verified to be the exact commit backing the `ghcr.io/berriai/litellm:main-stable` image), with three additions to the Admin UI applied directly to `ui/litellm-dashboard`:

1. **Universal Request & Response logging** — the Logs page's "Request & Response" panel now renders real input/output for text-completion, image-generation, and embedding requests, not just chat.
2. **Metrics tab** — a new sidebar page with response-time charts (per-model, per-mode, combined), daily/hourly trend, and per-model stats. Backed by `../metrics/dashboard.py` at the repo root — a standalone script, not part of the LiteLLM package, that queries the proxy's Postgres directly.
3. **Playground support for non-chat models** — Playground now offers a `/v1/completions` endpoint option, so base/completion models (no chat template) can be tested there instead of always failing with a 400.

## Files in this folder

- `Kisisel_Gelistirmeleri_LiteLLMe_Entegre_Etme_Rehberi.pdf` — how these changes work and how to reapply them to a different LiteLLM version (Turkish).
- `Uzak_Sunucu_vLLM_LiteLLM_Rehberi.pdf` — companion guide on serving a model with vLLM on a remote server and connecting it here (Turkish).

The actual code changes are just a normal part of this repo's `ui/litellm-dashboard` — diff this fork against the upstream `v1.97.0` tag to see exactly what changed:

```bash
git diff v1.97.0 -- ui/litellm-dashboard/src
```

## Running It

The repo root's `docker-compose.yml` runs this fork (proxy + Postgres + Redis)
with all three customizations already wired in — see the top-level
`.env.example` and the comments in `docker-compose.yml`.

**Build the Admin UI first — this is a required step, not optional.**
`ui-build/out/` is *not* committed to the repo (avoiding a compiled build
artifact in git), so `docker-compose.yml`'s volume mount has nothing to mount
until you build it once. Skip this and run `docker compose up -d` first, and
Docker bind-mounts an empty host directory over the official image's Admin UI
path — the UI won't load at all.

```bash
# 1) Build the Admin UI from this fork's own ui/litellm-dashboard source.
#    Pure Node.js -- the `ui-builder` Dockerfile stage never touches
#    Python or Rust, so it's unaffected by the backend build issue below.
docker build --target ui-builder -t litellm-fork-ui-build .
docker create --name tmp-ui litellm-fork-ui-build
docker cp tmp-ui:/ui/out ./ui-build/out
docker rm tmp-ui

# 2) Ordinary setup
cp .env.example .env    # fill in the values
docker compose up -d
python3 metrics/dashboard.py   # powers the Metrics tab, localhost:8093
```

Re-run step 1 any time you change `ui/litellm-dashboard` source, then
`docker compose restart litellm` to pick it up.
