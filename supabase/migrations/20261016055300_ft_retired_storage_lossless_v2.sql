-- Production already has these lossless, service_role-only backup contracts.
-- Keep exact definitions version controlled; existing original_row jsonb RPCs remain historical.
CREATE OR REPLACE FUNCTION public.ft_retired_archive_commit_lossless(p_rows jsonb, p_storage_path text, p_sha256_hex text, p_file_bytes integer, p_github_run_id text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'private', 'public', 'storage'
AS $function$
DECLARE n integer; seen integer; matched integer; removed integer;
BEGIN
 IF p_rows IS NULL OR jsonb_typeof(p_rows)<>'array' THEN
   RAISE EXCEPTION 'ARCHIVE_ROWS_NOT_ARRAY'; END IF;
 n:=jsonb_array_length(p_rows);
 IF n<1 OR n>200 OR p_file_bytes<50 OR p_file_bytes>5242880
 OR p_sha256_hex !~ '^[a-f0-9]{64}$'
 OR p_storage_path !~ '^retired/ft_identity_retired_rows/[0-9]{4}-[0-9]{2}-[0-9]{2}/[a-f0-9]{64}[.]json$'
 OR p_storage_path IS NULL OR p_github_run_id IS NULL
 OR p_github_run_id !~ '^[0-9]{6,20}$'
 THEN RAISE EXCEPTION 'INVALID_ARCHIVE_ENVELOPE'; END IF;
 PERFORM pg_advisory_xact_lock(20261016,417);
 IF EXISTS(SELECT 1 FROM private.ft_retired_storage_archive_ledger WHERE storage_path=p_storage_path)
 THEN RAISE EXCEPTION 'ARCHIVE_ALREADY_COMMITTED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM storage.objects WHERE bucket_id='fast-tracker-ingest'
 AND name=p_storage_path AND (metadata->>'size')::bigint=p_file_bytes)
 THEN RAISE EXCEPTION 'STORAGE_OBJECT_NOT_VERIFIED'; END IF;
 SELECT count(*),count(distinct relation_name||chr(31)||row_hash)
 INTO seen,matched FROM jsonb_to_recordset(p_rows) AS x(
 relation_name text,row_hash text,original_row_json text,retired_at timestamptz);
 IF seen<>n OR matched<>n THEN RAISE EXCEPTION 'ARCHIVE_DUPLICATE_OR_MALFORMED_ROWS'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_rows) AS x(
 relation_name text,row_hash text,original_row_json text,retired_at timestamptz)
 WHERE original_row_json IS NULL OR length(original_row_json)>2000000
 OR left(ltrim(original_row_json),1)<>'{')
 THEN RAISE EXCEPTION 'ARCHIVE_ORIGINAL_JSON_MISSING'; END IF;
 SELECT count(*) INTO matched FROM private.ft_identity_retired_rows t
 JOIN jsonb_to_recordset(p_rows) AS x(
 relation_name text,row_hash text,original_row_json text,retired_at timestamptz)
 ON t.relation_name=x.relation_name AND t.row_hash=x.row_hash
 AND t.original_row=x.original_row_json::jsonb AND t.retired_at=x.retired_at;
 IF matched<>n THEN RAISE EXCEPTION 'SOURCE_CHANGED_SINCE_BACKUP_READ'; END IF;
 DELETE FROM private.ft_identity_retired_rows t
 USING jsonb_to_recordset(p_rows) AS x(
 relation_name text,row_hash text,original_row_json text,retired_at timestamptz)
 WHERE t.relation_name=x.relation_name AND t.row_hash=x.row_hash
 AND t.original_row=x.original_row_json::jsonb AND t.retired_at=x.retired_at;
 GET DIAGNOSTICS removed=ROW_COUNT;
 IF removed<>n THEN RAISE EXCEPTION 'ARCHIVE_DELETE_MISMATCH'; END IF;
 INSERT INTO private.ft_retired_storage_archive_ledger
 (storage_path,sha256_hex,file_bytes,retired_rows,github_run_id)
 VALUES (p_storage_path,p_sha256_hex,p_file_bytes,n,p_github_run_id);
 RETURN jsonb_build_object('deleted',removed,'verified_backup',true,'storage_path',p_storage_path);
END $function$
;

CREATE OR REPLACE FUNCTION public.ft_retired_archive_read_lossless(p_limit integer DEFAULT 200)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'private', 'public'
AS $function$
BEGIN
  IF p_limit IS NULL OR p_limit<1 OR p_limit>200 THEN
    RAISE EXCEPTION 'INVALID_ARCHIVE_READ_LIMIT';
  END IF;
  RETURN (SELECT coalesce(jsonb_agg(jsonb_build_object(
   'relation_name',t.relation_name,'row_hash',t.row_hash,
   'original_row_json',t.original_row::text,'retired_at',t.retired_at)
   ORDER BY t.relation_name,t.row_hash),'[]'::jsonb)
   FROM (SELECT relation_name,row_hash,original_row,retired_at
         FROM private.ft_identity_retired_rows
         ORDER BY relation_name,row_hash LIMIT p_limit) t);
END $function$
;

REVOKE ALL ON FUNCTION public.ft_retired_archive_read_lossless(integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ft_retired_archive_read_lossless(integer) TO service_role;
REVOKE ALL ON FUNCTION public.ft_retired_archive_commit_lossless(jsonb,text,text,integer,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ft_retired_archive_commit_lossless(jsonb,text,text,integer,text) TO service_role;
