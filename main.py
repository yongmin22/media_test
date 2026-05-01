import streamlit as st
import os
import sys
import datetime
import json
import tempfile
import zipfile
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

def main():
    st.set_page_config(page_title="YT-Harness Direct", page_icon="📦", layout="wide")
    st.title("📦 YouTube Downloader [배송 시스템 가동]")
    
    with st.sidebar:
        st.header("⚙️ Harness Config")
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질", options=["360p", "720p", "1080p"], value="1080p")
        st.info("차단 시 cookies.txt를 업로드하세요.")
        cookie_file = st.file_uploader("cookies.txt", type=["txt"])

    st.subheader("1단계: 수집 대상 설정")
    url_input = st.text_input("YouTube URL (단일 또는 재생목록)", placeholder="https://www.youtube.com/...")

    # 세션 상태로 다운로드된 파일 목록 관리
    if 'delivered_files' not in st.session_state:
        st.session_state.delivered_files = []

    if st.button("🚀 서버 수집 시작", type="primary"):
        if not url_input:
            st.error("URL을 먼저 입력해 주세요!")
            return

        st.session_state.delivered_files = [] # 초기화
        mode_key = "video" if "영상" in mode else "audio"
        
        # 임시 작업 공간 (서버 창고)
        with tempfile.TemporaryDirectory() as tmp_work_dir:
            try:
                import yt_dlp
                
                # 수집된 파일 경로를 저장할 리스트
                local_downloads = []

                # yt-dlp가 파일명을 확정하는 순간을 포착하는 훅
                def progress_hook(d):
                    if d['status'] == 'finished':
                        # 다운로드 완료된 파일명 확보
                        fname = d.get('info_dict').get('filepath', d.get('filename'))
                        local_downloads.append(fname)

                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'progress_hooks': [progress_hook],
                    'cookiesfrombrowser': None, # 서버 에러 방지
                }

                # 포맷 설정
                if mode_key == "video":
                    h = quality.replace("p", "")
                    ydl_opts['format'] = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}]'
                    ydl_opts['merge_output_format'] = 'mp4'
                else:
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320',
                    }]

                # 쿠키 처리
                if cookie_file:
                    c_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(c_path, "wb") as f: f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = c_path

                # 파일 저장 위치 강제 (임시 폴더)
                ydl_opts['outtmpl'] = os.path.join(tmp_work_dir, '%(title)s.%(ext)s')

                # 실행
                with st.status("🏗️ 서버 창고로 데이터 수집 중...", expanded=True) as status:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url_input])
                    status.update(label="✅ 수집 완료! 배송 준비 중...", state="complete")

                # 결과물 가공 및 세션 저장
                if local_downloads:
                    for fpath in local_downloads:
                        # 오디오 변환 시 파일명 보정
                        if mode_key == "audio" and not fpath.endswith(".mp3"):
                            fpath = os.path.splitext(fpath)[0] + ".mp3"
                        
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.session_state.delivered_files.append({
                                    "name": os.path.basename(fpath),
                                    "data": f.read()
                                })
            
            except Exception as e:
                st.error(f"수집 실패: {e}")
                log_event(url_input, mode_key, "error", error=str(e))

    # --- 2단계: 브라우저 배송 (Download UI) ---
    if st.session_state.delivered_files:
        st.write("---")
        st.subheader("2단계: 내 컴퓨터로 배송받기")
        
        cols = st.columns(len(st.session_state.delivered_files) if len(st.session_state.delivered_files) < 4 else 1)
        
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
            # 재생목록일 경우 압축 배송
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
            
            # 개별 파일도 리스트로 보여줌
            with st.expander("개별 파일 보기"):
                for f in st.session_state.delivered_files:
                    st.write(f"📄 {f['name']}")

if __name__ == "__main__":
    main()
