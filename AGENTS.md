# Agent Working Rules

These rules are for coding agents working in this repository. Follow them before making changes and before marking work complete.

## Read First

Before implementing a feature, refactor, schema change, or UI change, read:

- `ARCHITECTURE.md`
- `README.md`
- `DESIGN_REFACTOR.md` for frontend work
- `INVENTORY_SALES.md` and `OPPORTUNITIES_INVENTORY.md` for inventory, sales, or opportunities work

`ARCHITECTURE.md` is the source of truth for module boundaries. Violating those boundaries is a bug.

## Documentation Refresh Rule

When a change is large enough to affect how future work should be understood, update the documentation in the same task.

A change is large enough when it does any of these:

- Adds, removes, renames, or materially changes a route, API endpoint, CLI command, page, workflow, or navigation item.
- Adds or changes a database table, persistent field, migration/schema initialization, config format, or durable data lifecycle.
- Changes core business logic, scheduler behavior, repricing rules, inventory/sales/opportunity conversion behavior, or source parsing assumptions.
- Refactors module boundaries, ownership, shared helpers, frontend rendering patterns, or cross-page component behavior.
- Changes the design system, page layout language, menu structure, AG Grid behavior, modal workflow, or visual interaction rules.
- Introduces a new integration, external dependency, cache/artifact directory, or generated output that future agents need to know about.
- Fixes a bug whose root cause is subtle enough that future agents could reintroduce it without written context.

Small text edits, narrow bug fixes, one-off test adjustments, and local-only cleanup do not need a full docs pass unless they change one of the areas above.

## Required Docs Sweep

For every major change, check and update as needed:

- `README.md` for user-facing behavior, routes, commands, outputs, and quick orientation.
- `ARCHITECTURE.md` for module responsibilities, data model, storage, routes, APIs, and cross-layer behavior.
- `DESIGN_REFACTOR.md` for frontend navigation, page decisions, visual rules, component vocabulary, and verification checklist.
- Domain-specific docs such as `INVENTORY_SALES.md` or `OPPORTUNITIES_INVENTORY.md` when the change affects that workflow.

Add a new `.md` file when the behavior has enough rules, edge cases, or future extension notes that it would clutter the general docs.

## Documentation Quality Bar

Docs should explain:

- What changed.
- Why the behavior exists.
- Which files/modules own it.
- Which routes, APIs, tables, config fields, or UI surfaces are involved.
- How the system behaves in important edge cases.
- How to verify the behavior manually or with tests.

Keep docs practical and specific. Prefer concrete route names, table names, field names, and file names over broad descriptions.

## Completion Checklist

Before final response on a major change:

- Update relevant docs, or explicitly state why no docs were needed.
- Run targeted tests or the full test suite when code changed.
- Check `git status --short`.
- Mention what changed, verification results, and the current file state in the final answer.
- Group changed files by feature area or purpose, and explain what each group does for the current feature. Include staged/unstaged/untracked/ignored state when relevant so the user can tell what is ready to commit and what is local-only.

When committing, split feature implementation and documentation into separate commits when that makes history easier to review.

When available, use codegraph/code search to inspect affected modules before editing.
