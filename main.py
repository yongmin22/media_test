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
        if "n challenge" in msg: return "JS 런타임(Node.js) 미작동"
        if "PO Token" in msg or "confirm you're not a bot" in msg: return "봇 확인 필요 (PO_TOKEN 부족)"
        return None

# --- Configuration ---
LOGS_DIR = os.path.join(current_dir, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def is_ffmpeg_installed():
    return shutil.which("ffmpeg") is not None

def get_js_runtime():
    """[Harness] 시스템에서 사용 가능한 JS 런타임을 찾습니다."""
    for runtime in ["node", "nodejs", "deno"]:
        if shutil.which(runtime):
            return runtime
    return None

def main():
    st.set_page_config(page_title="YT-Harness Direct v3", page_icon="🛡️", layout="wide")
    st.title("🛡️ YouTube Downloader [v3.0 - 통합 인증 모드]")
    
    ffmpeg_available = is_ffmpeg_installed()
    js_runtime = get_js_runtime()
    
    with st.sidebar:
        st.header("⚙️ 하네스 통제 센터")
        
        # 시스템 상태 가시화
        status_col1, status_col2 = st.columns(2)
        status_col1.metric("FFmpeg", "OK" if ffmpeg_available else "MISSING")
        status_col2.metric("JS Runtime", js_runtime if js_runtime else "NONE")
        
        if not js_runtime:
            st.error("⚠️ n-challenge 해결 불가: 깃허브 packages.txt에 nodejs를 추가했는지 확인하세요.")

        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질", options=["360p", "720p", "1080p"], value="1080p")
        
        st.write("---")
        st.subheader("🔑 1단계: 기본 신분증 (쿠키)")
        cookie_file = st.file_uploader("youtube.com_cookies.txt", type=["txt"])
        
        st.write("---")
        st.subheader("🔐 2단계: 심화 인증 (PO_TOKEN 세트)")
        st.caption("차단이 강력할 때 3가지를 모두 입력하세요.")
        po_token = st.text_input("PO_TOKEN", help="추출된 PO_TOKEN 입력")
        visitor_data = st.text_input("Visitor Data", help="추출된 Visitor Data 입력")
        data_sync_id = st.text_input("Data Sync ID (New)", help="로그에서 요구하는 경우 입력")
        
        st.write("---")
        show_raw_logs = st.checkbox("실시간 디버그 로그", value=True)

    st.subheader("다운로드 실행")
    url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/...")

    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 서버 수집 및 정밀 분석 시작", type="primary"):
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

                # [Harness] 모든 우회 옵션 총망라
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
                            'player_client': ['web_creator', 'mweb', 'ios', 'android'],
                            'player_skip': ['configs'],
                        }
                    },
                }

                # JS 런타임이 감지되면 명시적으로 지정
                if js_runtime:
                    ydl_opts['javascript_runtime'] = js_runtime

                # [Harness] 인증 정보 주입 로직
                yt_args = ydl_opts['extractor_args']['youtube']
                if po_token:
                    # 클라이언트별로 토큰 주입
                    yt_args['po_token'] = [f"web+{po_token}", f"web_creator+{po_token}", f"mweb+{po_token}"]
                if visitor_data:
                    yt_args['visitor_data'] = [visitor_data]
                if data_sync_id:
                    yt_args['data_sync_id'] = [data_sync_id]

                # 포맷 설정 (병합 실패를 대비한 유연한 구성)
                if mode_key == "video":
                    h = quality.replace("p", "")
                    if ffmpeg_available:
                        # 고화질 병합 시도 -> 실패 시 단일 파일 best로 자동 전환되는 포맷 문자열
                        ydl_opts['format'] = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best'
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

                # [Logger] 하네스 모니터링 센서
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

                with st.status("🏗️ 유튜브 서버와 신분 교신 중...", expanded=True) as status:
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

                # 결과물 확인 및 배송 세션 저장
                if local_downloads:
                    for fpath in local_downloads:
                        if mode_key == "audio" and ffmpeg_available:
                            base = os.path.splitext(fpath)[0]
                            if os.path.exists(base + ".mp3"): fpath = base + ".mp3"
                        
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.session_state.delivered_files.append({"name": os.path.basename(fpath), "data": f.read()})
                    st.toast(f"✅ {len(st.session_state.delivered_files)}개 수집 성공!")
                else:
                    st.warning("⚠️ 신분증은 확인되었으나, 해당 화질의 포맷을 찾지 못했습니다. 화질을 낮춰보세요.")

            except Exception:
                pass

    # --- 2단계: 배송 ---
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
            st.download_button(label="🎁 전체 압축 다운로드", data=zip_buffer.getvalue(), file_name=f"YT_Harness_{datetime.datetime.now().strftime('%H%M%S')}.zip", use_container_width=True)

if __name__ == "__main__":
    main()
