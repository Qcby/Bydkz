#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名：SendNotify.py
功能：为青龙/自建环境提供统一推送模块常用通知通道。
支持：企业微信机器人、Bark、Telegram、Server酱、钉钉、飞书、PushPlus、PushDeer、WxPusher、Gotify、Discord Webhook、SMTP、自定义 Webhook、Qmsg酱、iGot、PushMe、Chanify、ntfy
用法：
    from SendNotify import send_push_notification
    send_push_notification("标题", "正文")

环境变量规范：
1. 多渠道并发推送
   NOTIFY_CHANNELS=wecom_bot,bark,telegram

2. 各渠道主字段与扩展字段
   企业微信机器人：
     WECOM_BOT_WEBHOOK=

   Bark：
     BARK_DEVICE_KEY=
     BARK_SERVER_URL=
     BARK_SOUND=
     BARK_GROUP=
     BARK_ICON=
     BARK_URL=
     BARK_LEVEL=
     BARK_BADGE=
     BARK_SUBTITLE=
     BARK_AUTO_COPY=

   Telegram：
     TG_BOT_TOKEN=
     TG_CHAT_ID=
     TG_TOPIC_ID=
     TG_API_URL=
     TG_PROXY_URL=

   Server酱：
     SERVERCHAN_SENDKEY=
     SERVERCHAN_CHANNEL=
     SERVERCHAN_OPENID=

   钉钉：
     DINGTALK_WEBHOOK=
     DINGTALK_SECRET=
     DINGTALK_AT_ALL=true/false

   飞书：
     FEISHU_WEBHOOK=
     FEISHU_TITLE=

   PushPlus：
     PUSHPLUS_TOKEN=
     PUSHPLUS_TEMPLATE=
     PUSHPLUS_TOPIC=
     PUSHPLUS_CHANNEL=

   PushDeer：
     PUSHDEER_KEY=
     PUSHDEER_SERVER_URL=
     PUSHDEER_TYPE=
     PUSHDEER_DESP=

   WxPusher：
     WXPUSHER_APP_TOKEN=
     WXPUSHER_UIDS=uid_xxx,uid_yyy
     WXPUSHER_TOPIC_IDS=12345,67890
     WXPUSHER_CONTENT_TYPE=text/html/markdown
     WXPUSHER_URL=

   Gotify：
     GOTIFY_TOKEN=
     GOTIFY_SERVER_URL=
     GOTIFY_PRIORITY=

   Discord Webhook：
     DISCORD_WEBHOOK=
     DISCORD_USERNAME=
     DISCORD_AVATAR_URL=

   SMTP：
     SMTP_HOST=
     SMTP_PORT=
     SMTP_USER=
     SMTP_PASS=
     SMTP_FROM=
     SMTP_TO=xxx@qq.com,yyy@163.com
     SMTP_STARTTLS=true/false
     SMTP_SSL=true/false

   自定义 Webhook：
     CUSTOM_WEBHOOK_URL=
     CUSTOM_WEBHOOK_CONTENT_TYPE=application/json/application/x-www-form-urlencoded
     CUSTOM_WEBHOOK_AUTH_HEADER=

   Qmsg酱：
     QMSG_KEY=
     QMSG_QQ=123456,654321
     QMSG_SERVER_URL=
     QMSG_BOT=
     QMSG_IS_GROUP=true/false

   iGot：
     IGOT_KEY=
     IGOT_SERVER_URL=
     IGOT_URL=

   PushMe：
     PUSHME_KEY=
     PUSHME_SERVER_URL=
     PUSHME_TYPE=markdown/text

   Chanify：
     CHANIFY_TOKEN=
     CHANIFY_SERVER_URL=
     CHANIFY_COPY=
     CHANIFY_PRIORITY=1/5/10

   ntfy：
     NTFY_TOPIC=
     NTFY_SERVER_URL=
     NTFY_TOKEN=
     NTFY_PRIORITY=1-5
     NTFY_TAGS=tag1,tag2
     NTFY_CLICK=https://example.com
     NTFY_MARKDOWN=true/false

