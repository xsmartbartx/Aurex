# ADR-0003: Python, TypeScript and PowerShell

- Status: Accepted
- Date: 2026-11-15

## Context

The concept names Python for backend and analytics and TypeScript for the terminal; the standards use PowerShell and Pester for operations.

## Decision

Python 3.11+ with FastAPI, Pydantic, SQLAlchemy and pytest; TypeScript with Next.js, React, ESLint and Vitest; PowerShell for backup and restore scripts tested with Pester. Python packages use single-word or snake_case names because a package directory cannot contain a hyphen; everything else follows kebab-case files and the language's naming conventions.

## Consequences

Every language in the repository has a naming and test standard.

## Alternatives considered

A Python-only interface; dropping PowerShell.
