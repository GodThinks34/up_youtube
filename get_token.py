from google_auth_oauthlib.flow import InstalledAppFlow

# 申请上传权限
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
]

def main():
    # 读取你刚才下载的 JSON
    flow = InstalledAppFlow.from_client_secrets_file(
        'client_secrets.json', SCOPES)
    
    # 这步会弹窗打开浏览器
    creds = flow.run_local_server(port=0)
    
    print("\n" + "="*50)
    print("这就是你要存入 GitHub Secrets 的三把钥匙：")
    print(f"YOUTUBE_CLIENT_ID: {creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET: {creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN: {creds.refresh_token}")
    print("="*50)

if __name__ == "__main__":
    main()