# Starter Example

Use this local-first workflow from the repository root:

1. `python -m cellin.cli ingest --config examples/starter/cellin-starter.json --input examples/starter/seed_envelopes.json`
2. `python -m cellin.cli retrieve --config examples/starter/cellin-starter.json --query "memory graph retrieval" --top-k 2`
3. `python -m cellin.cli dream --config examples/starter/cellin-starter.json --strategy abstraction`
4. `python -m cellin.cli eval run --suite smoke --config examples/starter/cellin-starter.json --output eval-results/starter-smoke.json`
5. `python -m cellin.cli trace inspect --config examples/starter/cellin-starter.json --limit 5`

The starter config demonstrates role-specific storage (`memory`, `graph`, `vector`, `representation`)
using SQLite for graph/memory and in-memory vector indexes by default.
