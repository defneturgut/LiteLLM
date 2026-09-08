# Personal Improvements (Defne Turgut)

This fork is `BerriAI/litellm` at tag `v1.97.0` (verified to be the exact commit backing the `ghcr.io/berriai/litellm:main-stable` image), with three additions to the Admin UI applied directly to `ui/litellm-dashboard`:

1. **Universal Request & Response logging** — the Logs page's "Request & Response" panel now renders real input/output for text-completion, image-generation, and embedding requests, not just chat.
2. **Metrics tab** — a new sidebar page with response-time charts (per-model, per-mode, combined), daily/hourly trend, and per-model stats. Backed by `dashboard.py` in this folder — a standalone script, not part of the LiteLLM package, that queries the proxy's Postgres directly.
3. **Playground support for non-chat models** — Playground now offers a `/v1/completions` endpoint option, so base/completion models (no chat template) can be tested there instead of always failing with a 400.

## Files in this folder

- `dashboard.py` — run this alongside your LiteLLM proxy (`python3 dashboard.py`) to power the Metrics tab (serves on `localhost:8093`).
- `Kisisel_Gelistirmeleri_LiteLLMe_Entegre_Etme_Rehberi.pdf` — how these changes work and how to reapply them to a different LiteLLM version (Turkish).
- `Uzak_Sunucu_vLLM_LiteLLM_Rehberi.pdf` — companion guide on serving a model with vLLM on a remote server and connecting it here (Turkish).

The actual code changes are just a normal part of this repo's `ui/litellm-dashboard` — diff this fork against the upstream `v1.97.0` tag to see exactly what changed:

```bash
git diff v1.97.0 -- ui/litellm-dashboard/src
```

## Running it

Same as upstream LiteLLM — see the main repo `README.md` and `docker-compose.yml` you're already using. The UI changes take effect once you rebuild the Admin UI's static export from this source (see the PDF for the exact Docker-based build command) and mount it over the proxy's baked-in UI path.
