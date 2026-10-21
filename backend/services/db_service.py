import os
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

if not os.getenv("DATABASE_URL"):
    # No database configured (local dev without Supabase, and all tests)
    from services.memory_db import *  # noqa: F401,F403
    from services.memory_db import fail_stale_jobs  # noqa: F401
else:
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    from psycopg_pool import ConnectionPool

    from services.memory_db import version_of  # noqa: F401  (pure function, shared)

    _pool: ConnectionPool | None = None

    def _get_pool() -> ConnectionPool:
        global _pool
        if _pool is None:
            _pool = ConnectionPool(
                os.environ["DATABASE_URL"],
                min_size=1,
                max_size=5,
                open=False,
                # prepare_threshold=None keeps this working with Supabase's pooler
                kwargs={"row_factory": dict_row, "prepare_threshold": None},
            )
            _pool.open(wait=True, timeout=15)
        return _pool

    def _run(sql: str, params=None, fetch: str | None = None):
        with _get_pool().connection() as conn:  # commits on exit
            cur = conn.execute(sql, params)
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            return cur.rowcount

    # ---------- Jobs ----------

    _JOB_FIELDS = {"status", "result_url", "metadata", "error"}

    def create_job(job_type: str, user_id: str) -> str:
        job_id = f"job-{uuid4().hex[:8]}"
        _run(
            "insert into jobs (job_id, job_type, user_id) values (%s, %s, %s)",
            (job_id, job_type, user_id),
        )
        return job_id

    def update_job(job_id: str, **fields) -> None:
        unknown = set(fields) - _JOB_FIELDS
        if unknown:
            raise ValueError(f"Unknown job fields: {unknown}")
        if not fields:
            return
        # Column names come from the whitelist above, so this f-string is safe
        sets = ", ".join(f"{k} = %s" for k in fields)
        values = [
            Jsonb(v) if k == "metadata" and v is not None else v
            for k, v in fields.items()
        ]
        _run(f"update jobs set {sets}, updated_at = now() where job_id = %s", values + [job_id])

    def get_job(job_id: str) -> dict | None:
        return _run("select * from jobs where job_id = %s", (job_id,), "one")

    def fail_stale_jobs() -> int:
        """Background tasks die with the server, so anything still queued or
        processing at startup will never finish. Mark it failed so the UI stops polling."""
        return _run(
            "update jobs set status = 'failed', "
            "error = 'Server restarted before the job finished', updated_at = now() "
            "where status in ('queued', 'processing')"
        )

    # ---------- Wardrobe ----------

    def add_wardrobe_item(user_id: str, item: dict) -> None:
        _run(
            "insert into wardrobe_items "
            "(item_id, user_id, image_url, category, sub_category, color, fabric) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (
                item["item_id"], user_id, item["image_url"], item["category"],
                item.get("sub_category"), item.get("color"), item.get("fabric"),
            ),
        )

    def list_wardrobe_items(user_id: str) -> list[dict]:
        return _run(
            "select item_id, image_url, category, sub_category, color, fabric "
            "from wardrobe_items where user_id = %s order by created_at",
            (user_id,),
            "all",
        )

    # ---------- Outfit cache ----------

    def get_cached_outfits(user_id: str) -> list[dict] | None:
        items = list_wardrobe_items(user_id)
        row = _run(
            "select version, outfits from outfit_cache where user_id = %s",
            (user_id,),
            "one",
        )
        if row and row["version"] == version_of(items):
            return row["outfits"]
        return None

    def set_cached_outfits(user_id: str, outfits: list[dict], version: str) -> None:
        _run(
            "insert into outfit_cache (user_id, version, outfits) values (%s, %s, %s) "
            "on conflict (user_id) do update set "
            "version = excluded.version, outfits = excluded.outfits, updated_at = now()",
            (user_id, version, Jsonb(outfits)),
        )