"""Production Forebet runner with durable matching, recovery and availability state."""
from __future__ import annotations

from forebet_match_policy import install as install_match_policy

install_match_policy()

import run_selective as production  # noqa: E402  (must load after policy install)
from forebet_target_recovery import install as install_target_recovery  # noqa: E402
from forebet_availability import install as install_availability  # noqa: E402

install_target_recovery(production)
install_availability(production)


if __name__ == "__main__":
    raise SystemExit(production.main())
