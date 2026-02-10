# Roadmap: Research Pipeline

## Overview

Replace the failed N8N W1-W5 research paper pipeline with standalone Python microservices. Starting with shared infrastructure (v1.0), then building each service incrementally: Discovery → Analyzer → Extractor → Validator → Codegen → Orchestrator.

## Domain Expertise

None

## Milestones

- 🚧 **v1.0 Foundation** - Phases 1-4 (in progress)

## Phases

- [ ] **Phase 1: Research & Design** - Analyze CAS microservice pattern, design shared lib architecture
- [ ] **Phase 2: Database & Models** - SQLite schema, Pydantic models, DB layer
- [ ] **Phase 3: HTTP Server & Config** - Base HTTP server, config management, dotenvx integration
- [ ] **Phase 4: Test Suite** - Unit tests, integration tests, verification

## Phase Details

### 🚧 v1.0 Foundation (In Progress)

**Milestone Goal:** Shared infrastructure library that all 5 microservices + orchestrator will depend on.

#### Phase 1: Research & Design

**Goal**: Analyze CAS microservice (:8769) as reference pattern, design shared lib architecture (modules, interfaces, directory structure)
**Depends on**: Nothing (first phase)
**Research**: Likely (analyzing existing service code, architectural decisions for shared lib design)
**Research topics**: CAS microservice architecture, http.server patterns, SQLite connection patterns in Python
**Plans**: TBD

Plans:
- [ ] 01-01: TBD (run /gsd:plan-phase 01 to break down)

#### Phase 2: Database & Models

**Goal**: SQLite database layer with clean schema + Pydantic models for papers, formulas, validations, generated_code
**Depends on**: Phase 1
**Research**: Unlikely (sqlite3 stdlib, pydantic established patterns)
**Plans**: TBD

Plans:
- [ ] 02-01: TBD

#### Phase 3: HTTP Server & Config

**Goal**: Base HTTP server class (http.server pattern with /health, /status, /process endpoints) + centralized config management with dotenvx
**Depends on**: Phase 2
**Research**: Unlikely (follows patterns established in Phase 1 research)
**Plans**: TBD

Plans:
- [ ] 03-01: TBD

#### Phase 4: Test Suite

**Goal**: Comprehensive test suite — unit tests for each module, integration tests with real SQLite DB, endpoint tests for base HTTP server
**Depends on**: Phase 3
**Research**: Unlikely (standard pytest patterns)
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Research & Design | v1.0 | 0/? | Not started | - |
| 2. Database & Models | v1.0 | 0/? | Not started | - |
| 3. HTTP Server & Config | v1.0 | 0/? | Not started | - |
| 4. Test Suite | v1.0 | 0/? | Not started | - |
