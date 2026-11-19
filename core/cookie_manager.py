"""
Cookie Parser & Validator for Facebook authentication in Playwright (fbn style).
Supports:
1. Header / Raw Cookie string (e.g. c_user=1000...; xs=...; datr=...)
2. JSON Array exported from browser extensions (e.g. Cookie-Editor, J2TEAM)
3. Netscape format (tab-separated cookies.txt)
"""

import json
import re
from typing import List, Dict, Optional, Tuple


def parse_facebook_cookies(raw_input: str) -> Tuple[List[Dict[str, str]], Optional[str], Optional[str]]:
    """
    Parse any cookie format into Playwright-compatible cookie dictionaries.
    Returns:
        (playwright_cookies, c_user_id, error_message)
    """
    if not raw_input or not raw_input.strip():
        return [], None, "Chưa cung cấp cookie."

    text = raw_input.strip()
    cookies_list: List[Dict[str, str]] = []

    # 1. Try parsing as JSON Array
    if text.startswith("[") and text.endswith("]"):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    name = item.get("name") or item.get("key")
                    value = item.get("value")
                    domain = item.get("domain") or ".facebook.com"
                    path = item.get("path") or "/"
                    if name and value is not None:
                        cookies_list.append({
                            "name": str(name).strip(),
                            "value": str(value).strip(),
                            "domain": domain if domain.startswith(".") else f".{domain}",
                            "path": path,
                        })
        except Exception:
            pass

    # 2. Try parsing as Netscape format (tab separated lines)
    if not cookies_list and "\t" in text:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain = parts[0]
                path = parts[2]
                name = parts[5]
                value = parts[6]
                cookies_list.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": domain if domain.startswith(".") else f".{domain}",
                    "path": path or "/",
                })

    # 3. Try parsing as Header string (c_user=...; xs=...; ...)
    if not cookies_list:
        # Regex or split by ';'
        pairs = text.split(";")
        for pair in pairs:
            if "=" in pair:
                name, val = pair.split("=", 1)
                name = name.strip()
                val = val.strip().strip('"').strip("'")
                if name:
                    cookies_list.append({
                        "name": name,
                        "value": val,
                        "domain": ".facebook.com",
                        "path": "/",
                    })

    if not cookies_list:
        return [], None, "Không nhận diện được định dạng Cookie. Vui lòng dán chuỗi cookie (c_user=...; xs=...) hoặc JSON từ Cookie-Editor."

    # Look for critical Facebook auth cookies: c_user and xs
    c_user_val = None
    has_xs = False
    for c in cookies_list:
        if c["name"].lower() == "c_user":
            c_user_val = c["value"]
        elif c["name"].lower() == "xs":
            has_xs = True

    if not c_user_val:
        return cookies_list, None, "Cảnh báo: Không tìm thấy cookie 'c_user' trong dữ liệu. Facebook có thể sẽ yêu cầu đăng nhập."
    if not has_xs:
        return cookies_list, c_user_val, "Cảnh báo: Không tìm thấy cookie phiên 'xs'. Phiên đăng nhập có thể không hợp lệ."

    return cookies_list, c_user_val, None
