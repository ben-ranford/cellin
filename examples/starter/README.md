# Starter Example

Use this local-first workflow from the repository root:

1. `python -m cellin.cli storage list --role memory`
2. `python -m cellin.cli storage init --config examples/starter/cellin-starter.json --dry-run`
3. `python -m cellin.cli ingest --config examples/starter/cellin-starter.json --input examples/starter/seed_envelopes.json`
4. `python -m cellin.cli retrieve --config examples/starter/cellin-starter.json --query "memory graph retrieval" --top-k 2`
5. `python -m cellin.cli dream --config examples/starter/cellin-starter.json --strategy abstraction`
6. `python -m cellin.cli eval run --suite smoke --config examples/starter/cellin-starter.json --output eval-results/starter-smoke.json`
7. `python -m cellin.cli trace inspect --config examples/starter/cellin-starter.json --limit 5`

The starter config demonstrates role-specific storage (`memory`, `graph`, `vector`, `representation`)
using an explicit SQLite preset for graph/memory and in-memory vector indexes. Use `storage init`
without `--dry-run` if you want to create the starter SQLite file before the first ingest.
