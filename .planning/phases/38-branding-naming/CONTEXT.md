# Phase 38: Branding & Naming — Context

## Decisions

- **Name**: PPRS (Papers Precision Retrieval & Synthesis)
- **Package name**: `pprs` (pyproject.toml)
- **Env prefix**: Keep `RP_` (no breaking change)
- **Directory**: Rename `/media/sam/1TB/research-pipeline` → `/media/sam/1TB/pprs`
- **Branding style**: Arcade/gaming inspired (user provided concept as starting point)
- **Logo**: ASCII art + potential pixel art character (Peper-S frog mascot idea)

## Rename Impact (from code analysis)

| Category | Files | Notes |
|----------|-------|-------|
| pyproject.toml | 1 | `name = "research-pipeline"` → `name = "pprs"` |
| docker-compose.yml | 1 | `name: research-pipeline` → `name: pprs` |
| Dockerfile | 1 | Comment only |
| systemd units | 7 | WorkingDirectory paths × 6 services + 1 target |
| ARCHITECTURE.md | 2 | Root + docs/ |
| README.md | 1 | Full rewrite with PPRS branding |
| .planning/ docs | Multiple | References to "research-pipeline" in prose |
| egg-info | Auto | Will regenerate |

## What does NOT change

- `RP_` env var prefix (user decided to keep)
- `shared/` and `services/` directory names (internal package structure)
- Import paths (`from shared import X` — no package prefix used)
- Port numbers (8770-8775)
- Database schema
- All existing tests
