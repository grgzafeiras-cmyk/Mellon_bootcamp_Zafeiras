import json
import logging
import os
import time
from datetime import datetime

import pandas as pd
import redis
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_URL = (
    f"mysql+pymysql://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}"
    f"@{os.getenv('MYSQL_HOST', 'mysql')}:{os.getenv('MYSQL_PORT', '3306')}"
    f"/{os.getenv('MYSQL_DATABASE')}"
)
engine = create_engine(DB_URL, pool_pre_ping=True)
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"), port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True, socket_connect_timeout=1, socket_timeout=1,
)


def json_value(value):
    """Turn MySQL/Pandas values into JSON-safe values."""
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def rows_to_dicts(rows):
    return [{key: json_value(value) for key, value in row.items()} for row in rows]


def database_error(exc):
    logger.error("Database operation failed: %s", exc)
    return jsonify(error="database error"), 500


def cache_get(key):
    try:
        raw = redis_client.get(key)
        logger.info("Cache %s for %s", "HIT" if raw else "MISS", key)
        return json.loads(raw) if raw else None
    except redis.RedisError as exc:
        logger.error("Redis read failed; continuing without cache: %s", exc)
        return None


def cache_set(key, payload, ttl):
    try:
        redis_client.setex(key, ttl, json.dumps(payload))
    except (redis.RedisError, TypeError) as exc:
        logger.error("Redis write failed; continuing without cache: %s", exc)


def clear_cache():
    try:
        redis_client.flushdb()
        logger.info("Cache invalidated")
    except redis.RedisError as exc:
        logger.error("Redis invalidation failed: %s", exc)


def ensure_extra_schema():
    """Create app-owned schema objects safely on every API startup."""
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'terminals'
              AND COLUMN_NAME = 'updated_on'
        """)).scalar_one()
        if not exists:
            conn.execute(text("ALTER TABLE terminals ADD COLUMN updated_on DATETIME NULL"))
            logger.info("Added terminals.updated_on")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS decommission_queue (
                tid VARCHAR(20) NOT NULL PRIMARY KEY,
                queued_on DATETIME NOT NULL,
                delete_after DATETIME NOT NULL,
                CONSTRAINT fk_decommission_terminal FOREIGN KEY (tid)
                    REFERENCES terminals(tid)
            )
        """))


def initialize_schema_with_retry(attempts=15, delay_seconds=2):
    """Wait for MySQL/Docker DNS instead of exiting during service startup."""
    for attempt in range(1, attempts + 1):
        try:
            ensure_extra_schema()
            return
        except SQLAlchemyError as exc:
            if attempt == attempts:
                logger.error("Could not initialize application schema: %s", exc)
                raise
            logger.warning(
                "MySQL is not ready yet (attempt %s/%s); retrying in %s seconds: %s",
                attempt, attempts, delay_seconds, exc,
            )
            engine.dispose()
            time.sleep(delay_seconds)


@app.get("/health")
def health():
    status, code = {}, 200
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = "ok"
    except SQLAlchemyError as exc:
        logger.error("Health database check failed: %s", exc)
        status["database"] = "unavailable"
        code = 503
    try:
        redis_client.ping()
        status["redis"] = "ok"
    except redis.RedisError as exc:
        logger.error("Health Redis check failed: %s", exc)
        status["redis"] = "unavailable"
        code = 503
    status["status"] = "ok" if code == 200 else "degraded"
    return jsonify(status), code


@app.get("/terminals")
def list_terminals():
    enabled = request.args.get("enabled")
    if enabled not in (None, "true", "false"):
        return jsonify(error="enabled must be true or false"), 400
    key = f"terminals:list:{enabled or 'all'}"
    if (cached := cache_get(key)) is not None:
        return jsonify(cached)
    query = """SELECT t.tid, m.mid, t.hardware_model, t.software_version,
                      t.enabled, t.last_call_stamp AS last_call
               FROM terminals t JOIN merchants m ON m.id = t.merchant_id"""
    params = {}
    if enabled is not None:
        query += " WHERE t.enabled = :enabled"
        params["enabled"] = enabled == "true"
    query += " ORDER BY t.tid"
    try:
        with engine.connect() as conn:
            payload = rows_to_dicts(conn.execute(text(query), params).mappings().all())
        cache_set(key, payload, 30)
        return jsonify(payload)
    except SQLAlchemyError as exc:
        return database_error(exc)


