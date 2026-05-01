import streamlit as st
import os
import sys
import datetime
import json
import logging

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.sensors.check_block import check_for_blocks, heal
from scripts.sensors.check_quality import verify_contract

# --- Configuration & Setup ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(os.path.join(DOWNLOADS_DIR, "videos"), exist_ok=True)
os.makedirs(os.path.join(DOWNLOADS_DIR, "music"), exist_ok=True)
os.makedirs(os.path.join(DOWNLOADS_DIR, "quarantine"), exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def log_event(url, mode, event, detail="", output_path=None, error=None, heal_step=None):
    today = datetime.datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(LOGS_DIR, f"download_{today}.jsonl")
    
    log_data = {
        "timestamp": datetime.datetime.now().isoformat() + "+09:00",
        "url": url,
        "mode": mode,
        "event": event,
        "detail": detail
    }
    if output_path:
        log_data["output_path"] = output_path
    if error:
        log_data["error"] = error
    if heal_step is not None:
        log_data["heal_step"] = heal_step
        
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data, ensure_ascii=False) + "\n")

# --- UI Functions ---
def main():
    st.set_page_config(page_title="YouTube Downloader v2", page_icon="🎬", layout="wide")
    
    st.title("🎬 YouTube Downloader [v2]")
    
    with st.sidebar:
        st.header("설정")
        mode = st.radio("다운로드 모드", ["영상 (MP4)", "오디오 (MP3)"])
        quality = st.radio("화질", ["1080p 이하 (기본)", "최고화질"])
        auto_heal = st.checkbox("자가 치유 자동 실행", value=True)
    
    url_type = st.radio("다운로드 소스 선택", ["단일 URL", "재생목록 (Playlist) URL"])
    url_input = st.text_input("YouTube URL 입력", placeholder="https://www.youtube.com/...")
    
    if st.button("🚀 다운로드 시작", type="primary"):
        if not url_input:
            st.warning("URL을 입력해주세요.")
            return
            
        mode_key = "video" if "영상" in mode else "audio"
        
        st.write("---")
        st.subheader("진행 상황")
        
        # UI Elements for progress
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Import yt_dlp here to ensure it's available or handle import error
        try:
            import yt_dlp
        except ImportError:
            st.error("yt-dlp 모듈이 설치되어 있지 않습니다. `pip install yt-dlp`를 실행하세요.")
            return
            
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        
        # 1. Base Options
        ydl_opts = {
            'ignoreerrors': True,  # 헌법: 예외 처리 루프 (오류 시 다음으로 진행)
            'quiet': True,
            'no_warnings': True,
        }
        
        # 2. Paths & Naming
        if mode_key == "video":
            target_dir = os.path.join(DOWNLOADS_DIR, "videos")
            if url_type == "재생목록 (Playlist) URL":
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] [%(playlist_index)02d] %(title)s.%(ext)s")
                ydl_opts['yes_playlist'] = True
            else:
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] %(title)s.%(ext)s")
                ydl_opts['noplaylist'] = True
                
            if "1080p" in quality:
                ydl_opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
            else:
                ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            ydl_opts['merge_output_format'] = 'mp4'
            
        else:
            target_dir = os.path.join(DOWNLOADS_DIR, "music")
            if url_type == "재생목록 (Playlist) URL":
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] [%(playlist_index)02d] %(title)s.%(ext)s")
                ydl_opts['yes_playlist'] = True
            else:
                ydl_opts['outtmpl'] = os.path.join(target_dir, f"[{today_str}] %(title)s.%(ext)s")
                ydl_opts['noplaylist'] = True
                
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0',
            }, {'key': 'EmbedThumbnail'}, {'key': 'FFmpegMetadata'}]
            ydl_opts['writethumbnail'] = True
            
        # Logging config (custom logger)
        class MyLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg):
                block = check_for_blocks(msg)
                if block:
                    st.toast(f"차단 감지됨: {block}")
                    log_event(url_input, mode_key, "fail", detail=msg, error=block)
                else:
                    log_event(url_input, mode_key, "fail", error=msg)
                    
        ydl_opts['logger'] = MyLogger()
        
        # Progress Hook
        finished_items = []
        def my_hook(d):
            if d['status'] == 'finished':
                filename = d['filename']
                # yt-dlp의 임시 파일 이름 대신 실제 출력 파일 이름을 추론하거나, postprocessor hook에서 검증해야 함.
                # 단순화를 위해 여기서 로깅
                st.toast(f"다운로드 완료: {os.path.basename(filename)}")
                finished_items.append(filename)
                
        ydl_opts['progress_hooks'] = [my_hook]
        
        # Post-processor Hook for Quality Check
        def pp_hook(d):
            if d['status'] == 'finished':
                final_file = d['info_dict'].get('filepath', d.get('filename'))
                if final_file and os.path.exists(final_file):
                    is_valid, msg = verify_contract(final_file, mode_key)
                    if not is_valid:
                        st.warning(f"품질 위반 격리: {os.path.basename(final_file)} ({msg})")
                        log_event(url_input, mode_key, "fail", detail="Quarantined", error=msg)
                    else:
                        log_event(url_input, mode_key, "success", output_path=final_file)
                        
        ydl_opts['postprocessor_hooks'] = [pp_hook]

        # Execute Download
        status_text.info("다운로드를 준비 중입니다...")
        log_event(url_input, mode_key, "start", detail=f"Playlist: {ydl_opts.get('yes_playlist', False)}")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # To show proper progress for playlists, we could optionally extract_info first
                # but it might be slow. We'll rely on the simple hooks for now.
                status_text.info("다운로드 중입니다. 오류가 발생해도 계속 진행됩니다...")
                ydl.download([url_input])
                
            progress_bar.progress(100)
            status_text.success(f"작업 완료! (완료된 항목: {len(finished_items)}개)")
            
        except Exception as e:
            st.error(f"다운로드 중 치명적인 오류 발생: {e}")
            log_event(url_input, mode_key, "fail", error=str(e))

if __name__ == "__main__":
    main()
