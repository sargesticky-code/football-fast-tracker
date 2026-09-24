# Supabase migration sync guard

The production Supabase migration history and `supabase/migrations` must remain version-identical.

Operational rules:

1. Never invent or rename migration timestamps.
2. After any production DDL migration is applied, mirror the exact remote migration version, name and SQL into `supabase/migrations/<version>_<name>.sql`.
3. Before any database deploy, compare local migration versions with production remote history. Deployment must stop if either side has versions missing from the other.
4. Do not use `migration repair` merely to silence a mismatch. Repair changes history metadata only and is reserved for a proven history-table error.
5. Do not keep duplicate migrations containing already-applied SQL under a new timestamp.
6. Remote schema changes made outside the tracked migration flow must be pulled/mirrored before the next deploy.

Baseline restored on 2026-09-24 from the production migration history: 145 migrations, with zero local-only and zero remote-only versions.
