from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests
from flask import Flask, Response, request

from libs.edge_db import EdgeDB
from libs.forwarder import BackgroundForwardLoop, FakeSiftForwarder, ForwardWorker, SiftSDKForwarder
from libs.measurement_store import MeasurementStore
from schedule_logger import ScheduleLogger, log_schedule_update


IGNORED_KEYS = {
    "PASSKEY",
    "runtime",
    "heap",
    "freq",
    "model",
    "stationtype",
    "interval",
}


def filter_telemetry_data(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in IGNORED_KEYS}


def parse_ecowitt_timestamp(dateutc_str: str) -> Optional[datetime]:
    if not dateutc_str:
        return None
    try:
        dt = datetime.strptime(dateutc_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _normalize_to_channel_values(filtered: dict):
    out = []
    for k, v in filtered.items():
        if v is None or v == "":
            continue
        try:
            out.append((f"ecowitt.{k}", float(v)))
        except (ValueError, TypeError):
            continue
    return out


def create_app() -> Flask:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    app = Flask(__name__)

    cors_allow_origins = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    cors_allow_all = cors_allow_origins == "*"
    cors_allow_list = [o.strip() for o in cors_allow_origins.split(",") if o.strip()]

    def _cors_origin_for_request() -> Optional[str]:
        origin = request.headers.get("Origin")
        if not origin:
            return None
        if cors_allow_all:
            return "*"
        if origin in cors_allow_list:
            return origin
        return None

    @app.before_request
    def _handle_cors_preflight():
        if request.method != "OPTIONS":
            return None
        allow_origin = _cors_origin_for_request()
        if not allow_origin:
            return ("", 204)
        resp = Response("", status=204)
        resp.headers["Access-Control-Allow-Origin"] = allow_origin
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "600"
        return resp

    @app.after_request
    def _add_cors_headers(resp):
        allow_origin = _cors_origin_for_request()
        if allow_origin:
            resp.headers["Access-Control-Allow-Origin"] = allow_origin
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    data_path = os.getenv("DATA_STORAGE_PATH", "data")
    opensprinkler_url = os.getenv("OPENSPRINKLER_URL", "")
    opensprinkler_password = os.getenv("OPENSPRINKLER_PASSWORD", "")
    edge_db_path = os.getenv("EDGE_DB_PATH", os.path.join(data_path, "edge.db"))
    sift_mode = os.getenv("SIFT_MODE", "fake").strip().lower()  # fake|sdk
    sift_asset = os.getenv("SIFT_ASSET") or os.getenv("SIFT_ASSET_NAME", "orchard-main")
    fake_sift_out = os.getenv("FAKE_SIFT_OUT", os.path.join(data_path, "fake_sift.jsonl"))
    forward_interval_seconds = int(os.getenv("FORWARD_INTERVAL_SECONDS", "30"))

    measurements = MeasurementStore(base_path=data_path)
    edge_db = EdgeDB(path=edge_db_path)

    schedule_logger: Optional[ScheduleLogger] = None
    if opensprinkler_url and opensprinkler_password:
        schedule_logger = ScheduleLogger(
            base_url=opensprinkler_url,
            password=opensprinkler_password,
            base_path=data_path,
        )
    else:
        logger.warning("OPENSPRINKLER_URL/PASSWORD not set - schedule logging disabled")

    def _make_forward_worker():
        if sift_mode == "sdk":
            forwarder = SiftSDKForwarder()
        else:
            forwarder = FakeSiftForwarder(out_path=fake_sift_out)
        return ForwardWorker(db=edge_db, forwarder=forwarder, asset=sift_asset)

    forward_worker = _make_forward_worker()
    forward_loop = BackgroundForwardLoop(worker=forward_worker, interval_seconds=forward_interval_seconds)

    @app.route("/ecowitt", methods=["POST"])
    def ecowitt_listener():
        try:
            raw_data = request.form.to_dict()
            filtered = filter_telemetry_data(raw_data)

            timestamp = None
            if "dateutc" in raw_data:
                timestamp = parse_ecowitt_timestamp(raw_data["dateutc"])
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)

            raw_event_id = edge_db.insert_raw_event(
                source="ecowitt",
                payload=raw_data,
                received_at=timestamp,
            )
            channel_values = _normalize_to_channel_values(filtered)
            edge_db.insert_measurements(raw_event_id=raw_event_id, ts=timestamp, channel_values=channel_values)

            try:
                measurements.store_reading(filtered, timestamp)
            except Exception as pe:
                logger.error("Parquet store_reading failed (sqlite queue already saved): %s", pe, exc_info=True)

            if "soilmoisture1" in filtered:
                logger.info(
                    f"Received: soilmoisture1={filtered.get('soilmoisture1')}% ({len(filtered)} sensors)"
                )

            return "OK", 200
        except Exception as e:
            logger.error(f"Error processing Ecowitt: {e}", exc_info=True)
            return "OK", 200

    @app.route("/health", methods=["GET"])
    def health():
        try:
            counts = edge_db.counts()
        except Exception as e:
            logger.error("health: edge_db.counts failed: %s", e, exc_info=True)
            return {"status": "unhealthy", "error": str(e)}, 503
        return {"status": "healthy", "pending_forward": counts["pending_forward"], "sift_mode": sift_mode}, 200

    @app.route("/status", methods=["GET"])
    def status():
        try:
            counts = edge_db.counts()
            events = edge_db.recent_system_events(limit=20)
        except Exception as e:
            logger.error("status: edge_db query failed: %s", e, exc_info=True)
            return {"error": str(e), "edge_db_path": edge_db_path}, 503
        return {
            "data_path": data_path,
            "edge_db_path": edge_db_path,
            "sift_mode": sift_mode,
            "sift_asset": sift_asset,
            "pending_forward": counts["pending_forward"],
            "total_measurements_indexed": counts["total_measurements"],
            "recent_events": events,
        }, 200

    @app.route("/admin/forward/run-once", methods=["POST"])
    def admin_forward_run_once():
        res = forward_worker.run_once()
        return {"attempted": res.attempted, "forwarded": res.forwarded, "error": res.error}, 200

    def _opensprinkler_update(params: dict) -> dict:
        pw = hashlib.md5(opensprinkler_password.encode()).hexdigest()
        all_params = {"pw": pw, **params}
        url = f"{opensprinkler_url.rstrip('/')}/cp"
        r = requests.get(url, params=all_params, timeout=10)
        r.raise_for_status()
        return r.json()

    @app.route("/schedule/update", methods=["POST"])
    def schedule_update():
        if not schedule_logger:
            return {"error": "Open Sprinkler not configured"}, 503

        try:
            body = request.get_json() or {}
            resp = _opensprinkler_update(body)

            log_schedule_update(data_path, request_data=body, response_data=resp)
            schedule_logger.log_schedule()

            return {"result": resp.get("result", 1), "response": resp}, 200
        except Exception as e:
            logger.error(f"Schedule update failed: {e}", exc_info=True)
            log_schedule_update(
                data_path,
                request_data=request.get_json() or {},
                response_data={"error": str(e)},
            )
            return {"error": str(e)}, 500

    # Expose runtime wiring for the entrypoint (systemd) to start background threads.
    # Tests import `server.app` and should not start background loops implicitly.
    app.extensions["orchardmonitor"] = {
        "logger": logger,
        "data_path": data_path,
        "edge_db_path": edge_db_path,
        "sift_mode": sift_mode,
        "sift_asset": sift_asset,
        "schedule_logger": schedule_logger,
        "forward_loop": forward_loop,
    }

    return app


def start_background(app: Flask) -> None:
    ext = app.extensions.get("orchardmonitor") or {}
    logger = ext.get("logger") or logging.getLogger(__name__)
    logger.info("Starting OrchardMonitor on 0.0.0.0:8080")
    logger.info(f"Data path: {ext.get('data_path')}")
    logger.info(f"DB path: {ext.get('edge_db_path')}")
    logger.info(f"Sift mode: {ext.get('sift_mode')} asset={ext.get('sift_asset')}")

    schedule_logger = ext.get("schedule_logger")
    if schedule_logger:
        schedule_logger.start_background()

    forward_loop = ext.get("forward_loop")
    if forward_loop:
        forward_loop.start()

