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

# [Harness] 경로 및 환경 통제: 프로젝트 루트를 경로에 추가하여 센서 모듈 인식 보장
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 센서 임포트 가드: scripts 폴더가 없거나 경로가 잘못되어도 UI가 멈추지 않도록 설계
try:
    from scripts.sensors.check_block import check_for_blocks
except ImportError:
    def check_for_blocks(msg): 
        if "403" in msg or "Forbidden" in msg: return "IP 차단 (403 Forbidden)"
        if "429" in msg: return "요청 과다 (429 Too Many Requests)"
        if "n challenge" in msg: return "JS 런타임(Node.js) 인식 오류"
        if "PO Token" in msg or "confirm you're not a bot" in msg: return "강력 차단 (PO_TOKEN 필요)"
        return None

# --- Configuration ---
LOGS_DIR = os.path.join(current_dir, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def is_ffmpeg_installed():
    """[Harness Sensor] 시스템에 ffmpeg 도구가 설치되어 있는지 확인합니다."""
    return shutil.which("ffmpeg") is not None

def get_js_runtime():
    """[Harness Sensor] n-challenge 해결을 위한 JS 런타임 환경을 탐색합니다."""
    for runtime in ["node", "nodejs", "deno"]:
        if shutil.which(runtime):
            return runtime
    return None

def main():
    st.set_page_config(page_title="YT-Harness Local & Cloud", page_icon="🛡️", layout="wide")
    
    # [Harness] 환경 진단 센서: 현재 환경이 클라우드인지 로컬인지 판별
    is_cloud = "STREAMLIT_SERVER_PORT" in os.environ
    ffmpeg_available = is_ffmpeg_installed()
    js_runtime = get_js_runtime()

    st.title("🛡️ YouTube Downloader [v3.2 - 하이브리드 모드]")
    
    if is_cloud:
        st.warning("⚠️ 현재 **Cloud 서버**에서 실행 중입니다. 유튜브의 강력한 IP 차단이 적용될 수 있으니 반드시 쿠키나 PO_TOKEN을 사용하세요.")
        st.info("💡 정신 건강 가이드: 클라우드 IP 차단이 지속된다면, 이 코드를 다운로드받아 **로컬 PC**에서 실행하세요.")
    else:
        st.success("🏠 **로컬 환경**이 감지되었습니다. 본인의 공인 IP를 사용하므로 훨씬 안정적인 다운로드가 가능합니다.")

    with st.sidebar:
        st.header("⚙️ 하네스 통제 센터")
        
        # 하네스 지표 대시보드
        c1, c2 = st.columns(2)
        c1.metric("FFmpeg", "OK" if ffmpeg_available else "MISSING")
        c2.metric("JS Runtime", js_runtime if js_runtime else "NONE")
        
        mode = st.radio("포맷 선택", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질 제한", options=["360p", "720p", "1080p", "최고화질"], value="1080p")
        
        st.write("---")
        st.subheader("🔑 1단계: 기본 신분증 (쿠키)")
        cookie_file = st.file_uploader("youtube.com_cookies.txt 업로드", type=["txt"])
        
        st.write("---")
        st.subheader("🔐 2단계: 보안 토큰 (Cloud 필수)")
        st.caption("차단 시 PO_TOKEN과 Visitor Data를 직접 주입합니다.")
        po_token = st.text_input("PO_TOKEN", help="추출된 PO_TOKEN 입력")
        visitor_data = st.text_input("Visitor Data", help="추출된 Visitor Data 입력")
        
        show_raw_logs = st.checkbox("실시간 디버그 로그 표시", value=True)

    st.subheader("다운로드 실행")
    url_input = st.text_input("YouTube URL 입력 (단일 영상 또는 재생목록)", placeholder="https://www.youtube.com/watch?v=...")

    # 브라우저 전송을 위해 세션 상태에 데이터 보관
    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 보안망 돌파 및 수집 시작", type="primary"):
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

                # [Harness] 최적화된 우회 및 통제 옵션
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
                            'player_client': ['web', 'mweb'],
                            'player_skip': ['configs'],
                        }
                    },
                }

                # JS 런타임이 감지되면 명시적으로 전달하여 n-challenge 해결 유도
                if js_runtime:
                    ydl_opts['javascript_runtime'] = js_runtime

                # PO_TOKEN 주입 (인간 개입 하네스)
                if po_token:
                    yt_args = ydl_opts['extractor_args']['youtube']
                    yt_args['po_token'] = [f"web+{po_token}", f"mweb+{po_token}"]
                    if visitor_data:
                        yt_args['visitor_data'] = [visitor_data]

                # 포맷 설정 (병합 실패 시 자동 폴백)
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

                # 쿠키 파일 주입
                if cookie_file:
                    cookie_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(cookie_path, "wb") as f: f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = cookie_path

                ydl_opts['outtmpl'] = os.path.join(tmp_work_dir, '%(title)s.%(ext)s')

                # [Logger] 실시간 데이터 흐름 감시
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

                with st.status("🏗️ 신분 교신 및 데이터 수집 중...", expanded=True) as status:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url_input])
                        status.update(label="✅ 수집 프로세스 종료", state="complete")
                    except Exception as download_err:
                        err_msg = str(download_err)
                        block_type = check_for_blocks(err_msg)
                        status.update(label=f"🛑 {block_type if block_type else '실패'}", state="error")
                        st.error(f"상세 원인: {err_msg}")
                        raise download_err

                # 서버 메모리에 로드하여 사용자에게 쏴줌 (배송 단계)
                if local_downloads:
                    for fpath in local_downloads:
                        if mode_key == "audio" and ffmpeg_available:
                            base = os.path.splitext(fpath)[0]
                            if os.path.exists(base + ".mp3"): fpath = base + ".mp3"
                        
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.session_state.delivered_files.append({"name": os.path.basename(fpath), "data": f.read()})
                else:
                    st.warning("⚠️ 파일을 생성하지 못했습니다. 화질을 낮추거나 로컬 환경에서 시도해 보세요.")

            except Exception:
                pass

    # --- 2단계: 브라우저로 배송 ---
    if st.session_state.delivered_files:
        st.write("---")
        st.success(f"📦 {len(st.session_state.delivered_files)}개의 파일이 준비되었습니다!")
        
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
