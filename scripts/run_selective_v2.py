"""Production Forebet runner with durable matching, recovery and availability state."""
from __future__ import annotations

from forebet_match_policy import install as install_match_policy

install_match_policy()

import run_selective as production  # noqa: E402  (must load after policy install)
import forebet_target_recovery as target_recovery  # noqa: E402
from forebet_detail_parser import install as install_detail_parser  # noqa: E402
from forebet_unresolved_diagnostics import install as install_unresolved_diagnostics  # noqa: E402
from forebet_availability import install as install_availability  # noqa: E402

# Detail parser v3: anchor to the real fixture/table and tolerate Forebet's
# independently rounded integer probability totals of 99, 100 or 101.
install_detail_parser(target_recovery)
target_recovery.install(production)
# Diagnostics observes the fully recovered model surface but never changes a
# matching decision. Availability remains the outer wrapper/state authority.
install_unresolved_diagnostics(production)
install_availability(production)


if __name__ == "__main__":
    raise SystemExit(production.main())
