#!/usr/bin/env python3
"""
Demo CLI uploader for two-step External Call Upload API.

Flow:
1) PUT /api/v1/integrations/calls/upload-init
2) PUT upload_url (binary file)
3) PUT /api/v1/integrations/calls/finalize
"""

import argparse
import hashlib
import json
import logging
import mimetypes
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests


BASE_URL = "https://demo.neuro-tech.ai"
UPLOAD_INIT_PATH = "/api/v1/integrations/calls/upload-init"
FINALIZE_PATH = "/api/v1/integrations/calls/finalize"

REQUEST_TIMEOUT = (10, 120)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1


logger = logging.getLogger("external_call_uploader")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def log_json(event: str, payload: Dict[str, Any]) -> None:
    body = {"event": event, **payload}
    logger.info("json=%s", json.dumps(body, ensure_ascii=False, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Two-step uploader for external call records (init -> binary upload -> finalize).",
    )
    parser.add_argument("file_path", type=str, help="Path to audio file")
    parser.add_argument("--token", required=True, help="Bearer token for integration API")

    parser.add_argument("--operator-phone", required=True, help="Operator phone in metadata")
    parser.add_argument("--client-phone", required=True, help="Client phone in metadata")
    parser.add_argument(
        "--start-time",
        required=True,
        help="Call start time in ISO8601 (e.g. 2026-03-01T10:20:30+03:00 or ...Z)",
    )
    parser.add_argument(
        "--call-type",
        required=True,
        choices=["in", "out"],
        help="Call direction",
    )
    return parser.parse_args()


def validate_start_time(value: str) -> str:
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid --start-time ISO8601: {value}") from exc
    return text


def generate_external_call_id(file_path: Path) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    stem = file_path.stem or "call"
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    raw = f"demo_{safe_stem}_{ts}_{suffix}"
    return raw[:128]


def guess_content_type(file_path: Path) -> str:
    content_type, _ = mimetypes.guess_type(file_path.name)
    return content_type or "application/octet-stream"


def file_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def should_retry_response(
    *,
    step: str,
    status_code: int,
    body: Optional[Dict[str, Any]],
) -> bool:
    if status_code == 429 or 500 <= status_code < 600:
        return True

    if step == "finalize" and status_code == 409:
        if not isinstance(body, dict):
            return False
        error_code = str(body.get("error_code") or "")
        retryable = bool(body.get("retryable"))
        return error_code == "UPLOAD_NOT_READY" or retryable

    return False


def request_with_retry(
    *,
    session: requests.Session,
    method: str,
    url: str,
    step: str,
    headers: Optional[Dict[str, str]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
    binary_path: Optional[Path] = None,
) -> requests.Response:
    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            if binary_path is not None:
                with binary_path.open("rb") as fh:
                    response = session.request(
                        method=method,
                        url=url,
                        headers=headers,
                        data=fh,
                        timeout=REQUEST_TIMEOUT,
                    )
            else:
                response = session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_payload,
                    timeout=REQUEST_TIMEOUT,
                )
        except requests.RequestException as exc:
            last_error = exc
            log_json(
                "request_exception",
                {"step": step, "attempt": attempt, "error": str(exc)},
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            continue

        body: Optional[Dict[str, Any]] = None
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                body = parsed
        except ValueError:
            body = None

        if should_retry_response(step=step, status_code=response.status_code, body=body):
            log_json(
                "request_retry",
                {
                    "step": step,
                    "attempt": attempt,
                    "status_code": response.status_code,
                    "error_code": (body or {}).get("error_code"),
                    "retryable": (body or {}).get("retryable"),
                },
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

        return response

    if last_error is not None:
        raise RuntimeError(f"HTTP request failed after retries: {last_error}") from last_error
    raise RuntimeError("HTTP request failed after retries")


def parse_json_response(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Non-JSON response status={response.status_code}, body={response.text[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON response type: {type(payload).__name__}")
    return payload


def fail_with_response(step: str, response: requests.Response, payload: Dict[str, Any]) -> None:
    raise RuntimeError(
        f"{step} failed: status={response.status_code}, "
        f"error_code={payload.get('error_code')}, message={payload.get('message')}"
    )


def main() -> int:
    setup_logging()
    args = parse_args()

    file_path = Path(args.file_path).expanduser().resolve()
    if not file_path.is_file():
        raise RuntimeError(f"File not found: {file_path}")

    start_time = validate_start_time(args.start_time)
    file_size = file_path.stat().st_size
    content_type = guess_content_type(file_path)
    checksum_sha256 = file_sha256(file_path)
    external_call_id = generate_external_call_id(file_path)

    print(f"File: {file_path}")
    print(f"File size: {file_size} bytes")
    print(f"Content-Type: {content_type}")
    print(f"SHA256: {checksum_sha256}")
    print(f"external_call_id (auto): {external_call_id}")

    common_headers = {
        "Authorization": f"Bearer {args.token}",
        "Content-Type": "application/json",
    }

    init_payload: Dict[str, Any] = {
        "external_call_id": external_call_id,
        "file_name": file_path.name,
        "file_size": file_size,
        "content_type": content_type,
        "sha256": checksum_sha256,
        "metadata": {
            "operator_phone": args.operator_phone,
            "client_phone": args.client_phone,
            "start_time": start_time,
            "call_type": args.call_type,
        },
    }

    log_json(
        "upload_flow_start",
        {
            "base_url": BASE_URL,
            "file_path": str(file_path),
            "file_size": file_size,
            "external_call_id": external_call_id,
        },
    )

    with requests.Session() as session:
        init_url = f"{BASE_URL}{UPLOAD_INIT_PATH}"
        init_resp = request_with_retry(
            session=session,
            method="PUT",
            url=init_url,
            step="upload_init",
            headers=common_headers,
            json_payload=init_payload,
        )
        init_data = parse_json_response(init_resp)
        log_json(
            "upload_init_response",
            {"http_status": init_resp.status_code, "response": init_data},
        )

        if init_resp.status_code != 200:
            fail_with_response("upload_init", init_resp, init_data)

        if init_data.get("already_finalized"):
            result = {
                "status": init_data.get("status", "duplicate"),
                "step": "upload_init",
                "already_finalized": True,
                "upload_id": init_data.get("upload_id"),
                "dialog_id": init_data.get("dialog_id"),
                "external_call_id": external_call_id,
                "request_id": init_data.get("request_id"),
            }
            print("Загрузка уже была финализирована на стороне сервера.")
            print(f"status={result['status']}, dialog_id={result.get('dialog_id')}")
            log_json("upload_flow_result", result)
            return 0

        upload_id = str(init_data.get("upload_id") or "")
        upload_url = str(init_data.get("upload_url") or "")
        if not upload_id or not upload_url:
            raise RuntimeError("upload_init response missing upload_id/upload_url")

        upload_headers = init_data.get("upload_headers")
        if not isinstance(upload_headers, dict):
            upload_headers = {"Content-Type": content_type}

        print("Шаг 1/3: upload-init выполнен")
        print(f"upload_id={upload_id}")

        upload_resp = request_with_retry(
            session=session,
            method="PUT",
            url=upload_url,
            step="upload_binary",
            headers={str(k): str(v) for k, v in upload_headers.items()},
            binary_path=file_path,
        )
        upload_data = parse_json_response(upload_resp)
        log_json(
            "upload_binary_response",
            {"http_status": upload_resp.status_code, "response": upload_data},
        )
        if upload_resp.status_code != 200:
            fail_with_response("upload_binary", upload_resp, upload_data)

        print("Шаг 2/3: бинарная загрузка выполнена")
        print(
            "bytes_received={bytes_received}, sha256={sha}".format(
                bytes_received=upload_data.get("bytes_received"),
                sha=upload_data.get("sha256"),
            )
        )

        finalize_payload = {
            "upload_id": upload_id,
            "external_call_id": external_call_id,
        }
        finalize_url = f"{BASE_URL}{FINALIZE_PATH}"
        finalize_resp = request_with_retry(
            session=session,
            method="PUT",
            url=finalize_url,
            step="finalize",
            headers=common_headers,
            json_payload=finalize_payload,
        )
        finalize_data = parse_json_response(finalize_resp)
        log_json(
            "finalize_response",
            {"http_status": finalize_resp.status_code, "response": finalize_data},
        )
        if finalize_resp.status_code != 200:
            fail_with_response("finalize", finalize_resp, finalize_data)

    result = {
        "status": finalize_data.get("status"),
        "dialog_id": finalize_data.get("dialog_id"),
        "dedup": finalize_data.get("dedup"),
        "upload_id": finalize_data.get("upload_id"),
        "external_call_id": external_call_id,
        "request_id": finalize_data.get("request_id"),
        "error_code": finalize_data.get("error_code"),
        "message": finalize_data.get("message"),
    }

    print("Шаг 3/3: finalize выполнен")
    print(
        "Итог: status={status}, dialog_id={dialog_id}, dedup={dedup}".format(
            status=result.get("status"),
            dialog_id=result.get("dialog_id"),
            dedup=result.get("dedup"),
        )
    )
    log_json("upload_flow_result", result)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logger = logging.getLogger("external_call_uploader")
        logger.exception("Uploader failed: %s", exc)
        log_json("upload_flow_failure", {"error": str(exc)})
        sys.exit(1)
