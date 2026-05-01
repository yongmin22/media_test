import streamlit as st
import os
import sys
import datetime
import json
import tempfile

# [Harness] 경로 엔트로피 제어: scripts 폴더를 찾기 위한 절대 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# scripts 폴더 내의 모듈 임포트 시도 (실패 시 빈 함수로 대체하여 크래시 방지)
try:
    from scripts.sensors.check_block import check_for_blocks
    from scripts.sensors.check_quality import verify_contract
except ImportError:
    # 하네스 가드: 모듈이 없을 경우 자가 치유 로직이 작동하지 않음을 경고
    def check_for_blocks(msg): return None
    def verify_contract(path, mode): return True, "Sensor Missing"

# --- Configuration & Setup ---
BASE_DIR = current_dir
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(os.path.join(DOWNLOADS_DIR, "videos"), exist_ok=True)
os.makedirs(os.path.join(DOWNLOADS_DIR, "music"), exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def log_event(url, mode, event, detail="", output_path=None, error=None):
    today = datetime.datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(LOGS_DIR, f"download_{today}.jsonl")
    log_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "url": url, "mode": mode, "event": event, "detail": detail
    }
    if error: log_data["error"] = error
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data, ensure_ascii=False) + "\n")

def main():
    st.set_page_config(page_title="YouTube Downloader [Harness]", page_icon="🎬", layout="wide")
    st.title("🎬 YouTube Downloader [v2.1 - Cloud Optimized]")
    
    with st.sidebar:
        st.header("⚙️ Harness Control")
        mode = st.radio("모드", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("품질 제한", options=["360p", "720p", "1080p", "최고화질"], value="1080p")
        
        st.write("---")
        # [Harness] User Intervention: Cloud 환경에서는 쿠키 직접 업로드가 유일한 우회로입니다.
        st.subheader("🍪 쿠키 설정 (차단 시)")
        cookie_file = st.file_uploader("cookies.txt 업로드", type=["txt"])
        if cookie_file:
            st.success("쿠키 주입 완료 (서버 브라우저 의존성 해제)")

    url_type = st.radio("소스", ["단일 URL", "재생목록 (Playlist)"])
    url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/...")
    
    if st.button("🚀 실행", type="primary"):
        if not url_input:
            st.warning("URL을 입력하세요.")
            return

        mode_key = "video" if "영상" in mode else "audio"
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        try:
            import yt_dlp
        except ImportError:
            st.error("yt-dlp가 없습니다. requirements.txt를 확인하세요.")
            return

        # --- yt-dlp Options (Harness Integrated) ---
        ydl_opts = {
            'ignoreerrors': True,
            'quiet': True,
            'no_warnings': True,
            # [Fix] 서버 환경에서 크롬 찾지 말라고 명시적으로 꺼버림
            'cookiesfrombrowser': None, 
        }

        # 쿠키 파일이 업로드된 경우 임시 파일로 저장 후 주입
        if cookie_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
                tmp.write(cookie_file.getvalue())
                ydl_opts['cookiefile'] = tmp.name

        today_str = datetime.datetime.now().strftime("%Y%m%d")
        target_dir = os.path.join(DOWNLOADS_DIR, "videos" if mode_key == "video" else "music")
        
        # 네이밍 및 재생목록 규칙 (Contract 준수)
        idx_str = "[%(playlist_index)02d] " if url_type == "재생목록 (Playlist)" else ""
        ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] {idx_str}%(title)s.%(ext)s")
        
        if mode_key == "video":
            h_limit = quality.replace("p", "")
            if h_limit.isdigit():
                ydl_opts['format'] = f'bestvideo[height<={h_limit}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h_limit}]'
            else:
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
            ydl_opts['merge_output_format'] = 'mp4'
        else:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192',
            }, {'key': 'EmbedThumbnail'}, {'key': 'FFmpegMetadata'}]

        # --- Logger Hook ---
        class MyLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg):
                error_type = check_for_blocks(msg)
                if error_type:
                    st.error(f"⚠️ 차단 감지: {error_type}. 쿠키 파일을 업로드해보세요.")
                log_event(url_input, mode_key, "fail", error=msg)

        ydl_opts['logger'] = MyLogger()

        # --- Execute ---
        status_text.info("준비 중...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                status_text.info("다운로드 시작... (대량 작업 시 시간이 걸릴 수 있습니다)")
                ydl.download([url_input])
            
            progress_bar.progress(100)
            status_text.success("작업이 완료되었습니다. downloads/ 폴더를 확인하세요.")
            log_event(url_input, mode_key, "success")
            
        except Exception as e:
            st.error(f"치명적 오류: {e}")
            log_event(url_input, mode_key, "fail", error=str(e))
        finally:
            # 임시 쿠키 파일 삭제
            if 'cookiefile' in ydl_opts and os.path.exists(ydl_opts['cookiefile']):
                os.remove(ydl_opts['cookiefile'])

if __name__ == "__main__":
    main()
