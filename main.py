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
        if "n challenge" in msg: return "JS 런타임 부재 (Challenge solver missing)"
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
    st.title("🚀 YouTube Downloader [v2.9 - n-Challenge 대응]")
    
    ffmpeg_available = is_ffmpeg_installed()
    
    with st.sidebar:
        st.header("⚙️ Harness Control")
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질", options=["360p", "720p", "1080p"], value="1080p")
        
        st.write("---")
        st.subheader("🛡️ 1단계: 쿠키 업로드")
        cookie_file = st.file_uploader("youtube.com_cookies.txt", type=["txt"])
        
        st.write("---")
        # [Harness] 최신 차단 대응: PO_TOKEN 주입 (Human-in-the-loop)
        st.subheader("🔑 2단계: PO_TOKEN (강력 차단 시)")
        st.caption("유튜브가 '봇 확인'을 요구할 때 사용")
        po_token = st.text_input("PO_TOKEN", placeholder="추출된 토큰 입력")
        visitor_data = st.text_input("Visitor Data", placeholder="추출된 데이터 입력")
        
        st.write("---")
        show_raw_logs = st.checkbox("실시간 디버그 로그 표시", value=True)

    st.subheader("다운로드 실행")
    url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/...")

    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 서버 수집 시작", type="primary"):
        if not url_input:
            st.error("URL을 입력해 주세요.")
            return

        st.session_state.delivered_files = [] 
        mode_key = "video" if "영상" in mode else "audio"
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

                # [Harness] n-Challenge 및 PO_TOKEN 대응 옵션
                ydl_opts = {
                    'quiet': False, 
                    'no_warnings': False,
                    'progress_hooks': [progress_hook],
                    'cookiesfrombrowser': None,
                    'nocheckcertificate': True,
                    'ignoreerrors': False,
                    'nopart': True,
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                    # [Harness] 클라이언트 우선순위 재조정 (n-challenge 우회용)
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['web_creator', 'mweb', 'ios'],
                            'player_skip': ['webpage', 'configs'],
                        }
                    },
                }

                # PO_TOKEN 주입 (입력된 경우)
                if po_token and visitor_data:
                    ydl_opts['extractor_args']['youtube']['po_token'] = [f"web+{po_token}"]
                    ydl_opts['extractor_args']['youtube']['visitor_data'] = [visitor_data]
                    st.toast("🔑 PO_TOKEN 적용됨")

                # 포맷 설정 (n-challenge 실패 시를 대비한 유연한 선택)
                if mode_key == "video":
                    h = quality.replace("p", "")
                    if ffmpeg_available:
                        # 1순위: 고화질 병합, 2순위: 단일 파일(fallback)
                        ydl_opts['format'] = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best'
                        ydl_opts['merge_output_format'] = 'mp4'
                    else:
                        ydl_opts['format'] = f'best[height<={h}][ext=mp4]/best'
                else:
                    ydl_opts['format'] = 'bestaudio/best'
                    if ffmpeg_available:
                        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]

                if cookie_file:
                    c_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(c_path, "wb") as f: f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = c_path

                ydl_opts['outtmpl'] = os.path.join(tmp_work_dir, '%(title)s.%(ext)s')

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

                with st.status("🏗️ 수집 시도 중...", expanded=True) as status:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url_input])
                        status.update(label="✅ 프로세스 종료", state="complete")
                    except Exception as download_err:
                        err_msg = str(download_err)
                        block_type = check_for_blocks(err_msg)
                        status.update(label=f"🛑 {block_type if block_type else '실패'}", state="error")
                        st.error(f"원인: {err_msg}")
                        raise download_err

                if local_downloads:
                    for fpath in local_downloads:
                        if mode_key == "audio" and ffmpeg_available:
                            base = os.path.splitext(fpath)[0]
                            if os.path.exists(base + ".mp3"): fpath = base + ".mp3"
                        
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.session_state.delivered_files.append({"name": os.path.basename(fpath), "data": f.read()})
                else:
                    st.warning("⚠️ 파일이 생성되지 않았습니다. 로그를 확인하세요.")

            except Exception:
                pass

    # --- 2단계: 배송 ---
    if st.session_state.delivered_files:
        st.write("---")
        st.success(f"📦 {len(st.session_state.delivered_files)}개의 파일 준비 완료")
        
        if len(st.session_state.delivered_files) == 1:
            f = st.session_state.delivered_files[0]
            st.download_button(label=f"💾 {f['name']} 저장", data=f['data'], file_name=f['name'], use_container_width=True)
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for f in st.session_state.delivered_files: zf.writestr(f['name'], f['data'])
            st.download_button(label="🎁 전체 압축 다운로드", data=zip_buffer.getvalue(), file_name="YT_Download.zip", use_container_width=True)

if __name__ == "__main__":
    main()
