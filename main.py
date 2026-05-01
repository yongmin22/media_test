import streamlit as st
import os
import datetime
import json

# --- Configuration & Setup ---
# 단일 파일로 실행 시 현재 디렉토리를 기준으로 폴더를 생성합니다.
BASE_DIR = os.getcwd()
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(os.path.join(DOWNLOADS_DIR, "videos"), exist_ok=True)
os.makedirs(os.path.join(DOWNLOADS_DIR, "music"), exist_ok=True)
os.makedirs(os.path.join(DOWNLOADS_DIR, "quarantine"), exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def log_event(url, mode, event, detail="", output_path=None, error=None):
    today = datetime.datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(LOGS_DIR, f"download_{today}.jsonl")
    
    log_data = {
        "timestamp": datetime.datetime.now().isoformat() + "+09:00",
        "url": url,
        "mode": mode,
        "event": event,
        "detail": detail
    }
    if output_path:
        log_data["output_path"] = output_path
    if error:
        log_data["error"] = error
        
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data, ensure_ascii=False) + "\n")

# --- UI Functions ---
def main():
    st.set_page_config(page_title="YouTube Downloader [Standalone]", page_icon="🎬", layout="wide")
    
    st.title("🎬 YouTube Downloader [Standalone]")
    st.markdown("이 앱은 단일 `main.py` 파일로 구동되며, 외부 스크립트(센서 등) 의존성 없이 독립적으로 실행됩니다. (힐링 프로세스 제거)")
    
    with st.sidebar:
        st.header("설정")
        mode = st.radio("다운로드 모드", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.radio("화질", ["1080p 이하 (기본)", "최고화질"])
        
    url_type = st.radio("다운로드 소스 선택", ["단일 URL", "재생목록 (Playlist) URL"])
    url_input = st.text_input("YouTube URL 입력", placeholder="https://www.youtube.com/...")
    
    if st.button("🚀 다운로드 시작", type="primary"):
        if not url_input:
            st.warning("URL을 입력해주세요.")
            return
            
        mode_key = "video" if "영상" in mode else "audio"
        
        st.write("---")
        st.subheader("진행 상황")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            import yt_dlp
        except ImportError:
            st.error("yt-dlp 모듈이 설치되어 있지 않습니다. `pip install yt-dlp`를 실행하세요.")
            return
            
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        
        # 1. Base Options
        ydl_opts = {
            'ignoreerrors': True,  # 재생목록 오류 발생 시 중단 없이 다음으로 진행
            'quiet': True,
            'no_warnings': True,
        }
        
        # 2. Paths & Naming
        if mode_key == "video":
            target_dir = os.path.join(DOWNLOADS_DIR, "videos")
            if url_type == "재생목록 (Playlist) URL":
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] [%(playlist_index)02d] %(title)s.%(ext)s")
                ydl_opts['yes_playlist'] = True
            else:
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] %(title)s.%(ext)s")
                ydl_opts['noplaylist'] = True
                
            if "1080p" in quality:
                ydl_opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
            else:
                ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            ydl_opts['merge_output_format'] = 'mp4'
            
        else:
            target_dir = os.path.join(DOWNLOADS_DIR, "music")
            if url_type == "재생목록 (Playlist) URL":
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] [%(playlist_index)02d] %(title)s.%(ext)s")
                ydl_opts['yes_playlist'] = True
            else:
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] %(title)s.%(ext)s")
                ydl_opts['noplaylist'] = True
                
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0',
            }, {'key': 'EmbedThumbnail'}, {'key': 'FFmpegMetadata'}]
            ydl_opts['writethumbnail'] = True
            
        # Logging config (custom logger)
        class MyLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg):
                # 힐링(치유) 프로세스는 Streamlit 구동 안정성을 위해 제거하고 에러 로깅만 수행
                if "sign in to confirm you're not a bot" in msg.lower() or "http error 403" in msg.lower():
                    st.toast(f"차단/오류 감지됨 (건너뜀): {msg[:50]}...")
                log_event(url_input, mode_key, "fail", error=msg)
                    
        ydl_opts['logger'] = MyLogger()
        
        finished_items = []
        def my_hook(d):
            if d['status'] == 'finished':
                filename = d['filename']
                st.toast(f"다운로드 완료: {os.path.basename(filename)}")
                finished_items.append(filename)
                log_event(url_input, mode_key, "success", output_path=filename)
                
        ydl_opts['progress_hooks'] = [my_hook]
        
        status_text.info("다운로드를 준비 중입니다...")
        log_event(url_input, mode_key, "start", detail=f"Playlist: {ydl_opts.get('yes_playlist', False)}")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                status_text.info("다운로드 중입니다. 오류가 발생해도 건너뛰고 계속 진행됩니다...")
                ydl.download([url_input])
                
            progress_bar.progress(100)
            status_text.success(f"작업 완료! (완료된 항목: {len(finished_items)}개)")
            
        except Exception as e:
            st.error(f"다운로드 중 치명적인 오류 발생: {e}")
            log_event(url_input, mode_key, "fail", error=str(e))

if __name__ == "__main__":
    main()
