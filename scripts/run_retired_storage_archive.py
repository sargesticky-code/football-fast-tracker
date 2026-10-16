#!/usr/bin/env python3
"""Bounded OIDC runner for verified, reversible Supabase retired-row archive.

No Supabase service key, database password or Storage credential is present on
the GitHub runner. The edge worker owns all privileged operations.
"""
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/ft-retired-storage-archive"
MAX_CALLS = 150
MAX_SECONDS = 31 * 60


def oidc():
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=fast-tracker-supabase"
    req = Request(url, headers={
        "Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"],
        "Accept": "application/json",
    })
    with urlopen(req, timeout=20) as resp:
        token = json.load(resp)["value"]
    if not isinstance(token, str) or len(token) < 100:
        raise ValueError("OIDC_RESPONSE_INVALID")
    # Mask even if the platform has not automatically masked the JWT.
    print("::add-mask::" + token)
    return token


def run():
    started = time.monotonic()
    total = files = uploaded = calls = 0
    for attempt in range(1, MAX_CALLS + 1):
        if time.monotonic() - started > MAX_SECONDS:
            raise RuntimeError("ARCHIVE_TIME_BUDGET_REACHED_WITH_ROWS_LEFT")
        token = oidc()  # every iteration: avoid expiring 5-minute GitHub JWT
        req = Request(
            ENDPOINT,
            data=json.dumps({"action": "archive", "batches": 10}).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=140) as resp:
                result = json.load(resp)
        except (HTTPError, URLError) as exc:
            # Response bodies contain only error codes; never print Authorization.
            raise RuntimeError("ARCHIVE_EDGE_INVOCATION_FAILED " + str(getattr(exc, "code", type(exc).__name__))) from None
        if result.get("source") != "RETIRED_STORAGE_VERIFIED_ARCHIVE_V1":
            raise RuntimeError("ARCHIVE_UNVERIFIED_RESPONSE")
        n, f, b = (result.get("deleted"), result.get("files"), result.get("uploaded_bytes"))
        if not all(isinstance(x, int) and x >= 0 for x in (n, f, b)):
            raise RuntimeError("ARCHIVE_INVALID_COUNTS")
        total += n
        files += f
        uploaded += b
        calls += 1
        print(f"RETIRE_ARCHIVE_PROGRESS call={calls} backed_up_and_deleted={total} "
              f"verified_files={files} bytes={uploaded} completed={result.get('done') is True}")
        if result.get("done") is True:
            if result.get("truncated") is not True:
                raise RuntimeError("ARCHIVE_EMPTY_TABLE_NOT_RECLAIMED")
            print("RETIRE_ARCHIVE_COMPLETED", json.dumps({
                "deleted_rows": total, "verified_files": files, "verified_bytes": uploaded,
                "complete_and_truncated": True,
            }))
            return 0
        if f == 0 and n == 0:
            raise RuntimeError("ARCHIVE_NO_PROGRESS")
    raise RuntimeError("ARCHIVE_MAX_CALLS_EXCEEDED_WITH_ROWS_LEFT")


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        print("::error::RETIRED_ARCHIVE_STOPPED " + str(exc))
        sys.exit(1)
