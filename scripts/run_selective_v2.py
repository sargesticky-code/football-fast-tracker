"""Production Forebet runner with durable matching and target recovery."""
from __future__ import annotations

from forebet_match_policy import install as install_match_policy

install_match_policy()

import run_selective as production  # noqa: E402  (must load after policy install)
from forebet_target_recovery import install as install_target_recovery  # noqa: E402

install_target_recovery(production)


if __name__ == "__main__":
    raise SystemExit(production.main())
