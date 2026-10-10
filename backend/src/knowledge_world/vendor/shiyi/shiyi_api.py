#!/usr/bin/env python3
"""Portable Shiyi API client. Python 3.10+, standard library only."""

from __future__ import annotations

import argparse
import http.client
import json
import math
import mimetypes
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

SUBJECTS = ("408", "math", "english")
NETWORK_ERRORS = (URLError, TimeoutError, ConnectionError, http.client.HTTPException)
MAX_UPLOAD = 15 * 1024 * 1024


class ClientError(Exception):
    def __init__(self, message, *, status=None, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib can forward Authorization to a different host. Use the canonical URL.
        return None


def normalize_url(value):
    if not isinstance(value, str) or not value.strip():
        raise ClientError("Set SHIYI_API_URL or api_url in the local config file.")
    value = value.strip()
    if any(character.isspace() for character in value):
        raise ClientError("The API URL must not contain whitespace.")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ClientError("Invalid API URL or port.") from error
    if parts.scheme not in ("http", "https") or not parts.hostname or port == 0:
        raise ClientError("The API URL must be an http:// or https:// server address.")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ClientError("Use a server address without credentials, query parameters, or fragments.")
    path = parts.path.rstrip("/")
    if path.endswith("/api/v1"):
        path = path[:-7]
    elif "/api/" in path or path.endswith("/api"):
        raise ClientError("Use the server root or a base URL ending in /api/v1, not an individual endpoint.")
    if any(segment in (".", "..") for segment in path.split("/")):
        raise ClientError("The API URL must not contain relative path segments.")
    root = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return root + "/api/v1"


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError) as error:
        raise ClientError("Use the actual UUID returned by the API for an item, chapter, image, or review.") from error


def load_json(filename):
    text = sys.stdin.read() if filename == "-" else Path(filename).read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text.lstrip("\ufeff"))
    except json.JSONDecodeError as error:
        raise ClientError(f"Invalid JSON at line {error.lineno}, column {error.colno}.") from error
    if not isinstance(data, dict):
        raise ClientError("The JSON input must be an object.")
    return data


def settings(args):
    explicit = args.config or os.environ.get("SHIYI_CONFIG")
    path = Path(explicit).expanduser() if explicit else Path.home() / ".config" / "shiyi-api" / "config.json"
    config = load_json(str(path)) if explicit or path.is_file() else {}
    url = args.url or os.environ.get("SHIYI_API_URL") or config.get("api_url")
    key = os.environ.get("SHIYI_API_KEY") or config.get("api_key", "")
    if not isinstance(key, str) or any(character.isspace() for character in key.strip()):
        raise ClientError("The API key must be a single token without whitespace.")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ClientError("--timeout must be a positive finite number of seconds.")
    return Client(url, key.strip(), timeout=args.timeout, no_proxy=args.no_proxy)


