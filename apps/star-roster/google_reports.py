#!/usr/bin/env python3
"""Read Search Console and Analytics reports for the local Star Roster app."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen
import webbrowser
from zoneinfo import ZoneInfo

SITE = "https://chnragdoll.github.io/anki-pipeline/"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
STATE = Path.home() / "Library/Application Support/StarRoster/google-reports.json"


class ReportError(Exception):
    pass


def request(url, *, fields=None, body=None, token=None):
    headers = {}
    data = None
    if fields is not None:
        data = urlencode(fields).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=25) as response:
            return json.load(response)
    except HTTPError as error:
        if url == TOKEN_URL and error.code == 400:
            raise ReportError("Google 授权已过期或被撤销，请重新连接。") from None
        raise ReportError(f"Google API 返回 HTTP {error.code}。请检查 API、资源权限与设置。") from None


def save_credentials(value):
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=STATE.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
            temporary.replace(STATE)
        finally:
            temporary.unlink(missing_ok=True)


def connect(path):
    try:
        client = json.loads(Path(path).read_text())["installed"]
        client_id = client["client_id"]
        client_secret = client["client_secret"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ReportError("请选择 Google Cloud 的桌面应用 OAuth 客户端 JSON。") from None

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def do_GET(self):
            parsed = urlsplit(self.path)
            values = parse_qs(parsed.query)
            if parsed.path != "/oauth2callback" or not secrets.compare_digest(
                values.get("state", [""])[0], state
            ):
                self.send_error(404)
                return
            code = values.get("code", [""])[0]
            result["code"] = code
            message = "已收到 Google 授权结果，可以回到 Star 记录。" if code else "授权未完成，可以回到 Star 记录重试。"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(message.encode())

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        redirect = f"http://127.0.0.1:{server.server_port}/oauth2callback"
        query = urlencode({
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
            "access_type": "offline", "prompt": "consent", "scope": f"{GSC_SCOPE} {GA4_SCOPE}",
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        })
        if not webbrowser.open(f"https://accounts.google.com/o/oauth2/v2/auth?{query}"):
            raise ReportError("无法打开系统浏览器完成 Google 授权。")
        server.timeout = 1
        cutoff = time.monotonic() + 180
        while "code" not in result and time.monotonic() < cutoff:
            server.handle_request()
    if not result.get("code"):
        raise ReportError("未完成 Google 授权，请重新连接。")
    tokens = request(TOKEN_URL, fields={
        "client_id": client_id, "client_secret": client_secret, "code": result["code"],
        "code_verifier": verifier, "redirect_uri": redirect, "grant_type": "authorization_code",
    })
    if not tokens.get("refresh_token"):
        raise ReportError("Google 未发放可用于后续刷新数据的授权，请重试。")
    scopes = tokens.get("scope", "").split()
    if GSC_SCOPE not in scopes and GA4_SCOPE not in scopes:
        raise ReportError("未授予 Search Console 或 GA4 的读取权限。")
    save_credentials({
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": tokens["refresh_token"], "scopes": scopes,
    })


def day_range(days, zone):
    end = datetime.now(ZoneInfo(zone)).date() - timedelta(days=1)
    return str(end - timedelta(days=days - 1)), str(end)


def search_reports(token, days):
    first, last = day_range(days, "America/Los_Angeles")
    endpoint = f"https://www.googleapis.com/webmasters/v3/sites/{quote(SITE, safe='')}/searchAnalytics/query"

    def rows(dimensions):
        output = []
        page_size = 25000
        while True:
            response = request(endpoint, token=token, body={
                "startDate": first, "endDate": last, "dimensions": dimensions,
                "type": "web", "dataState": "final", "rowLimit": page_size, "startRow": len(output),
            })
            batch = response.get("rows", [])
            output.extend(batch)
            if len(batch) < page_size:
                return output

    return {"days": rows(["date"]), "pages": rows(["date", "page"]),
            "queries": rows(["date", "page", "query"])}


def analytics_report(token, property_id, days):
    endpoint = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
    output = []
    offset = 0
    while True:
        response = request(endpoint, token=token, body={
            "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "yesterday"}],
            "dimensions": [{"name": name} for name in ("date", "pagePath", "customEvent:download_slot")],
            "metrics": [{"name": "eventCount"}],
            "dimensionFilter": {"andGroup": {"expressions": [
                {"filter": {"fieldName": "eventName", "stringFilter": {"value": "release_download_click"}}},
                {"filter": {"fieldName": "hostName", "stringFilter": {"value": "chnragdoll.github.io"}}},
            ]}},
            "orderBys": [{"dimension": {"dimensionName": name}}
                         for name in ("date", "pagePath", "customEvent:download_slot")],
            "limit": 25000, "offset": offset,
        })
        batch = response.get("rows", [])
        for row in batch:
            raw_day, page, slot = (column["value"] for column in row["dimensionValues"])
            day = date(int(raw_day[:4]), int(raw_day[4:6]), int(raw_day[6:]))
            if page.startswith("/anki-pipeline/"):
                output.append({"day": str(day), "page": page, "slot": slot,
                               "count": int(row["metricValues"][0]["value"])})
        offset += len(batch)
        if len(batch) < 25000:
            return {"rows": output, "timezone": response.get("metadata", {}).get("timeZone")}


def reports(property_id, days):
    if not STATE.is_file():
        return {"searchError": "Google 尚未连接。", "analyticsError": "Google 尚未连接。"}
    credentials = json.loads(STATE.read_text())
    token = request(TOKEN_URL, fields={
        "client_id": credentials["client_id"], "client_secret": credentials["client_secret"],
        "refresh_token": credentials["refresh_token"], "grant_type": "refresh_token",
    })["access_token"]
    scopes = credentials["scopes"]
    result = {}

    def collect(name, scope, operation):
        if scope not in scopes:
            return {name + "Error": "未授予此来源的只读权限，请重新连接 Google。"}
        try:
            return {name: operation()}
        except (ReportError, OSError, ValueError) as error:
            return {name + "Error": str(error) if isinstance(error, ReportError) else "连接 Google 报表失败。"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(collect, "search", GSC_SCOPE, lambda: search_reports(token, days))
        if property_id:
            result.update(collect("analytics", GA4_SCOPE, lambda: analytics_report(token, property_id, days)))
        else:
            result["analyticsError"] = "请输入 GA4 的数字 Property ID。"
        result.update(future.result())
    return result


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("connect").add_argument("client_file")
    report = commands.add_parser("report")
    report.add_argument("--property", default="")
    report.add_argument("--days", type=int, choices=(7, 28, 90), default=28)
    arguments = parser.parse_args()
    try:
        if arguments.command == "connect":
            connect(arguments.client_file)
            output = {"ok": True}
        else:
            if arguments.property and (not arguments.property.isascii() or not arguments.property.isdecimal()):
                raise ReportError("GA4 Property ID 必须是数字。")
            output = reports(arguments.property, arguments.days)
    except ReportError as error:
        output = {"error": str(error)}
    except (OSError, ValueError, KeyError, TypeError):
        output = {"error": "无法读取 Google 配置或报表，请检查网络并重试。"}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
