import streamlit as st
import os
import sys
import datetime
import json
import tempfile
import zipfile
import subprocess
import shutil
from io import BytesIO

# [Harness] 경로 및 환경 통제
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from scripts.sensors.check_block import check_for_blocks
except ImportError:
    def check_for_blocks(msg): 
        if "403" in msg or "Forbidden" in msg: return "IP 차단 (403 Forbidden)"
        if "429" in msg: return "요청 과다 (429 Too Many Requests)"
        if "n challenge" in msg: return "암호 해독기(Node.js) 미설치"
        if "PO Token" in msg or "confirm you're not a bot" in msg: return "강력 차단 (PO_TOKEN 필요)"
        return None

# --- Configuration ---
LOGS_DIR = os.path.join(current_dir, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def is_ffmpeg_installed():
    return shutil.which("ffmpeg") is not None

def get_js_runtime():
    """시스템에서 사용 가능한 JS 런타임을 찾습니다."""
    for runtime in ["node", "nodejs", "deno"]:
        if shutil.which(runtime):
            return runtime
    return None

def main():
    st.set_page_config(page_title="YT-Harness v3.3", page_icon="🛡️", layout="wide")
    
    # [Harness] 환경 진단 센서
    is_cloud = "STREAMLIT_SERVER_PORT" in os.environ
    ffmpeg_available = is_ffmpeg_installed()
    js_runtime = get_js_runtime()

    st.title("🛡️ YouTube Downloader [v3.3 - 로컬 최적화]")
    
    # [Harness] 긴급 진단 및 가이드
    if not js_runtime:
        st.error("🚨 **암호 해독기(Node.js)가 없습니다!**")
        st.markdown("""
        현재 유튜브의 n-challenge 암호를 풀 수 있는 도구가 없습니다. 이 상태로는 고화질 다운로드가 막힙니다.
        - **해결책**: [Node.js 공식 홈페이지](https://nodejs.org/)에서 설치 후 프로그램을 재시작하세요.
        - **임시방편**: 아래 '호환성 모드(단일 스트림)'를 체크하면 낮은 화질로라도 받을 수 있습니다.
        """)

    if is_cloud:
        st.warning("⚠️ **Cloud 서버** 모드: IP 차단 위험이 매우 높습니다. 가급적 로컬에서 실행하세요.")
    else:
        st.success("🏠 **로컬 환경** 모드: 형님의 IP를 사용하여 차단 우회에 유리합니다.")

    with st.sidebar:
        st.header("⚙️ 하네스 통제 센터")
        
        c1, c2 = st.columns(2)
        c1.metric("FFmpeg", "OK" if ffmpeg_available else "MISSING")
        c2.metric("JS Runtime", js_runtime if js_runtime else "NONE")
        
        st.write("---")
        # [Harness] 생존 옵션
        use_compat_mode = st.checkbox("호환성 모드 (Node.js 없을 때)", value=not js_runtime)
        
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질 제한", options=["360p", "720p", "1080p", "최고화질"], value="1080p")
        
        st.write("---")
        st.subheader("🔑 1단계: 쿠키 (신분증)")
        cookie_file = st.file_uploader("youtube.com_cookies.txt", type=["txt"])
        
        st.write("---")
        st.subheader("🔐 2단계: 보안 토큰 (심화)")
        po_token = st.text_input("PO_TOKEN")
        visitor_data = st.text_input("Visitor Data")
        
        show_raw_logs = st.checkbox("실시간 디버그 로그", value=True)

    st.subheader("다운로드 실행")
    url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")

    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 데이터 수집 시작", type="primary"):
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

                # [Harness] v3.3 최적화 우회 옵션
                ydl_opts = {
                    'quiet': False, 
                    'no_warnings': False,
                    'progress_hooks': [progress_hook],
                    'nocheckcertificate': True,
                    'ignoreerrors': False,
                    'nopart': True,
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['web', 'mweb', 'tv', 'ios'],
                            'player_skip': ['configs'],
                        }
                    },
                }

                if js_runtime:
                    ydl_opts['javascript_runtime'] = js_runtime

                if po_token:
                    yt_args = ydl_opts['extractor_args']['youtube']
                    yt_args['po_token'] = [f"web+{po_token}", f"mweb+{po_token}"]
                    if visitor_data:
                        yt_args['visitor_data'] = [visitor_data]

                # 포맷 설정 (호환성 모드 및 폴백 강화)
                if mode_key == "video":
                    h = "1080" if quality == "최고화질" else quality.replace("p", "")
                    if use_compat_mode or not js_runtime:
                        # n-challenge 없이도 가능한 단일 파일(best) 요청
                        ydl_opts['format'] = f'best[height<={h}][ext=mp4]/best'
                    elif ffmpeg_available:
                        ydl_opts['format'] = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}]/best'
                        ydl_opts['merge_output_format'] = 'mp4'
                    else:
                        ydl_opts['format'] = f'best[height<={h}][ext=mp4]/best'
                else:
                    ydl_opts['format'] = 'bestaudio/best'
                    if ffmpeg_available:
                        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]

                if cookie_file:
                    cookie_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(cookie_path, "wb") as f: f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = cookie_path

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

                with st.status("🏗️ 신분 확인 및 데이터 수집 중...", expanded=True) as status:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url_input])
                        status.update(label="✅ 프로세스 종료", state="complete")
                    except Exception as download_err:
                        err_msg = str(download_err)
                        block_type = check_for_blocks(err_msg)
                        status.update(label=f"🛑 {block_type if block_type else '실패'}", state="error")
                        st.error(f"상세 원인: {err_msg}")
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
                    st.warning("⚠️ 파일을 찾지 못했습니다. Node.js를 설치하거나 '호환성 모드'를 켜보세요.")

            except Exception:
                pass

    if st.session_state.delivered_files:
        st.write("---")
        st.success(f"📦 {len(st.session_state.delivered_files)}개의 파일이 도착했습니다!")
        
        if len(st.session_state.delivered_files) == 1:
            f = st.session_state.delivered_files[0]
            st.download_button(label=f"💾 {f['name']} 내 컴퓨터로 저장", data=f['data'], file_name=f['name'], use_container_width=True)
        else:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for f in st.session_state.delivered_files: zf.writestr(f['name'], f['data'])
            st.download_button(label="🎁 전체 압축 다운로드", data=zip_buffer.getvalue(), file_name="YT_Harness.zip", use_container_width=True)

if __name__ == "__main__":
    main()
