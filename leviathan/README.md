# leviathan

> **Work in progress.** Deployed, but both of its model endpoints have been
> down since a GPU-server rebuild (late September 2026), so every cluster is
> currently dropped.

A news-intelligence dashboard: a 3D globe and sidebar fed by a small
multi-model pipeline that reads RSS feeds by region, merges stories about
the same event, and rates supply-chain risk.

## The pipeline (`engine/leviathan_core.py`)

1. **Collect.** Pull the latest items from each configured feed, tagged by
   region.
2. **Cluster.** A small "edge" model answers YES/NO for whether two
   headlines report the exact same event.
3. **Summarize and rate.** For each cluster, the edge model writes a short
   neutral summary; a larger "brain" model analyzes supply-chain exposure
   and must end with a risk tag (`CRITICAL` / `MODERATE` / `LOW`).
4. **Synthesize.** Two prompted roles — a geopolitical analyst (edge model)
   and a supply-chain architect (brain model) — write a joint assessment
   with an overall risk tag.

The Next.js app (`app/`) renders the globe, the feed and the assessment; a
trigger route kicks off a new run, and supervisord runs the engine next to
the web server in one container.

## Known gaps

- **Model endpoints down.** Set `EDGE_URL` and `BRAIN_URL` to live
  OpenAI-compatible endpoints.
- **Silent defaults.** If the brain model omits the risk tag, a cluster
  defaults to no risk and the global assessment to `LOW`; errors are
  swallowed and logged, not surfaced.
- **Free text everywhere.** Clustering, tags and roles are all parsed from
  prose; it is closer to an LLM pipeline than an agent (no tools, no
  actions), and typed answers would make it far more reliable.
- **No tests, and no accessibility checks** for the dashboard.
