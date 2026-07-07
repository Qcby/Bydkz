"""
比亚迪车主签到 v1.1.0（mywc网关聚合推送版）

功能：通过自建 mywc 网关获取比亚迪小程序 code，并调用签到服务完成车主签到，支持多账号执行，执行结束后统一聚合推送。

配置说明：
1. 微信 code 网关：
   wx_server_url 或 WX_SERVER_URL                  必填其一，自建授权服务器域名
   - 示例：http://127.0.0.1:8110
   - 脚本会自动拼接 /mywc
   - 请求格式：GET {网关}/mywc?wxid=账号标识&appId=wxa28c31d4ff7ae869
   - 请求头：auth=账号标识
   - # 部署教程：https://hub.docker.com/r/qcby/qcby-vxcode

2. 账号变量：
   byd_wxid 或 BYD_WXID                            推荐，比亚迪车主小程序专属账号变量
   - 多账号支持使用 &、英文逗号、中文逗号或换行分隔
   - 示例：wxid_a&wxid_b 或 wxid_a,wxid_b

3. 业务接口变量：
   BYD_API_SALT                                    必填，签到服务签名盐值，私聊群主获取专属盐值

4. 专属路由变量（可选）：
   BYD_CUSTOM_WEBHOOK                              UID 到企业微信机器人 webhook 的映射
   - 格式：uid1,uid2=>https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
   - 多组使用换行或 | 分隔
   - 未命中专属路由的账号走默认 SendNotify.py 聚合推送

5. 推送变量：
   需要同目录存在 SendNotify.py，脚本结束后会统一调用 send_push_notification。
   常用推送变量如下，配置任意一种即可：
   QYWX_KEY                                        企业微信机器人 key
   PUSH_PLUS_TOKEN                                 PushPlus token
   PUSH_KEY                                        Server 酱 key
   DD_BOT_TOKEN 或 DD_BOT_SECRET                    钉钉机器人 token/secret
   FSKEY                                           飞书机器人 key

6. 青龙任务建议：
   名称：比亚迪车主签到
   命令：python3 byd-sign.py
   定时：每天运行 1 次即可，具体时间自行调整
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlparse

import requests

SCRIPT_TITLE = "比亚迪车主签到"
SCRIPT_VERSION = "v1.1.0"
GLOBAL_NOTIFY_BUFFERS: List[Dict[str, Any]] = []

APP_ID = "wxa28c31d4ff7ae869"
REQUEST_TIMEOUT = 15
BYD_API_URL = (os.getenv("BYD_API_URL") or "http://api.qcby.cc:9991/api/sign").strip()
BYD_API_SALT = (os.getenv("BYD_API_SALT") or "").strip()


def split_multi_value(raw: str, *, keep_url_query: bool = False) -> List[str]:
    if not raw:
        return []
    pattern = r"[\n,，|]+" if keep_url_query else r"[&\n,，]+"
    return [item.strip() for item in re.split(pattern, raw) if item.strip()]


def mask_account(account: str) -> str:
    account = str(account or "未知")
    if len(account) <= 6:
        return account[:1] + "***" + account[-1:] if len(account) > 2 else account
    return f"{account[:4]}***{account[-4:]}"


def safe_json_loads(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def parse_custom_webhook_map(raw: str) -> Dict[str, str]:
    webhook_map: Dict[str, str] = {}
    # 左侧 UID 允许逗号分隔，所以整段配置只能按换行或 | 切分，不能按逗号切分。
    for group in [item.strip() for item in re.split(r"[\n|]+", raw or "") if item.strip()]:
        if "=>" not in group:
            continue
        uid_part, webhook = group.split("=>", 1)
        webhook = webhook.strip()
        if not webhook:
            continue
        for uid in split_multi_value(uid_part):
            webhook_map[str(uid)] = webhook
    return webhook_map


CUSTOM_WEBHOOK_MAP = parse_custom_webhook_map(os.getenv("BYD_CUSTOM_WEBHOOK", ""))


def extract_legacy_gateway_and_accounts() -> tuple[str, List[str]]:
    """兼容旧 LOCAL_CODE_URL：尽量提取 gateway 与 wxid，推荐变量仍为 byd_wxid / BYD_WXID。"""
    raw = os.getenv("LOCAL_CODE_URL", "")
    if not raw:
        return "", []

    gateway = ""
    accounts: List[str] = []
    for item in split_multi_value(raw, keep_url_query=True):
        parsed = urlparse(item)
        if not parsed.scheme or not parsed.netloc:
            continue
        query = parse_qs(parsed.query)
        wxid = str((query.get("wxid") or query.get("openid") or [""])[0]).strip()
        if wxid:
            accounts.append(wxid)
        if not gateway:
            base_path = (parsed.path or "").split("/mywc")[0].split("/login")[0]
            gateway = f"{parsed.scheme}://{parsed.netloc}{base_path}".rstrip("/")
    return gateway, accounts


def get_wx_server_url() -> str:
    gateway = (os.getenv("wx_server_url") or os.getenv("WX_SERVER_URL") or "").strip().rstrip("/")
    if not gateway:
        legacy_gateway, _ = extract_legacy_gateway_and_accounts()
        gateway = legacy_gateway
    if not gateway:
        raise RuntimeError("未配置 wx_server_url 或 WX_SERVER_URL")
    return re.sub(r"/(mywc|login)/?$", "", gateway).rstrip("/")


def get_account_wxids() -> List[str]:
    raw = (os.getenv("byd_wxid") or os.getenv("BYD_WXID") or "").strip()
    accounts = split_multi_value(raw)
    if accounts:
        return accounts

    # 最后兼容旧变量；推荐配置仍只写 byd_wxid / BYD_WXID。
    legacy_raw = (os.getenv("BYD_OPENID") or os.getenv("WXID") or "").strip()
    accounts = split_multi_value(legacy_raw)
    if accounts:
        return accounts

    _, legacy_accounts = extract_legacy_gateway_and_accounts()
    return legacy_accounts


def append_notify_result(**kwargs: Any) -> None:
    GLOBAL_NOTIFY_BUFFERS.append(kwargs)


def get_code(wxid: str, gateway: str) -> str:
    response = requests.get(
        f"{gateway}/mywc",
        params={"wxid": wxid, "appId": APP_ID},
        headers={"auth": wxid, "User-Agent": "Mozilla/5.0 MicroMessenger MiniProgram"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = safe_json_loads(response.text)
    code = str(data.get("code") or data.get("data", {}).get("code") or "").strip()
    if not code:
        match = re.search(r'"code"\s*:\s*"([^"]+)"', response.text)
        code = match.group(1).strip() if match else ""
    if not code:
        raise RuntimeError(f"提取 Code 失败：{response.text[:180]}")
    return code


def call_byd_sign_api(code: str) -> Dict[str, Any]:
    if not BYD_API_SALT:
        raise RuntimeError("未配置 BYD_API_SALT")
    if not BYD_API_URL:
        raise RuntimeError("未配置 BYD_API_URL")

    req_data = {"code": code}
    data_str = json.dumps(req_data, separators=(",", ":"), ensure_ascii=False)
    timestamp = str(int(time.time()))
    sign = get_md5(f"{timestamp}{BYD_API_SALT}{data_str}")
    payload = {"code": code, "timestamp": timestamp, "sign": sign}

    response = requests.post(BYD_API_URL, json=payload, timeout=20)
    response.raise_for_status()
    data = safe_json_loads(response.text)
    if not data:
        raise RuntimeError(f"签到服务返回非 JSON：{response.text[:180]}")
    return data


def get_webhook_by_uid(uid: str) -> str:
    uid = str(uid or "").strip()
    return CUSTOM_WEBHOOK_MAP.get(uid, "default")


def push_custom_webhook(webhook: str, title: str, content: str) -> None:
    payload = {"msgtype": "text", "text": {"content": f"{title}\n\n{content}"}}
    try:
        response = requests.post(webhook, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        data = safe_json_loads(response.text)
        if data.get("errcode") == 0:
            print(f"【推送】专属路由推送成功：{webhook.split('key=')[-1][:6]}...")
        else:
            print(f"【推送】专属路由推送失败：{response.text[:160]}")
    except Exception as exc:
        print(f"【推送】专属路由推送异常：{exc}")


def build_notify_report(buffers: Optional[Iterable[Dict[str, Any]]] = None) -> str:
    items = list(buffers if buffers is not None else GLOBAL_NOTIFY_BUFFERS)
    total = len(items)
    success = sum(1 for item in items if item.get("ok"))
    failed = total - success
    total_gain = sum(int(item.get("integral_gain") or 0) for item in items if item.get("ok"))

    status_map = {
        "signed": ("🎉", "签到成功"),
        "already_signed": ("✅", "今日已签"),
        "blocked": ("🛑", "服务拦截"),
        "config_error": ("⚙️", "配置错误"),
        "failed": ("❌", "执行失败"),
    }

    lines = [
        "==============================",
        f"🕒 执行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"📊 统计数据：成功 {success} / 总计 {total}",
        f"✅ 成功账号：{success} 个",
        f"❌ 失败账号：{failed} 个",
        f"💰 累计积分：+{total_gain}",
        "==============================",
    ]

    for item in items:
        ok = bool(item.get("ok"))
        status_icon, status_text = status_map.get(str(item.get("status") or "failed"), ("ℹ️", str(item.get("status") or "未知")))
        account_icon = "🧑‍💻" if ok else "🧟"
        lines.extend([
            f"{account_icon} 【账号{item.get('index', '-')}】{item.get('account', '未知')}",
            f"{status_icon} 状态：{status_text}",
        ])
        if item.get("nickname") or item.get("uid"):
            lines.append(f"👤 用户：{item.get('nickname', '未知')}（UID: {item.get('uid', '未知')}）")
        if ok:
            lines.extend([
                f"🧮 连签：{item.get('duration_days', 0)} 天",
                f"💰 积分：获得 +{item.get('integral_gain', 0)}，余额 {item.get('total_integral', '未知')}",
            ])
        else:
            lines.append(f"🧨 原因：{item.get('message', '未知错误')}")
        lines.append("------------------------------")

    return "\n".join(lines)


def send_default_notify(title: str, content: str) -> None:
    try:
        from SendNotify import send_push_notification
    except Exception as exc:
        print(f"【推送】导入 SendNotify.py 失败：{exc}")
        return

    try:
        send_push_notification(title, content)
        print("【推送】默认聚合推送已执行。")
    except Exception as exc:
        print(f"【推送】默认聚合推送异常：{exc}")


def dispatch_notify() -> None:
    if not GLOBAL_NOTIFY_BUFFERS:
        return

    if CUSTOM_WEBHOOK_MAP:
        grouped: Dict[str, List[Dict[str, Any]]] = {"default": []}
        for item in GLOBAL_NOTIFY_BUFFERS:
            webhook = get_webhook_by_uid(str(item.get("uid") or ""))
            grouped.setdefault(webhook, []).append(item)

        for webhook, items in grouped.items():
            if not items:
                continue
            content = build_notify_report(items)
            if webhook == "default":
                send_default_notify(f"{SCRIPT_TITLE}签到报告", content)
            else:
                push_custom_webhook(webhook, f"{SCRIPT_TITLE}专属签到报告", content)
        return

    send_default_notify(f"{SCRIPT_TITLE}签到报告", build_notify_report())


def run_account(index: int, wxid: str, gateway: str) -> None:
    result: Dict[str, Any] = {
        "index": index,
        "account": mask_account(wxid),
        "raw_account": wxid,
        "ok": False,
        "status": "failed",
        "nickname": "未知",
        "uid": "未知",
        "duration_days": 0,
        "integral_gain": 0,
        "total_integral": "未知",
        "message": "未执行",
    }

    try:
        print(f"--- 🚀 开始执行账号 [{index}] {mask_account(wxid)} ---")
        code = get_code(wxid, gateway)
        print(f"✅ 取码成功：{code[:8]}...")

        api_json = call_byd_sign_api(code)
        code_status = api_json.get("code")
        data = api_json.get("data") if isinstance(api_json.get("data"), dict) else {}
        uid = str(data.get("uid") or "未知")
        nickname = str(data.get("nickname") or "未知")
        msg = str(api_json.get("msg") or "")

        result.update({"uid": uid, "nickname": nickname})
        if code_status == 200:
            duration_days = int(data.get("duration_days") or 0)
            integral_gain = int(data.get("integral") or 0)
            total_integral = (
                data.get("total_integral")
                or data.get("integral_total")
                or data.get("integral_balance")
                or data.get("balance")
                or data.get("points")
                or "未知"
            )
            is_already = any(word in msg for word in ["已签", "重复", "already"])
            result.update(
                {
                    "ok": True,
                    "status": "already_signed" if is_already else "signed",
                    "duration_days": duration_days,
                    "integral_gain": 0 if is_already else integral_gain,
                    "total_integral": total_integral,
                    "message": msg or "签到成功",
                }
            )
            print(f"👤 用户：{nickname}（UID: {uid}）")
            print(f"✅ 状态：{msg or '签到成功'}")
            print(f"🧮 连签：{duration_days} 天 | 💰 获得：+{result['integral_gain']} | 余额：{total_integral}")
        elif code_status == 403:
            block_message = msg or json.dumps(api_json, ensure_ascii=False)[:180]
            if "请联系群主添加" not in block_message:
                block_message = f"{block_message},请联系群主添加"
            result.update({"status": "blocked", "message": block_message})
            print(f"🛑 服务拦截：{result['message']}")
        else:
            raise RuntimeError(f"签到服务异常：{json.dumps(api_json, ensure_ascii=False)[:200]}")
    except Exception as exc:
        result["message"] = str(exc)
        print(f"❌ 账号[{index}]执行失败：{exc}")
    finally:
        append_notify_result(**result)
        print("")


def main() -> None:
    print(f"====== {SCRIPT_TITLE} {SCRIPT_VERSION} ======")
    try:
        gateway = get_wx_server_url()
        accounts = get_account_wxids()
        if not BYD_API_SALT:
            raise RuntimeError("未配置 BYD_API_SALT")
    except Exception as exc:
        append_notify_result(index=1, account="配置检查", ok=False, status="config_error", message=str(exc))
        print(f"❌ 配置错误：{exc}")
        dispatch_notify()
        return

    if not accounts:
        append_notify_result(index=1, account="未配置账号", ok=False, status="config_error", message="未配置 byd_wxid 或 BYD_WXID")
        print("❌ 未检测到账号配置。")
        dispatch_notify()
        return

    print(f"📌 共检测到 {len(accounts)} 个待执行账号")
    print(f"🌐 Code 网关：{gateway}/mywc")
    print(f"🔗 签到接口：{BYD_API_URL}\n")

    for index, wxid in enumerate(accounts, 1):
        run_account(index, wxid, gateway)
        if index < len(accounts):
            time.sleep(1)

    print("====== 开始执行聚合推送 ======")
    dispatch_notify()


if __name__ == "__main__":
    main()
