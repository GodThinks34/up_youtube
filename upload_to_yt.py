import os
import re
import requests
import googleapiclient.discovery
import googleapiclient.http
from google.oauth2.credentials import Credentials
from urllib.parse import unquote, urlparse
from datetime import datetime, timedelta, timezone

def upload_or_sync():
    # 1. 获取基础配置
    client_id = os.environ.get('YOUTUBE_CLIENT_ID')
    client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET')
    video_url = os.environ.get('VIDEO_URL') 

    if not video_url:
        print("❌ 错误: 环境变量中找不到 VIDEO_URL")
        return

    parsed_url = urlparse(video_url)
    path_without_ext = parsed_url.path.rsplit('.', 1)[0]
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{path_without_ext}"
    
    # 初始化参数默认值
    target_channel_tags = ['C'] 
    privacy_status = 'private'   
    video_title = unquote(os.path.basename(base_url))
    description = ""
    
    is_chinese = bool(re.search(r'[\u4e00-\u9fa5]', video_title))
    detected_lang = 'zh-CN' if is_chinese else 'en'

    # ==================== 新增：计算 5 天后的发布时间 ====================
    # YouTube API 严格要求 ISO 8601 格式的 UTC 时间
    publish_time = datetime.now(timezone.utc) + timedelta(days=5)
    publish_at_str = publish_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    # ====================================================================

    # 2. 三行文本解析逻辑
    try:
        txt_res = requests.get(base_url + ".txt", timeout=10)
        if txt_res.status_code == 200:
            content = txt_res.content.decode('utf-8').strip()
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            
            if len(lines) >= 1:
                rule_line = lines[0]
                ch_match = re.search(r'CH:\s*([\w,]+)', rule_line)
                if ch_match: target_channel_tags = ch_match.group(1).split(',')
                
                priv_match = re.search(r'PRIV:\s*(\w+)', rule_line)
                if priv_match: privacy_status = priv_match.group(1)
                
                lang_match = re.search(r'LANG:\s*([\w-]+)', rule_line)
                if lang_match: detected_lang = lang_match.group(1)

            if len(lines) >= 2: video_title = lines[1]
            if len(lines) >= 3: description = "\n".join(lines[2:])
            
            print(f"🎯 解析指令成功: 频道={target_channel_tags}, 隐私={privacy_status}, 语言={detected_lang}")
    except Exception as e:
        print(f"⚠️ 读取 .txt 失败，将使用默认配置")

    # 3. 矩阵发布逻辑
    for tag in target_channel_tags:
        print(f"\n📺 >>> 正在处理频道 {tag} <<<")
        
        secret_name = 'YOUTUBE_REFRESH_TOKEN' if tag == 'A' else f'YOUTUBE_REFRESH_TOKEN_{tag}'
        refresh_token = os.environ.get(secret_name)
        
        if not refresh_token:
            print(f"❌ 错误: 找不到 {secret_name}，跳过该频道")
            continue

        creds = Credentials(
            token=None, refresh_token=refresh_token, 
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id, client_secret=client_secret
        )
        youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)

        video_id = None
        temp_video = f"video_temp_{tag}.mp4"
        print(f"📥 正在流式下载并校验视频资源...")
        
        try:
            # ==================== 新增：极其严格的下载与文件校验 ====================
            with requests.get(video_url, stream=True, timeout=20) as r:
                # 第一道防线：如果 URL 返回的不是 200 OK (比如 404 找不到文件)，直接抛出异常，阻止下载！
                r.raise_for_status() 
                with open(temp_video, 'wb') as f:
                    for chunk in r.iter_content(8192): f.write(chunk)
            
            # 第二道防线：检查下载下来的文件是否存在，并且体积是否大于 100KB
            # (防止 Cloudflare 拦截返回了一个只有几 KB 的 HTML 验证码页面)
            if not os.path.exists(temp_video) or os.path.getsize(temp_video) < 100 * 1024:
                print("🚨 致命拦截：下载的文件为空或不是真实的视频文件！")
                print("⛔ 已中止 YouTube API 调用，保护账号安全。")
                continue # 停止当前频道的操作，跳到下一个或者结束
            # ====================================================================

            # ==================== 设定 YouTube 请求体 ====================
            request_body = {
                'snippet': { 
                    'title': video_title, 
                    'description': description, 
                    'categoryId': '28', 
                    'defaultLanguage': detected_lang,
                    'defaultAudioLanguage': detected_lang  
                },
                'status': { 
                    'privacyStatus': privacy_status, 
                    'selfDeclaredMadeForKids': False 
                }
            }

            # 核心：只有当状态是 private 时，YouTube 才能接受 publishAt 参数（定时发布）
            if privacy_status == 'private':
                request_body['status']['publishAt'] = publish_at_str
                print(f"⏱️ 视频已设置为定时发布: 预计 UTC 时间 {publish_at_str} 上线")
            # =============================================================

            print("🚀 安全校验通过，正在通过接口提交视频到 YouTube...")
            media = googleapiclient.http.MediaFileUpload(temp_video, chunksize=-1, resumable=True)
            response = youtube.videos().insert(part="snippet,status", body=request_body, media_body=media).execute()
            video_id = response['id']
            print(f"🎉 上传成功 ID: {video_id}")

        except requests.exceptions.HTTPError as http_err:
            print(f"🚨 下载被拒：目标 URL 返回了错误状态码 (可能文件不存在) {http_err}")
            print("⛔ 未调用 YouTube API。")
        except Exception as upload_e:
            print(f"❌ 处理过程中发生异常: {upload_e}")
        finally:
            # 不管成功还是失败，最后一定要清理战场，防止撑爆 GitHub 的硬盘
            if os.path.exists(temp_video): 
                os.remove(temp_video)

        # 5. 封面图智能同步逻辑 (未做修改)
        if video_id:
            extensions = [".jpg", ".jpeg", ".png", ".JPG", ".PNG", ".webp"]
            for ext in extensions:
                thumb_res = requests.get(base_url + ext)
                if thumb_res.status_code == 200:
                    temp_thumb = f"thumb_temp_{tag}{ext}"
                    with open(temp_thumb, 'wb') as f: f.write(thumb_res.content)
                    try:
                        youtube.thumbnails().set(
                            videoId=video_id, 
                            media_body=googleapiclient.http.MediaFileUpload(temp_thumb)
                        ).execute()
                        print(f"✅ 封面图已同步 ({ext})")
                    except Exception as thumb_e:
                        print(f"⚠️ 封面图上传失败: {thumb_e}")
                    finally:
                        if os.path.exists(temp_thumb): os.remove(temp_thumb)
                    break

        print("ℹ️ 字幕同步已关闭，跳过字幕处理步骤。")

if __name__ == "__main__":
    upload_or_sync()
