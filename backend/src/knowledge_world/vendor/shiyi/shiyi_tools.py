"""Optional read-only function tools for agents; no LLM SDK or shell execution."""

from __future__ import annotations

import base64
import json
from datetime import date
from uuid import UUID

from .shiyi_api import redact

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_RESULT_CHARS = 131072
SUBJECT = {"type": "string", "enum": ["408", "math", "english"]}
ID = {"type": "string", "format": "uuid"}
PAGE = {"type": "integer", "minimum": 1, "default": 1}
PAGE_SIZE = {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}
BOOL = {"type": "boolean"}
DATE = {"type": "string", "format": "date"}


def tool(name, description, properties, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(required), "additionalProperties": False}}}


TOOLS = [
    tool("shiyi_context", "只读获取学习偏好、实际权限、今日任务数量和复习质量摘要，不含题目答案。", {}),
    tool("shiyi_search", "分页检索学习内容，默认隐藏答案；返回一页不代表全库。", {
        "q": {"type": "string", "maxLength": 200}, "subject": SUBJECT, "source_item_id": ID,
        "page": PAGE, "page_size": PAGE_SIZE, "include_answer": {**BOOL, "default": False}}),
    tool("shiyi_item", "读取一条题目，默认隐藏答案；只有用户作答或要求揭晓时才include_answer。", {
        "item_id": ID, "include_answer": {**BOOL, "default": False}}, ["item_id"]),
    tool("shiyi_due", "只读获取无答案的待复习队列；不评分，不代表本页已列出所有到期任务。", {
        "subject": SUBJECT, "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}}),
    tool("shiyi_reviews", "按日期、科目或卡点查询复习历史，默认最近30个学习日且不含作答正文。", {
        "subject": SUBJECT, "item_id": ID, "rating": {"type": "string", "enum": ["again", "hard", "good", "easy"]},
        "independent_completed": BOOL, "has_blocker": BOOL, "date_from": DATE, "date_to": DATE,
        "include_undone": BOOL, "include_deleted": BOOL, "include_answers": BOOL,
        "page": PAGE, "page_size": PAGE_SIZE}),
    tool("shiyi_weaknesses", "分页获取最近一次跨日首答仍失败的内容；初学卡点请查reviews。", {
        "subject": SUBJECT, "days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
        "page": PAGE, "page_size": PAGE_SIZE}),
    tool("shiyi_image", "认证读取一张私有图片，返回data URL供宿主转成模型图像输入；不能只把JSON当作看过图片。", {
        "media_id": ID}, ["media_id"]),
]


def validate_arguments(name, arguments):
    definition = next((entry["function"] for entry in TOOLS if entry["function"]["name"] == name), None)
    if definition is None:
        raise ValueError("Unknown or non-read-only tool")
    schema = definition["parameters"]
    if not isinstance(arguments, dict) or set(arguments) - schema["properties"].keys():
        raise ValueError("Tool arguments must be an object containing only declared fields")
    if any(key not in arguments for key in schema["required"]):
        raise ValueError("Missing required tool argument")
    values = {key: field["default"] for key, field in schema["properties"].items() if "default" in field}
    for key, value in arguments.items():
        field = schema["properties"][key]
        expected = {"string": str, "boolean": bool, "integer": int}[field["type"]]
        if type(value) is not expected:
            raise ValueError(f"Invalid type for {key}")
        if "enum" in field and value not in field["enum"]:
            raise ValueError(f"Invalid value for {key}")
        if expected is int and (value < field.get("minimum", value) or value > field.get("maximum", value)):
            raise ValueError(f"Out-of-range value for {key}")
        if expected is str and len(value) > field.get("maxLength", 2000):
            raise ValueError(f"Value is too long for {key}")
        if field.get("format") == "uuid":
            value = str(UUID(value))
        if field.get("format") == "date":
            value = date.fromisoformat(value).isoformat()
        values[key] = value
    if values.get("date_from") and values.get("date_to"):
        span = (date.fromisoformat(values["date_to"]) - date.fromisoformat(values["date_from"])).days
        if not 0 <= span <= 365:
            raise ValueError("Date range must be ordered and at most 366 days inclusive")
    return values


def without_answer(item):
    return {key: value for key, value in item.items()
            if key not in ("answer", "answer_media", "mistake_reason", "takeaway")}


def call_tool(name, arguments, client):
    """Execute a fixed GET-only tool. The host supplies its configured Shiyi Client."""
    args = validate_arguments(name, arguments)
    if name == "shiyi_image":
        with client.open("GET", f"/media/{args['media_id']}") as response:
            mime = response.headers.get_content_type()
            if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
                raise ValueError("Expected a supported image response")
            content = response.read(MAX_IMAGE_BYTES + 1)
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise ValueError("Image is empty or exceeds the 2 MiB model-tool limit; use the download command instead")
        return {"media_id": args["media_id"], "mime_type": mime, "bytes": len(content),
                "image_url": f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"}
    if name == "shiyi_item":
        result = client.request("GET", f"/items/{args['item_id']}")
        if not args["include_answer"]:
            result = without_answer(result)
    elif name == "shiyi_search":
        include_answer = args.pop("include_answer")
        result = client.request("GET", "/items", query=args)
        if not include_answer:
            result = {**result, "items": [without_answer(item) for item in result["items"]]}
    else:
        paths = {"shiyi_context": "/agent/context", "shiyi_due": "/reviews/due",
                 "shiyi_reviews": "/agent/reviews", "shiyi_weaknesses": "/agent/weaknesses"}
        result = client.request("GET", paths[name], query=args)
    result = redact(result, client.key)
    if len(json.dumps(result, ensure_ascii=False)) > MAX_RESULT_CHARS:
        raise ValueError("Result exceeds the tool output limit; narrow the query or use the CLI for large content")
    return result
