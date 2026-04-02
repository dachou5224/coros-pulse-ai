import os
from stravalib.client import Client

def get_strava_client(client_id, client_secret, refresh_token):
    """获取并刷新 Strava 客户端。"""
    if not refresh_token:
        return None
    client = Client()
    try:
        refresh_response = client.refresh_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token
        )
        client.access_token = refresh_response['access_token']
        return client
    except Exception as e:
        print(f"❌ Strava 授权失败: {e}")
        return None
