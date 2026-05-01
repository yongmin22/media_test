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
        if "cookies are no longer valid" in msg: return "쿠키 만료 (Invalid Cookies)"
        if "403" in msg or "Forbidden" in msg: return "IP 차단 (403 Forbidden)"
        if "429" in msg: return "요청 과다 (429 Too Many Requests)"
        if "n challenge" in msg: return "암호 해독기(Node.js) 미설치/인식오류"
        if "PO Token" in msg or "confirm you're not a bot" in msg: return "봇 확인 필요 (PO_TOKEN)"
        return None

# --- Configuration ---
LOGS_DIR = os.path.join(current_dir, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def is_ffmpeg_installed():
    return shutil.which("ffmpeg") is not None

def get_js_runtime():
    for runtime in ["node", "nodejs", "deno"]:
        if shutil.which(runtime):
            return runtime
    return None

def main():
    st.set_page_config(page_title="YT-Harness v3.4", page_icon="🛡️", layout="wide")
    
    # [Harness] 환경 진단 센서
    is_cloud = "STREAMLIT_SERVER_PORT" in os.environ
    ffmpeg_available = is_ffmpeg_installed()
    js_runtime = get_js_runtime()

    st.title("🛡️ YouTube Downloader [v3.4 - 실시간 진단 모드]")
    
    if is_cloud:
        st.warning("⚠️ **Cloud 서버** 실행 중: 강력한 차단이 적용됩니다.")
    else:
        st.success("🏠 **로컬 환경** 실행 중: 본인 IP를 사용하여 성공률이 높습니다.")

    with st.sidebar:
        st.header("⚙️ 하네스 통제 센터")
        
        c1, c2 = st.columns(2)
        c1.metric("FFmpeg", "OK" if ffmpeg_available else "MISSING")
        c2.metric("JS Runtime", js_runtime if js_runtime else "NONE")
        
        if st.button("🔄 세션 및 캐시 초기화"):
            st.session_state.delivered_files = []
            st.rerun()

        st.write("---")
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질 제한", options=["360p", "720p", "1080p", "최고화질"], value="1080p")
        
        st.write("---")
        st.subheader("🔑 1단계: 신분증 (쿠키)")
        st.caption("로그에 'Invalid Cookies'가 뜨면 반드시 새로 추출해서 올리세요.")
        cookie_file = st.file_uploader("youtube.com_cookies.txt", type=["txt"])
        
        st.write("---")
        st.subheader("🔐 2단계: 보안 토큰 (심화)")
        po_token = st.text_input("PO_TOKEN", help="web+토큰 형식으로 자동 변환됩니다.")
        visitor_data = st.text_input("Visitor Data")
        
        show_raw_logs = st.checkbox("실시간 디버그 로그 표시", value=True)

    st.subheader("다운로드 실행")
    url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")

    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 정밀 분석 후 수집 시작", type="primary"):
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

                # [Harness] 클라이언트 다변화 및 암호 해독 설정
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
                            'player_client': ['web', 'tv', 'mweb'], # tv 클라이언트는 가끔 쿠키 없이도 작동
                            'player_skip': ['configs', 'webpage'],
                        }
                    },
                }

                if js_runtime:
                    ydl_opts['javascript_runtime'] = js_runtime

                # PO_TOKEN 지능형 멀티 주입
                if po_token:
                    yt_args = ydl_opts['extractor_args']['youtube']
                    yt_args['po_token'] = [f"web+{po_token}", f"mweb+{po_token}", f"web_creator+{po_token}", f"tv+{po_token}"]
                    if visitor_data:
                        yt_args['visitor_data'] = [visitor_data]

                # 포맷 설정 (병합 실패를 대비한 유연한 구성)
                if mode_key == "video":
                    h = "1080" if quality == "최고화질" else quality.replace("p", "")
                    if ffmpeg_available:
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

                # [Logger] 실시간 진단 센서
                class YdlLogger:
                    def debug(self, msg): 
                        raw_log_data.append(f"[DEBUG] {msg}")
                        if show_raw_logs: log_container.code("\n".join(raw_log_data[-15:]))
                    def warning(self, msg): 
                        raw_log_data.append(f"[WARN] {msg}")
                        if show_raw_logs: log_container.code("\n".join(raw_log_data[-15:]))
                    def error(self, msg):
                        raw_log_data.append(f"[ERROR] {msg}")
                        if show_raw_logs: log_container.code("\n".join(raw_log_data[-15:]))
                
                ydl_opts['logger'] = YdlLogger()

                with st.status("🏗️ 유튜브 서버와 신분 대조 중...", expanded=True) as status:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            # 1단계: 가능한 포맷 리스트 확인 (로그 기록용)
                            ydl.download([url_input])
                        status.update(label="✅ 프로세스 완료", state="complete")
                    except Exception as download_err:
                        err_msg = str(download_err)
                        block_type = check_for_blocks(err_msg)
                        if block_type == "쿠키 만료 (Invalid Cookies)":
                            status.update(label="🛑 쿠키가 낡았습니다!", state="error")
                            st.error("유튜브가 현재 쿠키를 거부했습니다. 브라우저에서 'Get cookies.txt'로 새로 추출해 주세요.")
                        else:
                            status.update(label=f"🛑 {block_type if block_type else '수집 실패'}", state="error")
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
                    st.warning("⚠️ 신분 확인은 되었으나, 사용 가능한 비디오/오디오 스트림을 찾지 못했습니다.")

            except Exception:
                pass

    if st.session_state.delivered_files:
        st.write("---")
        st.success(f"📦 {len(st.session_state.delivered_files)}개의 파일이 검문을 통과했습니다!")
        
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