def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, dict):
        return {redact(key, secret): redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    return value


class Client:
    def __init__(self, url, key="", *, timeout=20, no_proxy=False):
        self.api_url = normalize_url(url)
        self.root_url = self.api_url[:-7]
        self.key = key
        self.timeout = timeout
        handlers = [NoRedirect()]
        if no_proxy:
            handlers.append(ProxyHandler({}))
        self.opener = build_opener(*handlers)

    def open(self, method, path, *, content=None, content_type=None, query=None, public=False):
        if not public and not self.key:
            raise ClientError("Set SHIYI_API_KEY or api_key in the local config file; create a key in the Shiyi website.")
        headers = {"Accept": "application/json", "User-Agent": "shiyi-api-skill/2.0"}
        if not public:
            headers["Authorization"] = "Bearer " + self.key
        if content_type:
            headers["Content-Type"] = content_type
        url = (self.root_url if public else self.api_url) + path
        if query:
            url += "?" + urlencode({name: str(value).lower() if isinstance(value, bool) else value
                                    for name, value in query.items() if value is not None})
        request = Request(url, data=content, headers=headers, method=method)
        try:
            return self.opener.open(request, timeout=self.timeout)
        except HTTPError as error:
            with error:
                raw = error.read(65536)
            try:
                detail = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = str(error.reason)
            hints = {
                401: "API key is invalid, expired, or revoked.",
                403: "API key lacks the required scope, or the server rejected the request.",
                404: "Record not found for this account, or the API address is incorrect.",
                409: "Conflict. Read the current state; do not silently replace versions or request IDs.",
                413: "Image exceeds the server upload limit.",
                422: "The server rejected the input. Check the fields and API reference.",
                429: "Rate limited. Stop and respect the server retry interval.",
            }
            hint = "Redirect refused. Configure the canonical server URL." if 300 <= error.code < 400 else hints.get(error.code, "The API request failed.")
            raise ClientError(hint, status=error.code, detail=redact(detail, self.key)) from None

    def request(self, method, path, *, body=None, query=None, public=False):
        content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8") if body is not None else None
        with self.open(method, path, content=content, content_type="application/json" if content is not None else None,
                       query=query, public=public) as response:
            if response.status == 204:
                return {"ok": True, "status": 204}
            raw = response.read()
            try:
                return redact(json.loads(raw.decode("utf-8")), self.key)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ClientError("Expected JSON from the API. Check the server address and reverse proxy.",
                                  status=response.status) from error

    def upload(self, filename):
        path = Path(filename)
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            raise ClientError("Upload a PNG, JPG, WebP, or GIF file.")
        with path.open("rb") as source:
            image = source.read(MAX_UPLOAD + 1)
        if not image or len(image) > MAX_UPLOAD:
            raise ClientError("Upload a nonempty image no larger than 15 MB.")
        boundary = "shiyi-" + uuid4().hex
        name = path.name.translate(str.maketrans({character: "_" for character in '\r\n"\\'}))
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                  f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        content = prefix + image + f"\r\n--{boundary}--\r\n".encode("ascii")
        with self.open("POST", "/media", content=content, content_type=f"multipart/form-data; boundary={boundary}") as response:
            try:
                return redact(json.loads(response.read().decode("utf-8")), self.key)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ClientError("The upload response was not valid JSON; its saved state is unknown.") from error

    def download(self, media_id, filename):
        media_id = identifier(media_id)
        destination = Path(filename).expanduser()
        if destination.exists():
            raise ClientError("The output file already exists. Choose another filename.")
        created = False
        try:
            with self.open("GET", f"/media/{media_id}") as response:
                if not response.headers.get_content_type().startswith("image/"):
                    raise ClientError("Expected an authenticated image response.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with destination.open("xb") as output:
                    created = True
                    while chunk := response.read(65536):
                        output.write(chunk)
                        size += len(chunk)
            return {"media_id": media_id, "saved_to": str(destination.resolve()), "bytes": size}
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise


def check_version(body, minimum):
    if type(body.get("expected_version")) is not int or body["expected_version"] < minimum:
        field = "item.version" if minimum else "item.schedule.version"
        raise ClientError(f"Include expected_version from {field}; do not substitute a newly fetched version after a conflict.")


def validate_review(body):
    allowed = {"request_id", "rating", "expected_version", "duration_ms", "answer_text", "answer_media",
               "expected_item_version", "independent_completed", "blocker"}
    if set(body) - allowed:
        raise ClientError("Unknown review fields; see references/api.md.")
    check_version(body, 0)
    if body.get("rating") not in ("again", "hard", "good", "easy"):
        raise ClientError("rating must be again, hard, good, or easy and describe an actual attempt.")
    item_version = body.get("expected_item_version")
    if item_version is not None and (type(item_version) is not int or item_version < 1):
        raise ClientError("expected_item_version must be an integer of at least 1, or null.")
    independent = body.get("independent_completed")
    if independent is not None and type(independent) is not bool:
        raise ClientError("independent_completed must be true, false, or null.")
    blocker = body.get("blocker", "")
    if not isinstance(blocker, str) or len(blocker.strip()) > 2000:
        raise ClientError("blocker must be text, at most 2000 characters after trimming whitespace.")
    if independent is False:
        if not blocker.strip() or body["rating"] != "again":
            raise ClientError("independent_completed=false requires a nonempty blocker and rating=again.")
    elif blocker.strip():
        raise ClientError("A nonempty blocker requires independent_completed=false.")
    if independent is True and body["rating"] == "again":
        raise ClientError("independent_completed=true cannot use rating=again.")
    request_id = body.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 100:
        raise ClientError("The review must have a saved request_id. Use review-prepare first.")
    duration = body.get("duration_ms", 0)
    if type(duration) is not int or not 0 <= duration <= 86400000:
        raise ClientError("duration_ms must be an integer from 0 to 86400000.")
    answer = body.get("answer_text", "")
    media = body.get("answer_media", [])
    if not isinstance(answer, str) or len(answer) > 30000:
        raise ClientError("answer_text must be text, at most 30000 characters.")
    if not isinstance(media, list) or len(media) > 8:
        raise ClientError("answer_media must contain at most 8 uploaded image IDs.")
    for value in media:
        identifier(value)


def prepare_review(client, item_id, body, filename):
    if "request_id" in body:
        raise ClientError("Do not generate another attempt to retry a review. Submit the existing attempt file.")
    body = {"duration_ms": 0, "answer_text": "", "answer_media": [], **body, "request_id": str(uuid4())}
    validate_review(body)
    attempt = {"format": "shiyi-review-attempt", "version": 1, "api_url": client.api_url,
               "item_id": identifier(item_id), "body": body}
    path = Path(filename).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(attempt, output, ensure_ascii=False, allow_nan=False, indent=2)
        output.write("\n")
    return {"submitted": False, "attempt_file": str(path.resolve()), "request_id": body["request_id"]}


def submit_review(client, attempt):
    if attempt.get("format") != "shiyi-review-attempt" or attempt.get("version") != 1:
        raise ClientError("Use an attempt file created by review-prepare.")
    if normalize_url(attempt.get("api_url")) != client.api_url:
        raise ClientError("The attempt belongs to a different API address. Use its original server configuration.")
    body = attempt.get("body")
    if not isinstance(body, dict):
        raise ClientError("Invalid attempt body.")
    validate_review(body)
    return client.request("POST", f"/items/{identifier(attempt.get('item_id'))}/reviews", body=body)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--config", help="Local JSON config; otherwise SHIYI_CONFIG or ~/.config/shiyi-api/config.json")
    cli.add_argument("--url", help="Server root or /api/v1 base URL; overrides SHIYI_API_URL")
    cli.add_argument("--timeout", type=float, default=20, help="Request timeout in seconds (default: 20)")
    cli.add_argument("--no-proxy", action="store_true", help="Connect directly, bypassing system HTTP proxies")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="Check the service without an API key")
    commands.add_parser("doctor", help="Check service identity, API key, and read access without changing data")
    commands.add_parser("stats", help="Fetch learning statistics")
    commands.add_parser("chapters", help="List chapters")
    commands.add_parser("context", help="Fetch agent context, profile, summaries, and actual permissions")
    reviews = commands.add_parser("reviews", help="Fetch a filtered page of review records")
    reviews.add_argument("--item-id", help="Item UUID returned by the API")
    reviews.add_argument("--rating", choices=("again", "hard", "good", "easy"))
    for name in ("independent-completed", "has-blocker"):
        reviews.add_argument("--" + name, choices=("true", "false"))
    for name in ("date-from", "date-to"):
        reviews.add_argument("--" + name, help="YYYY-MM-DD in the server learning timezone")
    for name in ("include-undone", "include-deleted", "include-answers"):
        reviews.add_argument("--" + name, action="store_true")
    weaknesses = commands.add_parser("weaknesses", help="Fetch a page of weakness summaries")
    weaknesses.add_argument("--days", type=int, default=30)
    for command in (reviews, weaknesses):
        command.add_argument("--subject", choices=SUBJECTS)
        command.add_argument("--page", type=int, default=1)
        command.add_argument("--page-size", type=int, default=20)
    listing = commands.add_parser("list", help="Search, filter, and paginate knowledge")
    listing.add_argument("--source-item-id", help="Source item UUID returned by the API")
    listing.add_argument("--question-only", action="store_true", help="Omit answer and reflection fields from output")
    for name in ("q", "chapter_id", "tag", "external_id"):
        listing.add_argument("--" + name.replace("_", "-"), dest=name)
    for name, choices in {"subject": SUBJECTS, "difficulty": ("basic", "medium", "hard"),
                          "kind": ("concept", "problem", "vocabulary", "expression"),
                          "status": ("all", "active", "draft", "suspended", "deleted"),
                          "state": ("new", "due", "learning", "review", "relearning"),
                          "sort": ("updated", "created", "due", "title")}.items():
        listing.add_argument("--" + name, choices=choices)
    listing.add_argument("--is-mistake", choices=("true", "false"))
    listing.add_argument("--page", type=int, default=1)
    listing.add_argument("--page-size", type=int, default=24)
    due = commands.add_parser("due", help="Fetch an answer-free review queue")
    due.add_argument("--subject", choices=SUBJECTS)
    due.add_argument("--limit", type=int, default=100)
    for name in ("get", "delete", "restore", "preview", "history", "undo", "chapter-delete"):
        command = commands.add_parser(name)
        command.add_argument("id", help="Record UUID returned by the API")
        if name == "get":
            command.add_argument("--question-only", action="store_true", help="Omit answer and reflection fields from output")
        if name == "history":
            command.add_argument("--page", type=int, default=1)
    for name in ("create", "update", "chapter-create", "chapter-update", "review-prepare", "review-submit"):
        command = commands.add_parser(name)
        if name in ("update", "chapter-update", "review-prepare"):
            command.add_argument("id", help="Record UUID returned by the API")
        command.add_argument("--file", required=True, help="UTF-8 JSON file; - reads standard input")
        if name == "review-prepare":
            command.add_argument("--out", required=True, help="New local attempt file; existing files are never overwritten")
    upload = commands.add_parser("upload", help="Upload an image and return its media ID")
    upload.add_argument("file")
    download = commands.add_parser("download", help="Download a private image using API authentication")
    download.add_argument("id")
    download.add_argument("--out", required=True)
    return cli


def agent_request(client, path, **kwargs):
    try:
        return client.request("GET", "/agent/" + path, **kwargs)
    except ClientError as error:
        if error.status != 404:
            raise
        raise ClientError("Upgrade the Shiyi backend to use agent context, reviews, and weaknesses; "
                          "legacy CRUD commands remain available.", status=404, detail=error.detail) from None


def validate_review_dates(date_from, date_to):
    dates = []
    for value in (date_from, date_to):
        if value is None:
            dates.append(None)
            continue
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ClientError("Review dates must use YYYY-MM-DD.")
        try:
            dates.append(date.fromisoformat(value))
        except ValueError as error:
            raise ClientError("Review dates must be valid calendar dates in YYYY-MM-DD format.") from error
    start, end = dates
    if start is not None and end is not None:
        if end < start:
            raise ClientError("date-from must not be after date-to.")
        if (end - start).days + 1 > 366:
            raise ClientError("The review date range must not exceed 366 days, including both endpoints.")


def execute(args, client):
    command = args.command
    if command in ("health", "doctor"):
        health = client.request("GET", "/api/health", public=True)
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise ClientError("The server did not report a healthy Shiyi service.")
        if command == "health":
            return health
        result = {"ok": True, "api_url": client.api_url, "server_version": health.get("version")}
        try:
            context = agent_request(client, "context")
        except ClientError as error:
            if error.status != 404:
                raise
            chapters = client.request("GET", "/chapters")
            if not isinstance(chapters, list):
                raise ClientError("Unexpected chapters response; check the API URL.")
            return {**result, "read_access": True, "agent_support": False,
                    "note": "Upgrade the Shiyi backend for agent endpoints and actual scope reporting. "
                            "Legacy CRUD commands remain available; write/review scopes were not probed."}
        if (not isinstance(context, dict) or type(context.get("agent_api_version")) is not int
                or context["agent_api_version"] != 1 or not isinstance(context.get("permissions"), list)
                or not all(isinstance(scope, str) for scope in context["permissions"])
                or "read" not in context["permissions"]):
            raise ClientError("Unexpected agent context or permissions; check the API URL and backend version.")
        return {**result, "read_access": True, "agent_support": True,
                "agent_api_version": context["agent_api_version"], "permissions": context["permissions"],
                "note": "Permissions reported by the server; no write or review operation was attempted."}
    if command == "context":
        return agent_request(client, "context")
    if command in ("reviews", "weaknesses"):
        if args.page < 1 or not 1 <= args.page_size <= 100:
            raise ClientError("page must be at least 1; page-size must be from 1 to 100.")
        query = {"subject": args.subject, "page": args.page, "page_size": args.page_size}
        if command == "reviews":
            validate_review_dates(args.date_from, args.date_to)
            names = ("rating", "independent_completed", "has_blocker", "date_from", "date_to",
                     "include_undone", "include_deleted", "include_answers")
            query.update({name: getattr(args, name) for name in names})
            query["item_id"] = identifier(args.item_id) if args.item_id is not None else None
        else:
            if not 1 <= args.days <= 365:
                raise ClientError("days must be from 1 to 365.")
            query["days"] = args.days
        return agent_request(client, command, query=query)
    if command in ("stats", "chapters"):
        return client.request("GET", "/" + command)
    if command == "list":
        if args.page < 1 or not 1 <= args.page_size <= 100:
            raise ClientError("page must be at least 1; page-size must be from 1 to 100.")
        names = ("subject", "q", "chapter_id", "tag", "external_id", "difficulty", "kind", "status", "state", "sort", "is_mistake", "page", "page_size")
        query = {name: getattr(args, name) for name in names}
        query["source_item_id"] = identifier(args.source_item_id) if args.source_item_id is not None else None
        result = client.request("GET", "/items", query=query)
        if args.question_only:
            result = {**result, "items": [
                {name: value for name, value in item.items()
                 if name not in ("answer", "answer_media", "mistake_reason", "takeaway")}
                for item in result["items"]]}
        return result
    if command == "due":
        if not 1 <= args.limit <= 200:
            raise ClientError("limit must be from 1 to 200.")
        return client.request("GET", "/reviews/due", query={"subject": args.subject, "limit": args.limit})
    if command in ("get", "delete", "restore", "preview", "history"):
        path = "/items/" + identifier(args.id)
        if command == "delete":
            return client.request("DELETE", path)
        if command == "restore":
            return client.request("POST", path + "/restore")
        if command == "preview":
            return client.request("GET", path + "/preview")
        if command == "history":
            if args.page < 1:
                raise ClientError("page must be at least 1.")
            return client.request("GET", path + "/reviews", query={"page": args.page})
        result = client.request("GET", path)
        if args.question_only:
            result = {name: value for name, value in result.items() if name not in ("answer", "answer_media", "mistake_reason", "takeaway")}
        return result
    if command == "undo":
        return client.request("POST", f"/reviews/{identifier(args.id)}/undo")
    if command == "chapter-delete":
        return client.request("DELETE", f"/chapters/{identifier(args.id)}")
    if command == "upload":
        return client.upload(args.file)
    if command == "download":
        return client.download(args.id, args.out)
    body = load_json(args.file)
    if command == "review-prepare":
        return prepare_review(client, args.id, body, args.out)
    if command == "review-submit":
        return submit_review(client, body)
    if command == "create":
        return client.request("POST", "/items", body=body)
    if command == "update":
        check_version(body, 1)
        return client.request("PATCH", f"/items/{identifier(args.id)}", body=body)
    if command == "chapter-create":
        return client.request("POST", "/chapters", body=body)
    if command == "chapter-update":
        return client.request("PATCH", f"/chapters/{identifier(args.id)}", body=body)
    raise ClientError("Unknown command.")


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    client = None
    try:
        args = parser().parse_args(argv)
        client = settings(args)
        result = execute(args, client)
        print(json.dumps(redact(result, client.key), ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except ClientError as error:
        message = {"ok": False, "error": str(error)}
        if error.status is not None:
            message["status"] = error.status
        if error.detail is not None:
            message["detail"] = error.detail
    except NETWORK_ERRORS:
        message = {"ok": False, "error": "Connection failed or response was interrupted. A write may already have succeeded. For review-submit, retry the same attempt file; for other writes, inspect the saved state before retrying."}
    except (OSError, ValueError) as error:
        message = {"ok": False, "error": f"Local input or file error: {error}"}
    except KeyboardInterrupt:
        message = {"ok": False, "error": "Interrupted. Check saved state before retrying any write; reuse the same review attempt file."}
    print(json.dumps(redact(message, client.key if client is not None else ""), ensure_ascii=False, indent=2),
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
