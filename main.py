import streamlit as st
import os
import sys
import datetime
import json
import tempfile
import zipfile
import subprocess
from io import BytesIO

# [Harness] 경로 엔트로피 제어: 로컬/클라우드 환경 통합 인식
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 센서 임포트 가드 (scripts 폴더가 없어도 UI는 뜨도록)
try:
    from scripts.sensors.check_block import check_for_blocks
except ImportError:
    def check_for_blocks(msg): 
        if "403" in msg or "Forbidden" in msg:
            return "IP 차단 (403 Forbidden)"
        return None

# --- Configuration ---
LOGS_DIR = os.path.join(current_dir, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def log_event(url, mode, event, detail="", error=None):
    log_file = os.path.join(LOGS_DIR, f"harness_{datetime.datetime.now().strftime('%Y%m%d')}.jsonl")
    log_data = {"ts": datetime.datetime.now().isoformat(), "url": url, "mode": mode, "event": event, "detail": detail}
    if error: log_data["error"] = error
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data, ensure_ascii=False) + "\n")

def is_ffmpeg_installed():
    """[Harness Sensor] 시스템에 ffmpeg가 설치되어 있는지 확인합니다."""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def main():
    st.set_page_config(page_title="YT-Harness Direct", page_icon="📦", layout="wide")
    st.title("📦 YouTube Downloader [v2.6 - 차단 대응]")
    
    # [Harness] 시스템 상태 확인
    ffmpeg_available = is_ffmpeg_installed()
    
    with st.sidebar:
        st.header("⚙️ Harness Control")
        if not ffmpeg_available:
            st.warning("⚠️ FFmpeg 미설치: 고화질 병합 불가 (720p 제한)")
            
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질", options=["360p", "720p", "1080p"], value="1080p")
        
        st.write("---")
        st.subheader("🛡️ 차단 우회 신분증 (쿠키)")
        st.markdown("""
        **403 에러 발생 시 대처법:**
        1. 크롬 확장프로그램 [Get cookies.txt] 설치
        2. 유튜브 접속 후 쿠키 추출
        3. 아래에 업로드 후 재시도
        """)
        cookie_file = st.file_uploader("cookies.txt 업로드", type=["txt"])

    st.subheader("1단계: 수집 대상 설정")
    url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/...")

    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 서버 수집 시작", type="primary"):
        if not url_input:
            st.error("URL을 먼저 입력해 주세요!")
            return

        st.session_state.delivered_files = [] 
        mode_key = "video" if "영상" in mode else "audio"
        
        with tempfile.TemporaryDirectory() as tmp_work_dir:
            try:
                import yt_dlp
                local_downloads = []

                def progress_hook(d):
                    if d['status'] == 'finished':
                        fname = d.get('info_dict').get('filepath', d.get('filename'))
                        local_downloads.append(fname)

                # [Harness] 차단 우회 및 네트워크 안정화 옵션
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'progress_hooks': [progress_hook],
                    'cookiesfrombrowser': None,
                    'nocheckcertificate': True,      # 인증서 체크 건너뛰기 (네트워크 에러 방지)
                    'ignoreerrors': True,            # 일부 영상 실패 시에도 중단 방지
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }

                # 동적 포맷 결정
                if mode_key == "video":
                    h = quality.replace("p", "")
                    if ffmpeg_available:
                        ydl_opts['format'] = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best'
                        ydl_opts['merge_output_format'] = 'mp4'
                    else:
                        ydl_opts['format'] = f'best[height<={h}][ext=mp4]/best[ext=mp4]/best'
                else:
                    if ffmpeg_available:
                        ydl_opts['format'] = 'bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320',
                        }]
                    else:
                        ydl_opts['format'] = 'bestaudio/best'

                # [Harness] 쿠키 주입
                if cookie_file:
                    c_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(c_path, "wb") as f: f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = c_path

                ydl_opts['outtmpl'] = os.path.join(tmp_work_dir, '%(title)s.%(ext)s')

                # [Logger] 403 에러 감지용 로거
                class YdlLogger:
                    def debug(self, msg): pass
                    def warning(self, msg): pass
                    def error(self, msg):
                        block_type = check_for_blocks(msg)
                        if block_type:
                            st.error(f"🛑 {block_type}: 유튜브가 서버 IP를 차단했습니다. 사이드바의 가이드에 따라 쿠키를 업로드하세요.")
                
                ydl_opts['logger'] = YdlLogger()

                with st.status("🏗️ 서버 창고로 데이터 수집 중...", expanded=True) as status:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url_input])
                    status.update(label="✅ 수집 프로세스 종료", state="complete")

                if local_downloads:
                    for fpath in local_downloads:
                        if ffmpeg_available and mode_key == "audio" and not fpath.endswith(".mp3"):
                            potential_mp3 = os.path.splitext(fpath)[0] + ".mp3"
                            if os.path.exists(potential_mp3):
                                fpath = potential_mp3
                        
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.session_state.delivered_files.append({
                                    "name": os.path.basename(fpath),
                                    "data": f.read()
                                })
                else:
                    st.warning("⚠️ 수집된 파일이 없습니다. URL이 올바른지, 혹은 403 차단이 발생했는지 확인하세요.")
            
            except Exception as e:
                st.error(f"수집 실패: {e}")
                log_event(url_input, mode_key, "error", error=str(e))

    if st.session_state.delivered_files:
        st.write("---")
        st.subheader("2단계: 내 컴퓨터로 배송받기")
        
        if len(st.session_state.delivered_files) == 1:
            file_info = st.session_state.delivered_files[0]
            st.download_button(
                label=f"💾 {file_info['name']} 다운로드",
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
                label=f"🎁 재생목록 전체 압축 다운로드 (총 {len(st.session_state.delivered_files)}개)",
                data=zip_buffer.getvalue(),
                file_name=f"Playlist_{datetime.datetime.now().strftime('%H%M%S')}.zip",
                mime="application/zip",
                use_container_width=True
            )

if __name__ == "__main__":
    main()