@app.get("/terminals/flagged")
def flagged_terminals():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT t.*, m.mid FROM terminals t JOIN merchants m ON m.id = t.merchant_id
                WHERE t.scenario_number IS NOT NULL AND t.scenario_number NOT IN ('', '0')
                ORDER BY t.tid
            """)).mappings().all()
        return jsonify(rows_to_dicts(rows))
    except SQLAlchemyError as exc:
        return database_error(exc)


@app.get("/terminals/decommissioned")
def decommissioned():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT t.tid, m.mid, q.queued_on, q.delete_after,
                  GREATEST(0, TIMESTAMPDIFF(DAY, NOW(), q.delete_after)) AS days_remaining
                FROM decommission_queue q JOIN terminals t ON t.tid = q.tid
                JOIN merchants m ON m.id = t.merchant_id ORDER BY q.delete_after
            """)).mappings().all()
        return jsonify(rows_to_dicts(rows))
    except SQLAlchemyError as exc:
        return database_error(exc)


@app.get("/terminals/<tid>")
def terminal_detail(tid):
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT t.*, m.mid, m.name AS merchant_name FROM terminals t
                JOIN merchants m ON m.id = t.merchant_id WHERE t.tid = :tid
            """), {"tid": tid}).mappings().first()
        return (jsonify(rows_to_dicts([row])[0]), 200) if row else (jsonify(error="terminal not found"), 404)
    except SQLAlchemyError as exc:
        return database_error(exc)


def update_flag(tid, value):
    try:
        with engine.begin() as conn:
            old = conn.execute(text("SELECT scenario_number FROM terminals WHERE tid = :tid"), {"tid": tid}).scalar_one_or_none()
            if old is None:
                return jsonify(error="terminal not found"), 404
            conn.execute(text("""
                UPDATE terminals SET scenario_number = :value, updated_on = NOW() WHERE tid = :tid
            """), {"value": value, "tid": tid})
        logger.info("Terminal %s scenario_number changed from %s to %s", tid, old, value)
        clear_cache()
        return jsonify(tid=tid, scenario_number=value)
    except SQLAlchemyError as exc:
        return database_error(exc)


@app.post("/terminals/<tid>/flag")
def flag(tid):
    body = request.get_json(silent=True) or {}
    if "scenario_number" not in body:
        return jsonify(error="scenario_number is required"), 400
    return update_flag(tid, str(body["scenario_number"]))


@app.post("/terminals/<tid>/unflag")
def unflag(tid):
    return update_flag(tid, "0")


@app.post("/terminals/<tid>/decommission")
def decommission(tid):
    try:
        with engine.begin() as conn:
            enabled = conn.execute(text("SELECT enabled FROM terminals WHERE tid = :tid FOR UPDATE"), {"tid": tid}).scalar_one_or_none()
            if enabled is None:
                return jsonify(error="terminal not found"), 404
            if not enabled:
                return jsonify(error="terminal already decommissioned"), 409
            conn.execute(text("UPDATE terminals SET enabled = 0, updated_on = NOW() WHERE tid = :tid"), {"tid": tid})
            conn.execute(text("""
                INSERT INTO decommission_queue (tid, queued_on, delete_after)
                VALUES (:tid, NOW(), DATE_ADD(NOW(), INTERVAL 3 DAY))
            """), {"tid": tid})
        clear_cache()
        return jsonify(tid=tid, status="decommissioned"), 200
    except SQLAlchemyError as exc:
        return database_error(exc)


@app.get("/templates")
def templates():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM templates ORDER BY id")).mappings().all()
        return jsonify(rows_to_dicts(rows))
    except SQLAlchemyError as exc:
        return database_error(exc)


@app.get("/templates/<int:template_id>")
def template_detail(template_id):
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM templates WHERE id = :id"), {"id": template_id}).mappings().first()
        return (jsonify(rows_to_dicts([row])[0]), 200) if row else (jsonify(error="template not found"), 404)
    except SQLAlchemyError as exc:
        return database_error(exc)


@app.post("/terminals/from-template")
def from_template():
    body = request.get_json(silent=True) or {}
    if "template_id" not in body or "mid" not in body:
        return jsonify(error="template_id and mid are required"), 400
    try:
        with engine.begin() as conn:
            template = conn.execute(text("SELECT * FROM templates WHERE id = :id"), {"id": body["template_id"]}).mappings().first()
            if not template:
                return jsonify(error="template not found"), 404
            merchant = conn.execute(text("SELECT id, mid FROM merchants WHERE mid = :mid FOR UPDATE"), {"mid": body["mid"]}).mappings().first()
            if not merchant:
                return jsonify(error="merchant not found"), 404
            prefix = "T" + merchant["mid"][-4:]
            suffix = conn.execute(text("""
                SELECT COALESCE(MAX(CAST(RIGHT(tid, 3) AS UNSIGNED)), 0) FROM terminals
                WHERE tid LIKE :prefix
            """), {"prefix": prefix + "%"}).scalar_one()
            new_tid = f"{prefix}{int(suffix) + 1:03d}"
            conn.execute(text("""
                INSERT INTO terminals (tid, merchant_id, template_id, serial_number, hardware_model,
                    hardware_family, scenario_number, enabled, last_call_stamp, updated_on)
                VALUES (:tid, :merchant_id, :template_id, :serial_number, :hardware_model,
                    :hardware_family, '0', 1, NOW(), NOW())
            """), {"tid": new_tid, "merchant_id": merchant["id"], "template_id": template["id"],
                  "serial_number": f"{new_tid}SN", "hardware_model": template["hardware_model"],
                  "hardware_family": template["hardware_family"]})
        clear_cache()
        return jsonify(tid=new_tid), 201
    except SQLAlchemyError as exc:
        return database_error(exc)


def statistics_payload(name, builder):
    key = f"statistics:{name}"
    if (cached := cache_get(key)) is not None:
        return jsonify(cached)
    try:
        with engine.connect() as conn:
            payload = builder(conn)
        cache_set(key, payload, 60)
        return jsonify(payload)
    except (SQLAlchemyError, ValueError) as exc:
        return database_error(exc)


@app.get("/statistics/by-hardware")
def by_hardware():
    return statistics_payload("by-hardware", lambda c: {"generated_at": datetime.now().isoformat(), "data": rows_to_dicts(pd.read_sql(text("SELECT hardware_model, COUNT(*) AS count FROM terminals GROUP BY hardware_model ORDER BY hardware_model"), c).to_dict("records"))})


@app.get("/statistics/by-hardware-family")
def by_hardware_family():
    return statistics_payload("by-hardware-family", lambda c: {"generated_at": datetime.now().isoformat(), "data": rows_to_dicts(pd.read_sql(text("SELECT hardware_family, COUNT(*) AS count FROM terminals GROUP BY hardware_family ORDER BY hardware_family"), c).to_dict("records"))})


@app.get("/statistics/by-state")
def by_state():
    def build(conn):
        frame = pd.read_sql(text("SELECT enabled FROM terminals"), conn)
        active = int(frame["enabled"].sum())
        total = int(len(frame))
        return {"generated_at": datetime.now().isoformat(), "active": active, "inactive": total - active, "total": total}
    return statistics_payload("by-state", build)


@app.get("/statistics/idle-distribution")
def idle_distribution():
    def build(conn):
        frame = pd.read_sql(text("SELECT last_call_stamp FROM terminals"), conn)
        days = (pd.Timestamp.now() - pd.to_datetime(frame["last_call_stamp"])).dt.days
        labels = ["Today", "1-7 days", "8-30 days", "31-90 days", "90+ days"]
        frame["range"] = pd.cut(days, bins=[-1, 0, 7, 30, 90, float("inf")], labels=labels)
        counts = frame.groupby("range", observed=False).size().reindex(labels, fill_value=0)
        return {"generated_at": datetime.now().isoformat(), "data": [{"range": label, "count": int(counts[label])} for label in labels]}
    return statistics_payload("idle-distribution", build)


if __name__ == "__main__":
    initialize_schema_with_retry()
    app.run(host="0.0.0.0", port=5000)
