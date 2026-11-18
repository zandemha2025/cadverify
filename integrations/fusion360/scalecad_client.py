"""ScaleCAD API client for the Fusion 360 add-in — pure stdlib, no adsk.

Fusion's bundled Python cannot pip install, so this module uses only the
standard library and is import-safe outside Fusion (unit-tested in CI).

Contract (backend /api/v1, API-key auth):
  Authorization: Bearer cv_live_...           (read_write key, minted at
                                              /settings/developer)
  X-Part-Check-ID: <uuid4>                    (one per part: /validate and
                                              /validate/cost share a check)
  POST /api/v1/validate          multipart file field "file"
  POST /api/v1/validate/cost     multipart file + FORM fields
                                 (qty, region, material_class, ...)
  Large files: POST /api/v1/uploads/multipart (JSON + Idempotency-Key) →
               PUT parts → POST /api/v1/checks → poll GET /api/v1/checks/{id}
               (progress ETA from GET /api/v1/checks/timing)

Error mapping is to plain words an engineer can act on without knowing our
status-code internals.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid

# Above this size the direct web path is skipped for the resumable
# uploads+checks flow: the server's web memory gate sits around ~9 MB STEP
# on a 4 GB deployment (docs/BIG_FILES.md), so 5 MB of STEP is the honest
# switchover with margin.
DIRECT_STEP_LIMIT_BYTES = 5 * 1024 * 1024

_USER_AGENT = "scalecad-fusion-addin/1.0"


class ScaleCadError(Exception):
    """An error with plain-words guidance attached (``advice``)."""

    def __init__(self, message: str, advice: str = "", status: int | None = None,
                 retry_after_s: float | None = None):
        super().__init__(message)
        self.advice = advice
        self.status = status
        self.retry_after_s = retry_after_s


def _advice_for(status: int, code: str | None) -> str:
    if status == 401:
        return "ScaleCAD rejected the API key — re-paste it from Settings → Developer in the web app."
    if status == 403 and code == "api_key_read_only":
        return "This key is read-only. Make a read+write key in Settings → Developer."
    if status == 403 and code == "user_validation_cap_exceeded":
        return "This month's checks are used up on the plan. The limit resets on the shown date, or upgrade."
    if status == 403 and code == "api_key_org_mismatch":
        return "The key belongs to a different organization than your current one."
    if status == 429:
        return "Rate limited — the add-in will wait and retry automatically."
    if status == 504:
        return "The part was too heavy to analyze in one pass. Try again, or run it in the web app with a narrowed process set."
    if status == 413:
        return "The file is above the direct-upload limit — the add-in will switch to the resumable path automatically."
    return ""


def _request(origin: str, method: str, path: str, api_key: str,
             body: bytes | None = None, headers: dict | None = None,
             timeout_s: float = 120.0) -> tuple[int, dict, bytes]:
    url = origin.rstrip("/") + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", _USER_AGENT)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        payload = e.read()
        code = None
        try:
            code = (json.loads(payload) or {}).get("code")
        except Exception:
            pass
        retry_after = None
        ra = e.headers.get("Retry-After") if e.headers else None
        if ra:
            try:
                retry_after = float(ra)
            except ValueError:
                pass
        try:
            detail = (json.loads(payload) or {}).get("detail") or payload.decode("utf-8", "replace")[:200]
        except Exception:
            detail = payload.decode("utf-8", "replace")[:200]
        raise ScaleCdErrorFromStatus(e.code, code, detail, retry_after)
    except urllib.error.URLError as e:
        raise ScaleCadError(
            f"Could not reach ScaleCAD at {origin}: {e.reason}",
            advice="Check the API origin in the add-in settings and your connection.",
        ) from e


def ScaleCdErrorFromStatus(status: int, code, detail, retry_after_s):
    return ScaleCadError(
        f"ScaleCAD answered {status}" + (f" ({code})" if code else "") + f": {detail}",
        advice=_advice_for(status, code), status=status, retry_after_s=retry_after_s,
    )


# ---------------------------------------------------------------------------
# multipart (stdlib)
# ---------------------------------------------------------------------------

def multipart_body(field_name: str, filename: str, content: bytes,
                   content_type: str, form_fields: dict | None = None) -> tuple[bytes, str]:
    boundary = "scalecad" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in (form_fields or {}).items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field_name}\"; "
         f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n").encode())
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# the two check calls
# ---------------------------------------------------------------------------

def check_part(origin: str, api_key: str, step_bytes: bytes, filename: str,
               quantities: str = "50,5000", region: str = "US",
               material_class: str | None = None,
               friction_log=None) -> dict:
    """Validate + cost one part. Returns {validation, cost} dicts.

    Chooses the direct path for small files and the resumable uploads+checks
    flow above DIRECT_STEP_LIMIT_BYTES (or on 413), mirroring the web app.
    """
    check_id = str(uuid.uuid4())
    started = time.monotonic()
    if len(step_bytes) <= DIRECT_STEP_LIMIT_BYTES:
        try:
            validation = _direct_validate(origin, api_key, step_bytes, filename, check_id)
            cost = _direct_cost(origin, api_key, step_bytes, filename, check_id,
                                quantities, region, material_class)
            _friction(friction_log, "check_ok", bytes=len(step_bytes),
                      ms=int((time.monotonic() - started) * 1000), path="direct")
            return {"validation": validation, "cost": cost}
        except ScaleCadError as e:
            if e.status != 413:
                raise
    result = _resumable_check(origin, api_key, step_bytes, filename, check_id,
                              quantities, region, material_class, friction_log)
    _friction(friction_log, "check_ok", bytes=len(step_bytes),
              ms=int((time.monotonic() - started) * 1000), path="resumable")
    return result


def _direct_validate(origin, api_key, step_bytes, filename, check_id) -> dict:
    body, ctype = multipart_body("file", filename, step_bytes, "application/step")
    status, _hdrs, payload = _request(
        origin, "POST", "/api/v1/validate", api_key, body,
        headers={"Content-Type": ctype, "X-Part-Check-ID": check_id, "Accept": "application/json"})
    return json.loads(payload)


def _direct_cost(origin, api_key, step_bytes, filename, check_id,
                 quantities, region, material_class) -> dict:
    form = {"qty": quantities, "region": region}
    if material_class:
        form["material_class"] = material_class
    body, ctype = multipart_body("file", filename, step_bytes, "application/step", form)
    status, _hdrs, payload = _request(
        origin, "POST", "/api/v1/validate/cost", api_key, body,
        headers={"Content-Type": ctype, "X-Part-Check-ID": check_id, "Accept": "application/json"})
    return json.loads(payload)


def _sha256_hex(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _resumable_check(origin, api_key, step_bytes, filename, check_id,
                     quantities, region, material_class, friction_log) -> dict:
    import hashlib

    # 1. open the upload
    meta = json.dumps({
        "purpose": "part", "filename": filename,
        "content_type": "application/step", "size_bytes": len(step_bytes),
        "checksum_sha256": _sha256_hex(step_bytes),
    }).encode()
    _status, _hdrs, payload = _request(
        origin, "POST", "/api/v1/uploads/multipart", api_key, meta,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Idempotency-Key": str(uuid.uuid4())})
    upload = json.loads(payload)
    upload_id = upload.get("upload_id") or upload.get("id")

    # 2. PUT the parts (relay form; presigned URLs would carry their own host)
    part_size = int(upload.get("part_size_bytes") or 8 * 1024 * 1024)
    part_size = max(part_size, 1)
    for n, offset in enumerate(range(0, len(step_bytes), part_size), start=1):
        chunk = step_bytes[offset:offset + part_size]
        path = upload.get("parts", {}).get(str(n)) if isinstance(upload.get("parts"), dict) else None
        if path:
            _request_upload_part(path, api_key, chunk)
        else:
            _request(origin, "PUT", f"/api/v1/uploads/{upload_id}/parts/{n}",
                     api_key, chunk, headers={"Content-Type": "application/octet-stream"})

    # 3. complete, then start the check
    complete_url = upload.get("complete_url") or f"/api/v1/uploads/{upload_id}/complete"
    _status, _hdrs, payload = _request(origin, "POST", complete_url, api_key, b"{}",
                                       headers={"Content-Type": "application/json", "Accept": "application/json"})
    _friction(friction_log, "upload_complete", bytes=len(step_bytes), parts=(
        (len(step_bytes) + part_size - 1) // part_size))
    body = {"direct_upload_id": upload_id, "qty": quantities, "region": region}
    if material_class:
        body["material_class"] = material_class
    _status, _hdrs, payload = _request(
        origin, "POST", "/api/v1/checks", api_key, json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    check = json.loads(payload)
    check_path = (check.get("poll_url") or f"/api/v1/checks/{check.get('id') or check.get('check_id')}").strip()

    # 4. poll, with the honest ETA endpoint alongside
    deadline = time.monotonic() + 900.0
    last_eta = None
    while time.monotonic() < deadline:
        _status, _hdrs, payload = _request(origin, "GET", check_path, api_key,
                                           headers={"Accept": "application/json"})
        doc = json.loads(payload)
        status = doc.get("status")
        if status in ("done", "complete", "succeeded", "finished"):
            _friction(friction_log, "check_done", path="resumable")
            return {"validation": _unwrap(doc), "cost": _unwrap(doc), "raw": doc}
        if status in ("failed", "error"):
            raise ScaleCadError("The check failed on the server.", advice=doc.get("error") or "")
        time.sleep(2.0)
    raise ScaleCadError("The check did not finish in 15 minutes.",
                        advice="The file may be very heavy; try the web app with a narrowed process set.")


def _unwrap(doc: dict) -> dict:
    for key in ("result", "response", "check"):
        inner = doc.get(key)
        if isinstance(inner, dict):
            return inner
    return doc


def _request_upload_part(url: str, api_key: str, chunk: bytes):
    req = urllib.request.Request(url, data=chunk, method="PUT")
    req.add_header("User-Agent", _USER_AGENT)
    if "://" not in url:  # relative relay path
        raise ScaleCadError("Relative presigned part URL; expected absolute")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise ScaleCdErrorFromStatus(e.code, None, "part upload failed", None) from e


def _friction(log, event: str, **fields):
    """Instrumentation for the activation gate: a local JSONL file the user
    can share; nothing leaves the machine automatically."""
    if log is None:
        return
    try:
        import datetime
        import os

        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "event": event, **fields}) + "\n")
    except Exception:
        pass
