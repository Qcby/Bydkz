#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名：SendNotify.py
功能：专为青龙/自建环境设计的 Python 核心通知推送模块，完美桥接 sendNotify.js 常用通知通道
"""

import os
import sys
import html
import requests
import urllib.parse
from functools import wraps

# 禁用未经验证的 HTTPS 请求警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 拦截标准输出以捕获运行结果 ──
class OutputCapture:
    def __init__(self):
        self.stdout_orig = sys.stdout
        self.captured_text = []

    def write(self, text):
        self.stdout_orig.write(text)
        self.captured_text.append(text)

    def flush(self):
        self.stdout_orig.flush()

    def get_content(self):
        return "".join(self.captured_text)


def capture_output(title: str = "脚本运行结果"):
    """
    捕获被装饰函数的所有 print 输出，并在执行结束后统一触发消息推送
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            capture = OutputCapture()
            stdout_bak = sys.stdout
            sys.stdout = capture
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                sys.stdout = stdout_bak
                content = capture.get_content()
                if content.strip():
                    send_push_notification(title, content)
        return wrapper
    return decorator


# ── 核心通知核心逻辑 ──
def send_push_notification(text: str, desp: str) -> None:
    """
    分发通知到各个主流推送通道（完美桥接 JS 版常用环境变量）
    """
    # 增加作者声明，对齐原 JS 版设计
    desp += "\n\n本通知 By：自建 Python 核心通知桥接模块"

    # 根据 SKIP_PUSH_TITLE 变量过滤
    skip_title = os.environ.get("SKIP_PUSH_TITLE", "")
    if skip_title and text in [t.strip() for t in skip_title.split("\n") if t.strip()]:
        print(f"[通知过滤] 标题【{text}】触发 SKIP_PUSH_TITLE，已跳过推送。")
        return

    # 1. Server酱 (PUSH_KEY)
    push_key = os.environ.get("PUSH_KEY")
    if push_key:
        try:
            formatted_desp = desp.replace("\n", "\n\n")
            url = f"https://sctapi.ftqq.com/{push_key}.send" if "SCT" in push_key else f"https://sc.ftqq.com/{push_key}.send"
            res = requests.post(url, data={"text": text, "desp": formatted_desp}, timeout=15, verify=False).json()
            if res.get("errno") == 0 or res.get("code") == 0 or (res.get("data") and res.get("data").get("errno") == 0):
                print("▶ Server酱 发送通知消息成功 🎉")
            else:
                print(f"▶ Server酱 发送通知异常: {res}")
        except Exception as e:
            print(f"▶ Server酱 异常: {e}")

    # 2. Push+ (PUSH_PLUS_TOKEN)
    push_plus_token = os.environ.get("PUSH_PLUS_TOKEN")
    if push_plus_token:
        try:
            html_desp = desp.replace("\n", "<br>")
            payload = {
                "token": push_plus_token,
                "title": text,
                "content": html_desp,
                "topic": os.environ.get("PUSH_PLUS_USER", "")
            }
            res = requests.post("https://www.pushplus.plus/send", json=payload, timeout=15, verify=False).json()
            if res.get("code") == 200:
                print("▶ Push+ 发送通知消息成功 🎉")
            else:
                print(f"▶ Push+ 发送通知异常: {res.get('msg')}")
        except Exception as e:
            print(f"▶ Push+ 异常: {e}")

    # 3. 企业微信机器人 (QYWX_KEY)
    qywx_key = os.environ.get("QYWX_KEY")
    if qywx_key:
        try:
            origin = os.environ.get("QYWX_ORIGIN", "https://qyapi.weixin.qq.com")
            url = f"{origin.rstrip('/')}/cgi-bin/webhook/send?key={qywx_key}"
            payload = {
                "msgtype": "text",
                "text": {"content": f"{text}\n\n{desp}"}
            }
            res = requests.post(url, json=payload, timeout=15, verify=False).json()
            if res.get("errcode") == 0:
                print("▶ 企业微信机器人 发送通知消息成功 🎉")
            else:
                print(f"▶ 企业微信机器人 发送通知异常: {res.get('errmsg')}")
        except Exception as e:
            print(f"▶ 企业微信机器人 异常: {e}")

    # 4. 钉钉机器人 (DD_BOT_TOKEN)
    dd_bot_token = os.environ.get("DD_BOT_TOKEN")
    if dd_bot_token:
        try:
            url = f"https://oapi.dingtalk.com/robot/send?access_token={dd_bot_token}"
            dd_secret = os.environ.get("DD_BOT_SECRET")
            if dd_secret:
                import hmac
                import hashlib
                import base64
                import time
                timestamp = str(round(time.time() * 1000))
                secret_enc = dd_secret.encode('utf-8')
                string_to_sign = f'{timestamp}\n{dd_secret}'
                string_to_sign_enc = string_to_sign.encode('utf-8')
                hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                url += f"&timestamp={timestamp}&sign={sign}"
            
            payload = {
                "msgtype": "text",
                "text": {"content": f"{text}\n\n{desp}"}
            }
            res = requests.post(url, json=payload, timeout=15, verify=False).json()
            if res.get("errcode") == 0:
                print("▶ 钉钉机器人 发送通知消息成功 🎉")
            else:
                print(f"▶ 钉钉机器人 发送通知异常: {res.get('errmsg')}")
        except Exception as e:
            print(f"▶ 钉钉机器人 异常: {e}")

    # 5. 飞书机器人 (FSKEY)
    fskey = os.environ.get("FSKEY")
    if fskey:
        try:
            url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{fskey}"
            payload = {
                "msg_type": "text",
                "content": {"text": f"{text}\n\n{desp}"}
            }
            res = requests.post(url, json=payload, timeout=15, verify=False).json()
            if res.get("StatusCode") == 0 or res.get("status_code") == 0:
                print("▶ 飞书机器人 发送通知消息成功 🎉")
            else:
                print(f"▶ 飞书机器人 发送通知异常: {res}")
        except Exception as e:
            print(f"▶ 飞书机器人 异常: {e}")


if __name__ == "__main__":
    # 单元探活测试
    send_push_notification("SendNotify 探活测试标题", "如果能看到这条消息，说明 Python 通知模块配置完美成功。")