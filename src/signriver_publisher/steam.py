from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .cream import SteamAppInfo, SteamDlc


class SteamApiError(RuntimeError):
    pass


class SteamStoreClient:
    def __init__(
        self,
        *,
        timeout: float = 20,
        max_response_bytes: int = 4 * 1024 * 1024,
        retries: int = 2,
        retry_delay: float = 0.5,
        fetch: Callable[[str, float, int], bytes] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.retries = max(0, retries)
        self.retry_delay = max(0.0, retry_delay)
        self._fetch = fetch or self._fetch_json
        self._sleep = sleep or time.sleep

    def fetch_appinfo(self, app_id: str) -> SteamAppInfo:
        if not app_id.isdigit():
            raise SteamApiError("Steam App ID 必须是数字")
        details = self._request(
            "https://store.steampowered.com/api/appdetails",
            {"appids": app_id, "l": "english", "cc": "us"},
        )
        envelope = details.get(app_id)
        if not isinstance(envelope, dict) or envelope.get("success") is not True or not isinstance(envelope.get("data"), dict):
            raise SteamApiError(f"Steam 没有返回 App {app_id} 的有效信息")
        data = envelope["data"]
        name = str(data.get("name", "")).strip()
        raw_ids = data.get("dlc", [])
        if not name or not isinstance(raw_ids, list):
            raise SteamApiError("Steam AppDetails 缺少游戏名称或 DLC 列表")
        ordered_ids = [str(value).strip() for value in raw_ids]
        if any(not value.isdigit() for value in ordered_ids) or len(set(ordered_ids)) != len(ordered_ids):
            raise SteamApiError("Steam AppDetails 返回了无效或重复的 DLC ID")
        ordered_ids.sort(key=int)

        catalog = self._request(
            "https://store.steampowered.com/api/dlcforapp/",
            {"appid": app_id, "l": "english", "cc": "us"},
        )
        raw_dlcs = catalog.get("dlc")
        if not isinstance(raw_dlcs, list):
            raise SteamApiError("Steam DLC 接口缺少 dlc 数组")
        names: dict[str, str] = {}
        for index, item in enumerate(raw_dlcs, start=1):
            if not isinstance(item, dict):
                raise SteamApiError(f"Steam 返回的第 {index} 个 DLC 格式不正确")
            dlc_id = str(item.get("id", "")).strip()
            dlc_name = str(item.get("name", "")).strip()
            if not dlc_id.isdigit() or not dlc_name or "\n" in dlc_name or "\r" in dlc_name:
                raise SteamApiError(f"Steam 返回的第 {index} 个 DLC 缺少有效 ID 或名称")
            names[dlc_id] = dlc_name
        missing = [value for value in ordered_ids if value not in names]
        if missing:
            raise SteamApiError(f"Steam DLC 名称接口缺少 {len(missing)} 个条目：{', '.join(missing[:5])}")
        dlcs = tuple(SteamDlc(value, names[value]) for value in ordered_ids)
        return SteamAppInfo(
            app_id=app_id,
            name=name,
            update_time=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            dlcs=dlcs,
        )

    def _request(self, base_url: str, query: dict[str, str]) -> dict[str, object]:
        url = f"{base_url}?{urlencode(query)}"
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                value = json.loads(self._fetch(url, self.timeout, self.max_response_bytes))
                break
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as error:
                last_error = error
                if attempt < self.retries:
                    self._sleep(self.retry_delay * (2 ** attempt))
        else:
            raise SteamApiError(f"Steam API 请求失败（已尝试 {self.retries + 1} 次）：{last_error}") from last_error
        if not isinstance(value, dict):
            raise SteamApiError("Steam API 返回格式不正确")
        return value

    @staticmethod
    def _fetch_json(url: str, timeout: float, limit: int) -> bytes:
        from .net_errors import describe_network_error

        request = Request(url, headers={"Accept": "application/json", "User-Agent": "SignRiver-Publisher/0.1"})
        try:
            with urlopen(request, timeout=timeout) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != "store.steampowered.com":
                    raise SteamApiError("Steam API 重定向到了不受信任的地址")
                data = response.read(limit + 1)
        except (OSError, TimeoutError) as error:
            raise OSError(
                describe_network_error(error, url=url, action="访问 Steam API")
            ) from error
        if len(data) > limit:
            raise SteamApiError("Steam API 响应过大")
        return data
