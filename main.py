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

# 센서 임포트 가드
try:
    from scripts.sensors.check_block import check_for_blocks
except ImportError:
    def check_for_blocks(msg): 
        if "403" in msg or "Forbidden" in msg: return "IP 차단 (403 Forbidden)"
        if "429" in msg: return "요청 과다 (429 Too Many Requests)"
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
    st.title("🚀 YouTube Downloader [v2.7 - 최종 돌파 모드]")
    
    ffmpeg_available = is_ffmpeg_installed()
    
    with st.sidebar:
        st.header("⚙️ Harness Control")
        if not ffmpeg_available:
            st.warning("⚠️ FFmpeg 미설치: 720p 제한 및 MP3 변환 불가")
            
        mode = st.radio("포맷", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.select_slider("화질", options=["360p", "720p", "1080p"], value="1080p")
        
        st.write("---")
        st.subheader("🛡️ 차단 우회 (쿠키 업로드)")
        st.info("403 에러가 계속되면 유튜브 로그인 후 'Get cookies.txt'로 받은 파일을 꼭 넣어주세요.")
        cookie_file = st.file_uploader("youtube.com_cookies.txt 업로드", type=["txt"])

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

                # [Harness] 차단 우회 및 안정성 강화 옵션
                ydl_opts = {
                    'quiet': False,               # 로거를 통해 상세 에러를 잡기 위해 False
                    'no_warnings': False,
                    'progress_hooks': [progress_hook],
                    'cookiesfrombrowser': None,
                    'nocheckcertificate': True,
                    'ignoreerrors': False,         # [CRITICAL] 에러 발생 시 즉시 멈추고 보고하게 함
                    'nopart': True,               # .part 파일 대신 직접 다운로드 (경로 꼬임 방지)
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    # [Harness] 최신 유튜브 차단 대응용 클라이언트 위장
                    'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
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
                    ydl_opts['format'] = 'bestaudio/best'
                    if ffmpeg_available:
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320',
                        }]

                # [Harness] 쿠키 주입 및 검증
                if cookie_file:
                    cookie_path = os.path.join(tmp_work_dir, "cookies.txt")
                    with open(cookie_path, "wb") as f: 
                        f.write(cookie_file.getvalue())
                    ydl_opts['cookiefile'] = cookie_path
                    st.toast("✅ 쿠키 신분증이 장착되었습니다.")

                ydl_opts['outtmpl'] = os.path.join(tmp_work_dir, '%(title)s.%(ext)s')

                # [Logger] 실시간 에러 포착 센서
                last_error = []
                class YdlLogger:
                    def debug(self, msg): pass
                    def warning(self, msg): pass
                    def error(self, msg):
                        last_error.append(msg)
                
                ydl_opts['logger'] = YdlLogger()

                with st.status("🏗️ 유튜브 서버에서 데이터 수집 시도 중...", expanded=True) as status:
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url_input])
                        status.update(label="✅ 수집 종료", state="complete")
                    except Exception as download_err:
                        err_msg = str(download_err)
                        block_type = check_for_blocks(err_msg)
                        if block_type:
                            status.update(label=f"🛑 {block_type} 발생", state="error")
                            st.error(f"유튜브가 차단했습니다: {block_type}. 쿠키 파일이 최신인지 확인하세요.")
                        else:
                            status.update(label="❌ 오류 발생", state="error")
                            st.error(f"상세 에러: {err_msg}")
                        raise download_err # 상위 try로 넘김

                # 결과물 확인
                if local_downloads:
                    for fpath in local_downloads:
                        # MP3 변환 완료 후 실제 파일명 찾기
                        if mode_key == "audio" and ffmpeg_available:
                            base = os.path.splitext(fpath)[0]
                            if os.path.exists(base + ".mp3"): fpath = base + ".mp3"
                        
                        if os.path.exists(fpath):
                            with open(fpath, "rb") as f:
                                st.session_state.delivered_files.append({
                                    "name": os.path.basename(fpath),
                                    "data": f.read()
                                })
                elif not last_error:
                    st.warning("⚠️ 파일이 생성되지 않았습니다. URL을 다시 확인해 보세요.")

            except Exception as e:
                # 이미 위에서 에러 처리를 했으므로 로그만 남김
                pass

    # --- 2단계: 브라우저 배송 ---
    if st.session_state.delivered_files:
        st.write("---")
        st.success(f"📦 총 {len(st.session_state.delivered_files)}개의 파일이 배송 대기 중입니다.")
        
        if len(st.session_state.delivered_files) == 1:
            file_info = st.session_state.delivered_files[0]
            st.download_button(
                label=f"💾 {file_info['name']} 다운로드 받기",
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