兼容老变量：
- PUSH_KEY -> Server酱
- QYWX_KEY / QYWX_ORIGIN -> 企业微信机器人
- DD_BOT_TOKEN / DD_BOT_SECRET -> 钉钉
- FSKEY -> 飞书
- PUSH_PLUS_TOKEN / PUSH_PLUS_USER -> PushPlus
- WXPUSHER_TOKEN / WP_APP_TOKEN -> WxPusher
- QMSG_KEY / QMSG_TOKEN -> Qmsg酱
"""

import os
import sys
import json
import time
import html
import hmac
import smtplib
import hashlib
import urllib.parse
from base64 import b64encode
from functools import wraps
from email.mime.text import MIMEText
from email.header import Header
from typing import Callable, Dict, List, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OutputCapture:
    def __init__(self):
        self.stdout_orig = sys.stdout
        self.captured_text: List[str] = []

    def write(self, text):
        self.stdout_orig.write(text)
        self.captured_text.append(text)

    def flush(self):
        self.stdout_orig.flush()

    def get_content(self):
        return "".join(self.captured_text)


def capture_output(title: str = "脚本运行结果"):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            capture = OutputCapture()
            stdout_bak = sys.stdout
            sys.stdout = capture
            try:
                return func(*args, **kwargs)
            finally:
                sys.stdout = stdout_bak
                content = capture.get_content()
                if content.strip():
                    send_push_notification(title, content)
        return wrapper
    return decorator


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_multi(value: str) -> List[str]:
    if not value:
        return []
    text = value.replace("，", ",").replace("&", ",").replace("\n", ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def _post_json(url: str, payload: dict, timeout: int = 15, proxies: Optional[dict] = None):
    return requests.post(url, json=payload, timeout=timeout, verify=False, proxies=proxies)


def _post_form(url: str, data: dict, timeout: int = 15):
    return requests.post(url, data=data, timeout=timeout, verify=False)


def _get_headers(base=None):
    headers = {
        "User-Agent": "Qcby-SendNotify/1.0",
    }
    if base:
        headers.update(base)
    return headers


def _format_plain(text: str, desp: str) -> str:
    return f"{text}\n\n{desp}".strip()


def _format_html(desp: str) -> str:
    return desp.replace("\n", "<br>")


def _notify_wecom_bot(title: str, desp: str):
    webhook = os.environ.get("WECOM_BOT_WEBHOOK") or os.environ.get("QYWX_KEY")
    if not webhook:
        return False
    if webhook and "http" not in webhook:
        origin = os.environ.get("QYWX_ORIGIN", "https://qyapi.weixin.qq.com").rstrip("/")
        webhook = f"{origin}/cgi-bin/webhook/send?key={webhook}"
    payload = {"msgtype": "text", "text": {"content": _format_plain(title, desp)}}
    res = _post_json(webhook, payload).json()
    if res.get("errcode") == 0:
        print("▶ 企业微信机器人 发送通知消息成功 🎉")
        return True
    print(f"▶ 企业微信机器人 发送通知异常: {res}")
    return False


def _notify_bark(title: str, desp: str):
    key = os.environ.get("BARK_DEVICE_KEY")
    if not key:
        return False
    server = (os.environ.get("BARK_SERVER_URL") or "https://api.day.app").rstrip("/")
    payload = {
        "title": title,
        "body": desp,
        "sound": os.environ.get("BARK_SOUND", ""),
        "group": os.environ.get("BARK_GROUP", ""),
        "icon": os.environ.get("BARK_ICON", ""),
        "url": os.environ.get("BARK_URL", ""),
        "level": os.environ.get("BARK_LEVEL", ""),
        "badge": os.environ.get("BARK_BADGE", ""),
        "subtitle": os.environ.get("BARK_SUBTITLE", ""),
        "automaticallyCopy": os.environ.get("BARK_AUTO_COPY", ""),
    }
    payload = {k: v for k, v in payload.items() if str(v).strip() != ""}
    res = _post_json(f"{server}/push", {"device_key": key, **payload}).json()
    if res.get("code") in {200, 0}:
        print("▶ Bark 发送通知消息成功 🎉")
        return True
    print(f"▶ Bark 发送通知异常: {res}")
    return False


def _notify_telegram(title: str, desp: str):
    token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        return False
    api_url = (os.environ.get("TG_API_URL") or "https://api.telegram.org").rstrip("/")
    proxy_url = os.environ.get("TG_PROXY_URL", "").strip()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    text = _format_plain(title, desp)
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    topic_id = os.environ.get("TG_TOPIC_ID", "").strip()
    if topic_id:
        payload["message_thread_id"] = topic_id
    res = _post_json(f"{api_url}/bot{token}/sendMessage", payload, proxies=proxies).json()
    if res.get("ok"):
        print("▶ Telegram 发送通知消息成功 🎉")
        return True
    print(f"▶ Telegram 发送通知异常: {res}")
    return False


def _notify_serverchan(title: str, desp: str):
    sendkey = os.environ.get("SERVERCHAN_SENDKEY") or os.environ.get("PUSH_KEY")
    if not sendkey:
        return False
    url = f"https://sctapi.ftqq.com/{sendkey}.send" if sendkey.startswith("SCT") else f"https://sc.ftqq.com/{sendkey}.send"
    data = {
        "text": title,
        "desp": desp.replace("\n", "\n\n"),
    }
    channel = os.environ.get("SERVERCHAN_CHANNEL", "").strip()
    openid = os.environ.get("SERVERCHAN_OPENID", "").strip()
    if channel:
        data["channel"] = channel
    if openid:
        data["openid"] = openid
    res = _post_form(url, data).json()
    if res.get("errno") == 0 or res.get("code") == 0 or (res.get("data") and res.get("data", {}).get("errno") == 0):
        print("▶ Server酱 发送通知消息成功 🎉")
        return True
    print(f"▶ Server酱 发送通知异常: {res}")
    return False


def _notify_dingtalk(title: str, desp: str):
    webhook = os.environ.get("DINGTALK_WEBHOOK")
    if not webhook:
        token = os.environ.get("DD_BOT_TOKEN")
        if token:
            webhook = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
    if not webhook:
        return False
    secret = os.environ.get("DINGTALK_SECRET") or os.environ.get("DD_BOT_SECRET")
    if secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        sign = urllib.parse.quote_plus(b64encode(hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=hashlib.sha256).digest()))
        joiner = "&" if "?" in webhook else "?"
        webhook = f"{webhook}{joiner}timestamp={timestamp}&sign={sign}"
    payload = {
        "msgtype": "text",
        "text": {"content": _format_plain(title, desp)},
        "at": {"isAtAll": _truthy(os.environ.get("DINGTALK_AT_ALL"))},
    }
    res = _post_json(webhook, payload).json()
    if res.get("errcode") == 0:
        print("▶ 钉钉机器人 发送通知消息成功 🎉")
        return True
    print(f"▶ 钉钉机器人 发送通知异常: {res}")
    return False


def _notify_feishu(title: str, desp: str):
    webhook = os.environ.get("FEISHU_WEBHOOK")
    if not webhook:
        fskey = os.environ.get("FSKEY")
        if fskey:
            webhook = f"https://open.feishu.cn/open-apis/bot/v2/hook/{fskey}"
    if not webhook:
        return False
    msg_title = os.environ.get("FEISHU_TITLE") or title
    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": msg_title,
                    "content": [
                        [{"tag": "text", "text": desp}]
                    ]
                }
            }
        }
    }
    res = _post_json(webhook, payload).json()
    if res.get("StatusCode") == 0 or res.get("status_code") == 0 or res.get("code") == 0:
        print("▶ 飞书机器人 发送通知消息成功 🎉")
        return True
    print(f"▶ 飞书机器人 发送通知异常: {res}")
    return False


def _notify_pushplus(title: str, desp: str):
    token = os.environ.get("PUSHPLUS_TOKEN") or os.environ.get("PUSH_PLUS_TOKEN")
    if not token:
        return False
    payload = {
        "token": token,
        "title": title,
        "content": _format_html(desp),
        "template": os.environ.get("PUSHPLUS_TEMPLATE", "html"),
        "topic": os.environ.get("PUSHPLUS_TOPIC") or os.environ.get("PUSH_PLUS_USER", ""),
        "channel": os.environ.get("PUSHPLUS_CHANNEL", ""),
    }
    payload = {k: v for k, v in payload.items() if str(v).strip() != ""}
    res = _post_json("https://www.pushplus.plus/send", payload).json()
    if res.get("code") == 200:
        print("▶ PushPlus 发送通知消息成功 🎉")
        return True
    print(f"▶ PushPlus 发送通知异常: {res}")
    return False


def _notify_pushdeer(title: str, desp: str):
    key = os.environ.get("PUSHDEER_KEY")
    if not key:
        return False
    server = (os.environ.get("PUSHDEER_SERVER_URL") or "https://api2.pushdeer.com").rstrip("/")
    payload = {
        "pushkey": key,
        "text": title,
        "desp": desp if _truthy(os.environ.get("PUSHDEER_DESP", "true")) else "",
        "type": os.environ.get("PUSHDEER_TYPE", "markdown")
    }
    res = _post_form(f"{server}/message/push", payload).json()
    if res.get("code") == 0:
        print("▶ PushDeer 发送通知消息成功 🎉")
        return True
    print(f"▶ PushDeer 发送通知异常: {res}")
    return False


def _notify_wxpusher(title: str, desp: str):
    app_token = os.environ.get("WXPUSHER_APP_TOKEN") or os.environ.get("WXPUSHER_TOKEN") or os.environ.get("WP_APP_TOKEN")
    if not app_token:
        return False
    uids = _split_multi(os.environ.get("WXPUSHER_UIDS", ""))
    topic_ids = []
    for item in _split_multi(os.environ.get("WXPUSHER_TOPIC_IDS", "")):
        try:
            topic_ids.append(int(str(item).strip()))
        except Exception:
            continue
    if not uids and not topic_ids:
        print("▶ WxPusher 缺少 UIDs 或 Topic IDs，已跳过")
        return False

    content_type_map = {
        "text": 1,
        "html": 2,
        "markdown": 3,
    }
    raw_type = str(os.environ.get("WXPUSHER_CONTENT_TYPE", "markdown") or "markdown").strip().lower()
    content_type = content_type_map.get(raw_type, 3)
    content = desp if content_type != 1 else _format_plain(title, desp)
    if content_type in {2, 3}:
        content = (f"# {title}\n\n{desp}" if content_type == 3 else f"<h3>{html.escape(title)}</h3><div>{_format_html(html.escape(desp))}</div>")

    payload = {
        "appToken": app_token,
        "content": content,
        "summary": title,
        "contentType": content_type,
    }
    if uids:
        payload["uids"] = uids
    if topic_ids:
        payload["topicIds"] = topic_ids
    url = os.environ.get("WXPUSHER_URL", "").strip()
    if url:
        payload["url"] = url

    res = _post_json("https://wxpusher.zjiecode.com/api/send/message", payload).json()
    if res.get("code") == 1000 or res.get("success") is True:
        print("▶ WxPusher 发送通知消息成功 🎉")
        return True
    print(f"▶ WxPusher 发送通知异常: {res}")
    return False


def _notify_gotify(title: str, desp: str):
    token = os.environ.get("GOTIFY_TOKEN")
    if not token:
        return False
    server = (os.environ.get("GOTIFY_SERVER_URL") or "").rstrip("/")
    if not server:
        print("▶ Gotify 发送通知异常: 缺少 GOTIFY_SERVER_URL")
        return False
    headers = _get_headers({"X-Gotify-Key": token})
    payload = {
        "title": title,
        "message": desp,
        "priority": int(os.environ.get("GOTIFY_PRIORITY", "5") or 5)
    }
    res = requests.post(f"{server}/message", json=payload, headers=headers, timeout=15, verify=False).json()
    if res.get("id"):
        print("▶ Gotify 发送通知消息成功 🎉")
        return True
    print(f"▶ Gotify 发送通知异常: {res}")
    return False


def _notify_discord(title: str, desp: str):
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if not webhook:
        return False
    payload = {
        "content": _format_plain(title, desp),
        "username": os.environ.get("DISCORD_USERNAME", "").strip(),
        "avatar_url": os.environ.get("DISCORD_AVATAR_URL", "").strip(),
    }
    payload = {k: v for k, v in payload.items() if str(v).strip() != ""}
    res = requests.post(webhook, json=payload, headers=_get_headers(), timeout=15, verify=False)
    if res.ok:
        print("▶ Discord Webhook 发送通知消息成功 🎉")
        return True
    print(f"▶ Discord Webhook 发送通知异常: {res.status_code} {res.text}")
    return False


def _notify_smtp(title: str, desp: str):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "465") or 465)
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    sender = os.environ.get("SMTP_FROM") or user
    recipients = _split_multi(os.environ.get("SMTP_TO", ""))
    if not all([host, user, password, sender]) or not recipients:
        return False
    msg = MIMEText(desp, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    try:
        if _truthy(os.environ.get("SMTP_SSL", "true")):
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            if _truthy(os.environ.get("SMTP_STARTTLS", "false")):
                server.starttls()
        server.login(user, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        print("▶ SMTP 邮件 发送通知消息成功 🎉")
        return True
    except Exception as e:
        print(f"▶ SMTP 邮件 异常: {e}")
        return False


def _notify_custom_webhook(title: str, desp: str):
    url = os.environ.get("CUSTOM_WEBHOOK_URL")
    if not url:
        return False
    content_type = (os.environ.get("CUSTOM_WEBHOOK_CONTENT_TYPE") or "application/json").strip()
    auth_header = os.environ.get("CUSTOM_WEBHOOK_AUTH_HEADER", "").strip()
    headers = _get_headers({"Content-Type": content_type})
    if auth_header:
        headers["Authorization"] = auth_header

    if content_type == "application/x-www-form-urlencoded":
        data = {
            "title": title,
            "content": desp,
            "source": "Qcby-SendNotify",
        }
        res = requests.post(url, data=data, headers=headers, timeout=15, verify=False)
    else:
        payload = {
            "title": title,
            "content": desp,
            "source": "Qcby-SendNotify",
        }
        res = requests.post(url, json=payload, headers=headers, timeout=15, verify=False)

    if res.ok:
        print("▶ 自定义 Webhook 发送通知消息成功 🎉")
        return True
    print(f"▶ 自定义 Webhook 发送通知异常: {res.status_code} {res.text}")
    return False


def _notify_qmsg(title: str, desp: str):
    key = os.environ.get("QMSG_KEY") or os.environ.get("QMSG_TOKEN")
    if not key:
        return False
    server = (os.environ.get("QMSG_SERVER_URL") or "https://qmsg.zendee.cn").rstrip("/")
    payload = {
        "msg": _format_plain(title, desp),
        "qq": os.environ.get("QMSG_QQ", "").strip(),
        "bot": os.environ.get("QMSG_BOT", "").strip(),
    }
    is_group = os.environ.get("QMSG_IS_GROUP", "").strip()
    if is_group:
        payload["isGroup"] = "true" if _truthy(is_group) else "false"
    payload = {k: v for k, v in payload.items() if str(v).strip() != ""}
    res = _post_form(f"{server}/send/{key}", payload)
    try:
        data = res.json()
    except Exception:
        data = {"raw": res.text, "status_code": res.status_code}
    if res.ok and (data.get("code") in {0, 200} or data.get("success") is True or data.get("reason") == "success"):
        print("▶ Qmsg酱 发送通知消息成功 🎉")
        return True
    print(f"▶ Qmsg酱 发送通知异常: {data}")
    return False


def _notify_igot(title: str, desp: str):
    key = os.environ.get("IGOT_KEY")
    if not key:
        return False
    server = (os.environ.get("IGOT_SERVER_URL") or "https://push.hellyw.com").rstrip("/")
    payload = {
        "title": title,
        "content": desp,
        "url": os.environ.get("IGOT_URL", "")
    }
    payload = {k: v for k, v in payload.items() if str(v).strip() != ""}
    res = _post_json(f"{server}/{key}", payload).json()
    if res.get("ret") == 0 or res.get("code") == 0:
        print("▶ iGot 发送通知消息成功 🎉")
        return True
    print(f"▶ iGot 发送通知异常: {res}")
    return False


def _notify_pushme(title: str, desp: str):
    key = os.environ.get("PUSHME_KEY")
    if not key:
        return False
    server = (os.environ.get("PUSHME_SERVER_URL") or "https://push.i-i.me").rstrip("/")
    payload = {
        "push_key": key,
        "title": title,
        "content": desp,
        "type": os.environ.get("PUSHME_TYPE", "markdown")
    }
    res = _post_form(f"{server}/push", payload).json()
    if res.get("code") == 0 or res.get("ok") is True:
        print("▶ PushMe 发送通知消息成功 🎉")
        return True
    print(f"▶ PushMe 发送通知异常: {res}")
    return False


def _notify_chanify(title: str, desp: str):
    token = os.environ.get("CHANIFY_TOKEN")
    if not token:
        return False
    server = (os.environ.get("CHANIFY_SERVER_URL") or "https://api.chanify.net").rstrip("/")
    payload = {
        "title": title,
        "text": desp,
        "copy": os.environ.get("CHANIFY_COPY", ""),
        "priority": os.environ.get("CHANIFY_PRIORITY", "1")
    }
    payload = {k: v for k, v in payload.items() if str(v).strip() != ""}
    res = _post_json(f"{server}/v1/sender/{token}", payload).json()
    if res.get("res") == 0 or res.get("message") == "success":
        print("▶ Chanify 发送通知消息成功 🎉")
        return True
    print(f"▶ Chanify 发送通知异常: {res}")
    return False


def _notify_ntfy(title: str, desp: str):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    server = (os.environ.get("NTFY_SERVER_URL") or "https://ntfy.sh").rstrip("/")
    headers = _get_headers({"Title": title})
    token = os.environ.get("NTFY_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    priority = os.environ.get("NTFY_PRIORITY", "").strip()
    tags = os.environ.get("NTFY_TAGS", "").strip()
    click = os.environ.get("NTFY_CLICK", "").strip()
    markdown = os.environ.get("NTFY_MARKDOWN", "").strip()
    if priority:
        headers["Priority"] = priority
    if tags:
        headers["Tags"] = tags
    if click:
        headers["Click"] = click
    if markdown:
        headers["Markdown"] = markdown
    res = requests.post(f"{server}/{topic}", data=desp.encode("utf-8"), headers=headers, timeout=15, verify=False)
    if res.ok:
        print("▶ ntfy 发送通知消息成功 🎉")
        return True
    print(f"▶ ntfy 发送通知异常: {res.status_code} {res.text}")
    return False


CHANNEL_DISPATCH: Dict[str, Callable[[str, str], bool]] = {
    "wecom_bot": _notify_wecom_bot,
    "bark": _notify_bark,
    "telegram": _notify_telegram,
    "serverchan": _notify_serverchan,
    "dingtalk": _notify_dingtalk,
    "feishu": _notify_feishu,
    "pushplus": _notify_pushplus,
    "pushdeer": _notify_pushdeer,
    "wxpusher": _notify_wxpusher,
    "gotify": _notify_gotify,
    "discord": _notify_discord,
    "smtp": _notify_smtp,
    "custom_webhook": _notify_custom_webhook,
    "qmsg": _notify_qmsg,
    "igot": _notify_igot,
    "pushme": _notify_pushme,
    "chanify": _notify_chanify,
    "ntfy": _notify_ntfy,
}


def _detect_default_channels() -> List[str]:
    checks = {
        "wecom_bot": lambda: bool(os.environ.get("WECOM_BOT_WEBHOOK") or os.environ.get("QYWX_KEY")),
        "bark": lambda: bool(os.environ.get("BARK_DEVICE_KEY")),
        "telegram": lambda: bool(os.environ.get("TG_BOT_TOKEN") and os.environ.get("TG_CHAT_ID")),
        "serverchan": lambda: bool(os.environ.get("SERVERCHAN_SENDKEY") or os.environ.get("PUSH_KEY")),
        "dingtalk": lambda: bool(os.environ.get("DINGTALK_WEBHOOK") or os.environ.get("DD_BOT_TOKEN")),
        "feishu": lambda: bool(os.environ.get("FEISHU_WEBHOOK") or os.environ.get("FSKEY")),
        "pushplus": lambda: bool(os.environ.get("PUSHPLUS_TOKEN") or os.environ.get("PUSH_PLUS_TOKEN")),
        "pushdeer": lambda: bool(os.environ.get("PUSHDEER_KEY")),
        "wxpusher": lambda: bool((os.environ.get("WXPUSHER_APP_TOKEN") or os.environ.get("WXPUSHER_TOKEN") or os.environ.get("WP_APP_TOKEN")) and (os.environ.get("WXPUSHER_UIDS") or os.environ.get("WXPUSHER_TOPIC_IDS"))),
        "gotify": lambda: bool(os.environ.get("GOTIFY_TOKEN") and os.environ.get("GOTIFY_SERVER_URL")),
        "discord": lambda: bool(os.environ.get("DISCORD_WEBHOOK")),
        "smtp": lambda: bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS") and os.environ.get("SMTP_TO")),
        "custom_webhook": lambda: bool(os.environ.get("CUSTOM_WEBHOOK_URL")),
        "qmsg": lambda: bool(os.environ.get("QMSG_KEY") or os.environ.get("QMSG_TOKEN")),
        "igot": lambda: bool(os.environ.get("IGOT_KEY")),
        "pushme": lambda: bool(os.environ.get("PUSHME_KEY")),
        "chanify": lambda: bool(os.environ.get("CHANIFY_TOKEN")),
        "ntfy": lambda: bool(os.environ.get("NTFY_TOPIC")),
    }
    enabled = []
    for channel, checker in checks.items():
        try:
            if checker():
                enabled.append(channel)
        except Exception:
            continue
    return enabled


def send_push_notification(text: str, desp: str) -> None:
    desp = (desp or "").strip() + "\n\n本通知 By：Qcby Python 聚合通知模块"
    skip_title = os.environ.get("SKIP_PUSH_TITLE", "")
    if skip_title and text in [t.strip() for t in skip_title.split("\n") if t.strip()]:
        print(f"[通知过滤] 标题【{text}】触发 SKIP_PUSH_TITLE，已跳过推送。")
        return

    channel_list = _split_multi(os.environ.get("NOTIFY_CHANNELS", "")) or _detect_default_channels()
    if not channel_list:
        print("▶ 未检测到任何可用通知渠道，已跳过推送")
        return

    ok_count = 0
    for channel in channel_list:
        channel = channel.strip().lower()
        handler = CHANNEL_DISPATCH.get(channel)
        if not handler:
            print(f"▶ 未识别的通知渠道: {channel}")
            continue
        try:
            if handler(text, desp):
                ok_count += 1
        except Exception as e:
            print(f"▶ 渠道 {channel} 异常: {e}")

    print(f"▶ 通知分发完成：成功 {ok_count} / 总计 {len(channel_list)}")


if __name__ == "__main__":
    send_push_notification("SendNotify 探活测试标题", "如果能看到这条消息，说明 Python 通知模块配置完美成功。")
