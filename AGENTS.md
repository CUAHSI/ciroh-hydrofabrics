# AGENTS.md

Instructions for AI coding agents working in this repository
(CUAHSI/ciroh-hydrofabrics). See `.ai/PROJECT_CONTEXT.md` for a full
description of the project structure and purpose.

## General Guidance
- This repo manages large geospatial data via DVC. Never commit large
  binary artifacts (`.gpkg`, `.tif`, `.parquet`, etc.) directly to git —
  they must be tracked with `dvc add` / pipeline stages and referenced via
  `.dvc` files.
- Prefer editing pipeline stage scripts in `ngen-workflow/R`,
  `ngen-workflow/Python`, or `ngen-workflow/bash` over ad hoc scripts when
  changing pipeline behavior, and keep `pipelines/<scenario>/dvc.yaml` and
  `params.yaml` in sync with any stage changes.
- When modifying the `subsetter/` Vue app, keep changes scoped there; it is
  independently deployed to GitHub Pages via
  `.github/workflows/deploy_pages.yaml`.
- Update the root `README.md` when pipeline stages, parameters, or outputs
  change, since it is the canonical stage-by-stage reference.
- Do not commit credentials (AWS/HydroShare profiles, tokens). Check for
  stray files like `github_token.txt` before adding new secrets.

## Coding Principles
- Follow the Unix philosophy: write small, focused pieces of code that do
  one thing well and compose cleanly, rather than monolithic scripts.
- Favor simple, easy-to-understand code over clever or overly compact
  solutions, even if it's more verbose.
- Comments are required on non-trivial code and should explain what is
  being done at a high level (intent/purpose), not restate the code
  line-by-line.
- Agents must always ask the user before editing files directly; do not
  make direct edits without explicit confirmation first.

## Adding Future Context
- Save durable project context/notes under `.ai/` (this directory) rather
  than scattering new markdown files across the repo.
- Update this file (`AGENTS.md`) directly whenever new standing instructions
  or conventions are established for this repository.
