# AGENTS.md

## Purpose

This document defines repository-wide engineering behavior, implementation constraints, and AI execution rules.

---

# Core Principles

Priority order:

1. correctness
2. maintainability
3. consistency
4. simplicity
5. performance

Prefer:
- explicit code
- incremental change
- stable patterns
- type safety
- local readability

---

# General Rules

- read relevant files before editing
- understand existing patterns before implementing
- preserve module boundaries
- preserve naming consistency
- preserve stable public contracts
- keep changes localized
- prefer extending existing flows
- prefer editing existing files
- preserve explicit dependencies

---

# Forbidden Actions

Do not introduce:
- speculative abstractions
- hidden global state
- implicit cross-module coupling
- unnecessary framework layers
- duplicate parallel patterns
- premature extensibility systems

Do not:
- rewrite working code unnecessarily
- bypass module boundaries
- silently change public contracts
- suppress failing tests
- add dependencies casually
- introduce dead code
- leave unused abstractions
- introduce placeholder structures

---

# Complexity Management

- keep files focused and locally understandable
- split mixed responsibilities
- preserve navigability
- reduce context-switching cost
- optimize for incremental modification
- keep execution flow discoverable

Indicators for splitting:
- unrelated responsibilities
- difficult navigation
- excessive branching
- hidden execution flow
- difficult local reasoning

---

# Dependency Rules

- all dependencies must be declared in `pyproject.toml`
- prefer existing dependencies first
- prefer standard library first
- new dependencies require clear implementation benefit
- preserve explicit dependency direction

---

# Refactoring Rules

Allowed:
- localized cleanup
- duplication reduction
- readability improvements
- responsibility clarification
- incremental extraction

Preserve:
- module boundaries
- public contracts
- CLI interface
- execution flow
- configuration schema

Approval required for:
- large rewrites
- architecture redesign
- framework migration
- breaking CLI changes

---

# File Organization Rules

- keep related logic together
- split by responsibility and execution flow
- preserve local discoverability
- avoid deeply nested structures
- avoid placeholder files
- avoid empty abstractions
- optimize for local reasoning

Project structure:
- `src/code_nearby/` — core implementation
- `tests/` — test suite
- `pyproject.toml` — dependencies and configuration
- `README.md` — user documentation
- `AGENTS.md` — engineering rules

---

# Documentation Rules

## README.md

`README.md` contains:
- installation instructions
- usage examples
- development workflow

Update when:
- installation flow changes
- CLI interface changes
- development workflow changes

---

## AGENTS.md

`AGENTS.md` contains:
- engineering behavior
- implementation constraints
- repository-wide rules
- execution workflow

Update when:
- engineering constraints change
- repository-wide rules change
- implementation workflow changes

---

## CLAUDE.md

`CLAUDE.md` contains:
- project context for AI assistants
- architecture overview
- key patterns
- implementation guidelines

Update when:
- architecture changes
- new patterns emerge
- key constraints change

---

# Testing Rules

- add tests for new behavior
- preserve deterministic execution
- keep tests close to implementation
- prefer behavior-oriented tests
- use `pytest` for all tests
- preserve reproducible execution paths

Test organization:
- `tests/test_*.py` — unit and integration tests
- match `src/code_nearby/` structure

---

# Development Workflow

## Before Coding

1. read relevant files
2. identify affected boundaries
3. identify existing patterns
4. preserve module structure

---

## During Coding

1. keep changes localized
2. preserve explicit execution flow
3. preserve module boundaries
4. preserve local readability
5. avoid unrelated edits

---

## After Coding

Always provide:
- summary
- changed files
- remaining risks

---

# AI Execution Behavior

- read local context before proposing abstractions
- preserve existing layering
- preserve naming consistency
- preserve module boundaries
- prefer explicit implementation paths
- prefer concrete workflows
- keep generated code locally understandable
- keep execution flow observable
- optimize for maintainability and incremental evolution

---

# Decision Rules

When multiple implementations are valid:
- prefer consistency with existing code
- prefer simpler execution flow
- prefer localized complexity
- prefer explicit dependencies
- prefer maintainable structure
- prefer stable patterns
- prefer incremental evolution

---

# Python-Specific Rules

- use type hints for all public functions
- use `from __future__ import annotations` for forward references
- prefer `pathlib.Path` over string paths
- use `typer` for CLI commands
- follow PEP 8 style (enforced by `ruff`)
- keep functions focused and single-purpose
- prefer explicit over implicit
- use context managers for resource management
