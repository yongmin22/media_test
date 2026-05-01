import streamlit as st
import os
import sys
import datetime
import json
import tempfile
import zipfile
import subprocess
from io import BytesIO

# [Harness] 경로 엔트로피 제어
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 센서 임포트 가드
try:
    from scripts.sensors.check_block import check_for_blocks
except ImportError:
    def check_for_blocks(msg): 
        if "403" in msg or "Forbidden" in msg: return "IP 차단 (403 Forbidden)"
        if "429" in msg: return "요청 과다 (429 Too Many Requests)"
        if "Sign in" in msg: return "신분 인증 필요 (Cookies required)"
        return None

# --- Configuration ---
LOGS_DIR = os.path.join(current_dir, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def is_ffmpeg_installed():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def main():
    st.set_page_config(page_title="YT-Harness Direct", page_icon="🚀", layout="wide")
    st.title("🚀 YouTube Downloader [v2.8 - 정밀 진단 모드]")
    
    ffmpeg_available = is_ffmpeg_installed()
    
    with st.sidebar:
        st.header("⚙️ Harness Control")
        if not ffmpeg_available:
            st.warning("⚠️ FFmpeg 미설치: 720p 제한")
            
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질", options=["360p", "720p", "1080p"], value="1080p")
        
        st.write("---")
        st.subheader("🛡️ 차단 우회 (쿠키 업로드)")
        cookie_file = st.file_uploader("youtube.com_cookies.txt 업로드", type=["txt"])
        
        st.write("---")
        # [Harness] 실시간 로그 확인 옵션
        show_raw_logs = st.checkbox("실시간 디버그 로그 표시", value=True)

    st.subheader("1단계: 수집 대상 설정")
    url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/...")

    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 서버 수집 시작", type="primary"):
        if not url_input:
            st.error("URL을 입력해 주세요.")
            return

        st.session_state.delivered_files = [] 
        mode_key = "video" if "영상" in mode else "audio"
        
        # 로그 수집용 컨테이너
        log_container = st.empty()
        raw_log_data = []

        with tempfile.TemporaryDirectory() as tmp_work_dir:
            try:
                import yt_dlp
                local_downloads = []

                def progress_hook(d):
                    if d['status'] == 'finished':
                        fname = d.get('info_dict').get('filepath', d.get('filename'))
                        local_downloads.append(fname)

                # [Harness] 로그 및 디버깅 옵션 강화
                ydl_opts = {
                    'quiet': False, 
                    'no_warnings': False,
                    'progress_hooks': [progress_hook],
                    'cookiesfrombrowser': None,
                    'nocheckcertificate': True,
                    'ignoreerrors': False,
                    'nopart': True,
                    'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    # [Harness] 클라이언트 다변화 전략: 유튜브의 클라이언트별 차단 로직을 우회
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['web_safari', 'android', 'ios'],
                            'skip': ['dash', 'hls']
                        }
                    },
                    'file_access_retries': 5,
                    'fragment_retries': 10,
                }

                # 포맷 설정
                if mode_key == "video":
                    h = quality.replace("p", "")
                    if ffmpeg_available:
                        ydl_opts['format'] = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best'
                        ydl_opts['merge_output_format'] = 'mp4'
                    else:
                        ydl_opts['format'] = f'best[height<={h}][ext=mp4]/best[ext=mp4]/best'
                else:
                    ydl_opts['format'] = 'bestaudio/best'
                    if ffmpeg_available:
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320',
                        }]

                # 쿠키 처리
                if cookie_file:
                    cookie_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(cookie_path, "wb") as f: f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = cookie_path

                ydl_opts['outtmpl'] = os.path.join(tmp_work_dir, '%(title)s.%(ext)s')

                # [Logger] 실시간 로그 캡처 센서
                class YdlLogger:
                    def debug(self, msg): 
                        raw_log_data.append(f"[DEBUG] {msg}")
                        if show_raw_logs: log_container.code("\n".join(raw_log_data[-10:]))
                    def warning(self, msg): 
                        raw_log_data.append(f"[WARN] {msg}")
                        if show_raw_logs: log_container.code("\n".join(raw_log_data[-10:]))
                    def error(self, msg):
                        raw_log_data.append(f"[ERROR] {msg}")
                        if show_raw_logs: log_container.code("\n".join(raw_log_data[-10:]))
                
                ydl_opts['logger'] = YdlLogger()

                with st.status("🏗️ 유튜브 서버 데이터 수집 중...", expanded=True) as status:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            # 1. 정보 추출 시도
                            info = ydl.extract_info(url_input, download=True)
                        status.update(label="✅ 수집 종료", state="complete")
                    except Exception as download_err:
                        err_msg = str(download_err)
                        block_type = check_for_blocks(err_msg)
                        status.update(label=f"🛑 {block_type if block_type else '오류 발생'}", state="error")
                        st.error(f"상세 원인: {err_msg}")
                        # 로그 창 상단 고정
                        if not show_raw_logs:
                            with st.expander("실행 로그 확인"):
                                st.code("\n".join(raw_log_data))
                        raise download_err

                # 결과물 확인
                if local_downloads:
                    for fpath in local_downloads:
                        if mode_key == "audio" and ffmpeg_available:
                            base = os.path.splitext(fpath)[0]
                            if os.path.exists(base + ".mp3"): fpath = base + ".mp3"
                        
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.session_state.delivered_files.append({
                                    "name": os.path.basename(fpath),
                                    "data": f.read()
                                })
                else:
                    st.warning("⚠️ 파일은 생성되지 않았으나 에러는 발생하지 않았습니다. 로그를 확인해 주세요.")

            except Exception as e:
                pass # 이미 처리됨

    # --- 2단계: 브라우저 배송 ---
    if st.session_state.delivered_files:
        st.write("---")
        st.success(f"📦 총 {len(st.session_state.delivered_files)}개의 파일이 준비되었습니다.")
        
        if len(st.session_state.delivered_files) == 1:
            file_info = st.session_state.delivered_files[0]
            st.download_button(
                label=f"💾 {file_info['name']} 내 컴퓨터로 저장",
                data=file_info['data'],
                file_name=file_info['name'],
                mime="video/mp4" if file_info['name'].endswith(".mp4") else "audio/mpeg",
                use_container_width=True
            )
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for f in st.session_state.delivered_files:
                    zf.writestr(f['name'], f['data'])
            
            st.download_button(
                label=f"🎁 재생목록 전체 압축 다운로드 (.zip)",
                data=zip_buffer.getvalue(),
                file_name=f"YT_Harness_{datetime.datetime.now().strftime('%H%M%S')}.zip",
                mime="application/zip",
                use_container_width=True
            )

if __name__ == "__main__":
    main()
