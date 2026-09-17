"""Production Forebet runner with durable matching, recovery and availability state."""
from __future__ import annotations

from forebet_match_policy import install as install_match_policy

install_match_policy()

import run_selective as production  # noqa: E402  (must load after policy install)
import forebet_target_recovery as target_recovery  # noqa: E402
from forebet_detail_parser import install as install_detail_parser  # noqa: E402
from forebet_availability import install as install_availability  # noqa: E402

# Keep match-detail parsing isolated from the broader recovery engine. Forebet's
# detail pages contain many navigation/sidebar mentions of "1 X 2"; the detail
# parser therefore anchors to the actual fixture and prediction-table headers.
install_detail_parser(target_recovery)
target_recovery.install(production)
install_availability(production)


if __name__ == "__main__":
    raise SystemExit(production.main())
