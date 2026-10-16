import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

// Exact GitHub Actions OIDC main-branch workflow; no public or user JWT bypass.
const jwks = createRemoteJWKSet(new URL("https://token.actions.githubusercontent.com/.well-known/jwks"));
const WORKFLOW = "sargesticky-code/football-fast-tracker/.github/workflows/retired-storage-archive.yml@refs/heads/main";
const MAX_BATCH_ROWS = 200;
const MAX_FILE_BYTES = 4_500_000;
const BUCKET = "fast-tracker-ingest";
const PREFIX = "retired/ft_identity_retired_rows/";
const te = new TextEncoder();
const reply = (status: number, data: Record<string, unknown>) =>
  Response.json(data, { status, headers: { "Cache-Control": "no-store" } });

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes.slice().buffer as ArrayBuffer);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function requestJSON(url: string, serviceKey: string, body: unknown): Promise<unknown> {
  const res = await fetch(url, {
    method: "POST",
    headers: { apikey: serviceKey, authorization: "Bearer " + serviceKey,
      "content-type": "application/json", accept: "application/json",
      "cache-control": "no-store" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(25000),
  });
  if (!res.ok) {
    // The DB returns a safe SQLSTATE and our fixed reason codes. Avoid
    // logging the request, source rows, or any credentials.
    let errorCode = "UNKNOWN";
    let reason = "REJECTED";
    try {
      const fault = await res.json() as Record<string, unknown>;
      if (typeof fault.code === "string" && /^[A-Z0-9]{5}$/.test(fault.code)) errorCode = fault.code;
      const allowed = new Set([
        "INVALID_ARCHIVE_ENVELOPE", "STORAGE_OBJECT_NOT_VERIFIED",
        "ARCHIVE_DUPLICATE_OR_MALFORMED_ROWS", "SOURCE_CHANGED_SINCE_BACKUP_READ",
        "ARCHIVE_DELETE_MISMATCH", "ARCHIVE_ALREADY_COMMITTED",
        "ARCHIVE_ROWS_NOT_ARRAY", "ARCHIVE_READ_LIMIT_INVALID",
      ]);
      if (typeof fault.message === "string" && allowed.has(fault.message)) reason = fault.message;
    } catch { /* malformed errors also stop safely */ }
    throw new Error("INTERNAL_RPC_FAILED_" + res.status + "_" + errorCode + "_" + reason);
  }
  return await res.json();
}

function assertRow(row: unknown): boolean {
  if (!row || typeof row !== "object") return false;
  const v = row as Record<string, unknown>;
  return typeof v.relation_name === "string" && v.relation_name.length > 0
    && typeof v.row_hash === "string" && /^[a-f0-9]{32}$/.test(v.row_hash)
    && typeof v.retired_at === "string" && Number.isFinite(Date.parse(v.retired_at))
    && typeof v.original_row === "object" && v.original_row !== null;
}

// Each invocation processes at most 12 * 200 rows. The GitHub job repeatedly
// invokes with fresh OIDC. No deletion occurs before Storage SHA256 read-back,
// JSON parse/row-count verification, and DB source-exact transactional check.
Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method !== "POST") return reply(405, { error: "METHOD_NOT_ALLOWED" });
  const auth = req.headers.get("authorization") || "";
  if (!auth.startsWith("Bearer ")) return reply(401, { error: "MISSING_OIDC" });
  let runId = "";
  try {
    const verified = await jwtVerify(auth.slice(7), jwks, {
      issuer: "https://token.actions.githubusercontent.com",
      audience: "fast-tracker-supabase",
      algorithms: ["RS256"],
      clockTolerance: "30s",
    });
    const c = verified.payload;
    if (c.repository !== "sargesticky-code/football-fast-tracker"
      || c.ref !== "refs/heads/main" || c.workflow_ref !== WORKFLOW
      || !["push", "workflow_dispatch", "schedule"].includes(String(c.event_name))
      || !/^[0-9]{6,20}$/.test(String(c.run_id))) {
      return reply(403, { error: "UNTRUSTED_WORKFLOW" });
    }
    runId = String(c.run_id);
  } catch {
    return reply(401, { error: "INVALID_GITHUB_OIDC" });
  }

  let config: { action?: string; batches?: number } = {};
  try { config = await req.json(); } catch { return reply(400, { error: "INVALID_JSON" }); }
  if (config?.action !== "archive" || (config.batches !== undefined
    && (!Number.isInteger(config.batches) || config.batches < 1 || config.batches > 12))) {
    return reply(422, { error: "INVALID_ARCHIVE_ACTION" });
  }
  const base = Deno.env.get("SUPABASE_URL");
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!base || !service) return reply(503, { error: "SERVICE_CONFIGURATION_MISSING" });
  const rpc = (name: string) => base + "/rest/v1/rpc/" + name;
  const storage = (path: string, authPath = false) =>
    base + "/storage/v1/object/" + (authPath ? "authenticated/" : "") + BUCKET + "/" + path;

  let deleted = 0, files = 0, uploadedBytes = 0, done = false, truncated = false;
  try {
    for (let i = 0; i < (config.batches || 10); i++) {
      let limit = MAX_BATCH_ROWS, rows: unknown[] = [];
      let bytes = new Uint8Array(), digest = "", path = "";
      while (limit >= 1) {
        const fetched = await requestJSON(rpc("ft_retired_archive_read"), service, { p_limit: limit });
        if (!Array.isArray(fetched) || fetched.length > limit || !fetched.every(assertRow)) {
          throw new Error("UNEXPECTED_SOURCE_BATCH");
        }
        rows = fetched;
        if (rows.length === 0) break;
        const pairs = new Set(rows.map((r) => {
          const v = r as Record<string, unknown>;
          return String(v.relation_name) + ":" + String(v.row_hash);
        }));
        if (pairs.size !== rows.length) throw new Error("DUPLICATE_SOURCE_KEY");
        const doc = { schema_version: 1, source_table: "private.ft_identity_retired_rows", rows };
        bytes = te.encode(JSON.stringify(doc));
        if (bytes.length <= MAX_FILE_BYTES) {
          digest = await sha256(bytes);
          const date = new Date().toISOString().slice(0, 10);
          path = PREFIX + date + "/" + digest + ".json";
          break;
        }
        limit = Math.floor(limit / 2);
      }
      if (!rows.length) {
        const fin = await requestJSON(rpc("ft_retired_archive_finalize"), service, {});
        if (!fin || typeof fin !== "object") throw new Error("INVALID_FINALIZE");
        const state = fin as Record<string, unknown>;
        done = state.empty === true && state.remaining === 0;
        truncated = state.truncated === true;
        break;
      }
      if (!path || !digest || !bytes.length) throw new Error("ARCHIVE_CHUNK_TOO_LARGE");

      const upload = await fetch(storage(path), {
        method: "POST",
        headers: {
          apikey: service, authorization: "Bearer " + service,
          "content-type": "application/octet-stream", "x-upsert": "false",
          "cache-control": "no-store"
        },
        body: bytes,
        signal: AbortSignal.timeout(30000),
      });
      // Storage may answer 400 Asset Already Exists for an immutable orphan
      // from a previously rolled-back DB receipt. This status is NOT success:
      // it is accepted solely to attempt readback of the same SHA-256 path.
      // No receipt or deletion occurs unless all independent checks pass.
      if (![200, 201, 400, 409].includes(upload.status)) {
        throw new Error("STORAGE_UPLOAD_FAILED_" + upload.status);
      }
      const download = await fetch(storage(path, true), {
        method: "GET",
        headers: { apikey: service, authorization: "Bearer " + service,
          "cache-control": "no-store" },
        signal: AbortSignal.timeout(30000),
      });
      if (!download.ok) throw new Error("STORAGE_DOWNLOAD_FAILED_" + download.status);
      const checkBytes = new Uint8Array(await download.arrayBuffer());
      if (checkBytes.length !== bytes.length || await sha256(checkBytes) !== digest) {
        throw new Error("BACKUP_ROUNDTRIP_CHECKSUM_MISMATCH");
      }
      const backup = JSON.parse(new TextDecoder().decode(checkBytes));
      if (backup.schema_version !== 1 || backup.source_table !== "private.ft_identity_retired_rows"
        || !Array.isArray(backup.rows) || backup.rows.length !== rows.length
        || !backup.rows.every(assertRow)) {
        throw new Error("BACKUP_RESTORE_PARSE_OR_COUNT_FAILED");
      }
      // This RPC verifies Storage metadata and exact source JSON & timestamps.
      // A receipt and the exact row deletion commit atomically or not at all.
      let result: unknown;
      try {
        result = await requestJSON(rpc("ft_retired_archive_commit"), service, {
          p_rows: rows, p_storage_path: path, p_sha256_hex: digest,
          p_file_bytes: bytes.length, p_github_run_id: runId,
        });
      } catch (err) {
        // Diagnostic is read-only; only safe mismatch counts, never row values,
        // hashes, secrets or URLs, leave Edge logs.
        if (String(err).includes("SOURCE_CHANGED_SINCE_BACKUP_READ")) {
          try {
            const diagnostic = await requestJSON(rpc("ft_retired_archive_diagnose"),
              service, {p_rows: rows}) as Record<string, unknown>;
            console.error("ARCHIVE_SOURCE_MISMATCH_COUNTS", JSON.stringify(diagnostic));
          } catch { console.error("ARCHIVE_DIAGNOSTIC_UNAVAILABLE"); }
        }
        throw err;
      }
      if (!result || typeof result !== "object"
        || (result as Record<string, unknown>).deleted !== rows.length
        || (result as Record<string, unknown>).verified_backup !== true) {
        throw new Error("ROW_COMMIT_NOT_CONFIRMED");
      }
      deleted += rows.length;
      files++;
      uploadedBytes += bytes.length;
    }
    return reply(200, { source: "RETIRED_STORAGE_VERIFIED_ARCHIVE_V1",
      deleted, files, uploaded_bytes: uploadedBytes, done, truncated });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "UNKNOWN";
    console.error("RETIRED_ARCHIVE_STOP", reason);
    return reply(503, { error: "ARCHIVE_FAIL_CLOSED", reason, deleted, files, done: false });
  }
});
