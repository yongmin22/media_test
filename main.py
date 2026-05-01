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
    def check_for_blocks(msg): return None

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
    st.title("📦 YouTube Downloader [배송 시스템 가동]")
    
    # [Harness] 시스템 상태 확인
    ffmpeg_available = is_ffmpeg_installed()
    
    with st.sidebar:
        st.header("⚙️ Harness Config")
        if not ffmpeg_available:
            st.warning("⚠️ FFmpeg가 설치되지 않았습니다. 고화질 병합이 불가능하여 단일 파일(최대 720p) 모드로 동작합니다.")
            st.info("해결책: 깃허브에 'packages.txt' 파일을 만들고 'ffmpeg'를 입력해 업로드하세요.")
            
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질", options=["360p", "720p", "1080p"], value="1080p")
        st.info("차단 시 cookies.txt를 업로드하세요.")
        cookie_file = st.file_uploader("cookies.txt", type=["txt"])

    st.subheader("1단계: 수집 대상 설정")
    url_input = st.text_input("YouTube URL (단일 또는 재생목록)", placeholder="https://www.youtube.com/...")

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

                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'progress_hooks': [progress_hook],
                    'cookiesfrombrowser': None,
                }

                # [Harness] 동적 포맷 결정 (FFmpeg 유무에 따른 최적화)
                if mode_key == "video":
                    h = quality.replace("p", "")
                    if ffmpeg_available:
                        # FFmpeg가 있으면 영상/음성 병합 포맷 사용 (최고화질 가능)
                        ydl_opts['format'] = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best'
                        ydl_opts['merge_output_format'] = 'mp4'
                    else:
                        # FFmpeg가 없으면 이미 합쳐진 단일 파일만 요청 (보통 720p 이하)
                        ydl_opts['format'] = f'best[height<={h}][ext=mp4]/best[ext=mp4]/best'
                else:
                    if ffmpeg_available:
                        ydl_opts['format'] = 'bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320',
                        }]
                    else:
                        # FFmpeg가 없으면 MP3 변환 불가. 원본 오디오(주로 m4a/webm)를 그대로 받음
                        ydl_opts['format'] = 'bestaudio/best'
                        st.warning("FFmpeg 부재로 MP3 변환을 건너뛰고 원본 오디오 형식으로 다운로드합니다.")

                if cookie_file:
                    c_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(c_path, "wb") as f: f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = c_path

                ydl_opts['outtmpl'] = os.path.join(tmp_work_dir, '%(title)s.%(ext)s')

                with st.status("🏗️ 서버 창고로 데이터 수집 중...", expanded=True) as status:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url_input])
                    status.update(label="✅ 수집 완료! 배송 준비 중...", state="complete")

                if local_downloads:
                    for fpath in local_downloads:
                        # FFmpeg가 있을 때만 mp3 확장자 체크
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
                    st.error("파일 수집에 실패했습니다. (유튜브 정책 변경 또는 차단 가능성)")
            
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
            
            with st.expander("개별 파일 보기"):
                for f in st.session_state.delivered_files:
                    st.write(f"📄 {f['name']}")

if __name__ == "__main__":
    main()
