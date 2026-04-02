import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread.exceptions import APIError
import time

def get_gspread_client(json_key: str):
    """获取 Google Sheets 客户端。"""
    if not json_key:
        return None
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = json.loads(json_key)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ Google Sheets 认证失败: {e}")
        return None

def retry_gspread_call(fn, max_attempts=6):
    """处理 Sheets API 限流 (429) 的指数退避重试。"""
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            err = str(e)
            if "429" in err and attempt < max_attempts - 1:
                wait = min(60, 2**attempt)
                print(f"⏳ Sheets API 限流 (429)，{wait}s 后重试 ({attempt + 1}/{max_attempts})...")
                time.sleep(wait)
                continue
            raise
