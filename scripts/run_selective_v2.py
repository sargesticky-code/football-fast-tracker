"""Production Forebet runner with durable matching policy installed first."""
from __future__ import annotations

from forebet_match_policy import install

install()

import run_selective as production  # noqa: E402  (must load after policy install)


if __name__ == "__main__":
    raise SystemExit(production.main())
