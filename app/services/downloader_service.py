import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from Crypto.Cipher import DES
import yt_dlp
from app.models import MovieResult, Track

DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "music_website_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory dictionary tracking async download jobs
TASKS: Dict[str, dict] = {}

def cleanup_old_downloads(max_age_seconds: int = 900):
    """Automatically purge old zip files and temporary task folders to free disk space."""
    now = time.time()
    try:
        if not os.path.exists(DOWNLOAD_DIR):
            return
        for item in os.listdir(DOWNLOAD_DIR):
            item_path = os.path.join(DOWNLOAD_DIR, item)
            try:
                # If older than 15 minutes, remove
                mtime = os.path.getmtime(item_path)
                if now - mtime > max_age_seconds:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                    else:
                        os.remove(item_path)
            except Exception:
                pass

        # If free space is still low (less than 1.5 GB), remove oldest zips
        total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
        if free < 1500 * 1024 * 1024:
            zips = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".zip")]
            zips.sort(key=os.path.getmtime)
            for z in zips[:len(zips)//2 + 1]:
                try:
                    os.remove(z)
                except Exception:
                    pass
    except Exception as e:
        print(f"Error during cleanup: {e}")

def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames across OS platforms."""
    safe = re.sub(r'[\\/*?:"<>|]', "", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe or "untitled"

def download_cover_image(artwork_url: Optional[str], dest_folder: str) -> Optional[str]:
    """Download highest resolution album cover as cover.jpg inside the movie folder."""
    if not artwork_url:
        return None
    try:
        cover_path = os.path.join(dest_folder, "cover.jpg")
        if os.path.exists(cover_path):
            return cover_path
            
        req = urllib.request.Request(artwork_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            with open(cover_path, "wb") as f:
                f.write(resp.read())
        return cover_path
    except Exception as e:
        print(f"Error downloading cover image: {e}")
        return None

def fetch_cdn_stream(track: Track, movie_folder: str, audio_quality: str, target_ext: str, safe_title: str) -> bool:
    """Fetch direct full-length 320k/160k audio stream from Saavn high-speed CDN (unaffected by datacenter IP blocks)."""
    queries = [
        f"{track.movie} {track.title}",
        f"{track.title} {track.artist}" if track.artist and "various" not in track.artist.lower() else f"{track.title} {track.movie}"
    ]

    final_file = os.path.join(movie_folder, f"{track.track_number:02d} - {safe_title}.{target_ext}")

    for q in queries:
        try:
            url = f"https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&n=5&p=1&q={urllib.parse.quote_plus(q)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=7.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                if not results:
                    continue
                for item in results:
                    enc = item.get("encrypted_media_url")
                    if not enc:
                        continue
                    des = DES.new(b"38346591", DES.MODE_ECB)
                    decrypted = des.decrypt(base64.b64decode(enc))
                    pad = decrypted[-1]
                    if isinstance(pad, int) and 0 < pad <= 8:
                        decrypted = decrypted[:-pad]
                    clean = decrypted.decode("utf-8", errors="ignore").strip()

                    # Try 320k or 160k bitrate streams
                    stream_urls = [
                        clean.replace("_96.mp4", "_320.mp4"),
                        clean.replace("_96.mp4", "_160.mp4"),
                        clean
                    ]

                    raw_tmp = os.path.join(movie_folder, f".temp_{track.track_number}_{uuid.uuid4().hex[:6]}.m4a")

                    downloaded = False
                    for stream_url in stream_urls:
                        try:
                            dl_req = urllib.request.Request(stream_url, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(dl_req, timeout=12.0) as dl_resp, open(raw_tmp, "wb") as f:
                                f.write(dl_resp.read())
                            if os.path.exists(raw_tmp) and os.path.getsize(raw_tmp) > 500000:
                                downloaded = True
                                break
                        except Exception:
                            continue

                    if not downloaded or not os.path.exists(raw_tmp):
                        continue

                    # Transcode using FFmpeg to requested format (MP3 or FLAC) with ID3 tags
                    codec = "libmp3lame" if target_ext == "mp3" else "flac"
                    bitrate = "320k" if audio_quality == "mp3_320" else ("192k" if target_ext == "mp3" else None)

                    cmd = ["ffmpeg", "-y", "-i", raw_tmp, "-vn", "-c:a", codec]
                    if bitrate:
                        cmd.extend(["-b:a", bitrate])
                    cmd.extend([
                        "-metadata", f"title={track.title}",
                        "-metadata", f"artist={track.artist}",
                        "-metadata", f"album={track.album}",
                        "-metadata", f"track={track.track_number}",
                        final_file
                    ])

                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    if os.path.exists(raw_tmp):
                        try:
                            os.remove(raw_tmp)
                        except Exception:
                            pass

                    if os.path.exists(final_file) and os.path.getsize(final_file) > 500000:
                        return True
        except Exception as e:
            continue

    return False

def download_single_track(track: Track, movie_folder: str, audio_quality: str, cover_path: Optional[str] = None) -> bool:
    """Download a single full-length track in requested quality (FLAC, MP3 320k, or Fast MP3 192k)."""
    safe_title = sanitize_filename(track.title)
    
    # Map any legacy "fast" setting to high-speed full-length 192kbps MP3 (NO 30-sec previews)
    if audio_quality == "fast":
        audio_quality = "mp3_192"

    # Determine codec and file extension
    if audio_quality == "flac":
        target_ext = "flac"
        postprocessors = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "flac"},
            {"key": "FFmpegMetadata"}
        ]
    elif audio_quality == "mp3_320":
        target_ext = "mp3"
        postprocessors = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"},
            {"key": "FFmpegMetadata"}
        ]
    else:  # mp3_192 (Fast Full Songs) or fallback
        target_ext = "mp3"
        postprocessors = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegMetadata"}
        ]

    final_file = os.path.join(movie_folder, f"{track.track_number:02d} - {safe_title}.{target_ext}")
    if os.path.exists(final_file) and os.path.getsize(final_file) > 500000:
        return True

    # Check if any valid full audio file exists for this track number and title
    if os.path.exists(movie_folder):
        for f in os.listdir(movie_folder):
            if f.startswith(f"{track.track_number:02d} - {safe_title}.") and f.endswith(('.mp3', '.flac', '.m4a', '.wav', '.opus', '.aac')):
                fpath = os.path.join(movie_folder, f)
                if os.path.getsize(fpath) > 500000:
                    return True

    # 1. Primary Engine: High-Speed Direct CDN Stream (unblocked on cloud/datacenter IPs)
    try:
        if fetch_cdn_stream(track, movie_folder, audio_quality, target_ext, safe_title):
            return True
    except Exception as e:
        print(f"CDN fetch failed for {track.title}: {e}")

    # 2. Secondary Engine: YouTube Audio Stream via yt-dlp
    output_tmpl = os.path.join(movie_folder, f"{track.track_number:02d} - {safe_title}.%(ext)s")
    ydl_opts = {
        "format": "ba/b[ext=m4a]/ba*/best",
        "outtmpl": output_tmpl,
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "default_search": "ytsearch1",
        "ignoreerrors": True,
        "socket_timeout": 12,
        "retries": 1,
        "fragment_retries": 1,
    }

    artist_part = f" {track.artist}" if track.artist and "various" not in track.artist.lower() else ""
    primary_query = f"ytsearch1:{track.movie} {track.title}{artist_part} audio"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([primary_query])
    except Exception as e:
        print(f"Primary audio search failed for {track.title}: {e}")

    if os.path.exists(movie_folder):
        for f in os.listdir(movie_folder):
            if f.startswith(f"{track.track_number:02d} - {safe_title}.") and f.endswith(('.mp3', '.flac', '.m4a', '.wav', '.opus', '.aac')):
                fpath = os.path.join(movie_folder, f)
                if os.path.getsize(fpath) > 500000:
                    return True

    # 3. Tertiary Engine: SoundCloud Search via yt-dlp (bypasses YouTube bot verification on cloud IPs)
    sc_query = f"scsearch1:{track.movie} {track.title}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([sc_query])
    except Exception as e:
        print(f"SoundCloud audio search failed for {track.title}: {e}")

    if os.path.exists(movie_folder):
        for f in os.listdir(movie_folder):
            if f.startswith(f"{track.track_number:02d} - {safe_title}.") and f.endswith(('.mp3', '.flac', '.m4a', '.wav', '.opus', '.aac')):
                fpath = os.path.join(movie_folder, f)
                if os.path.getsize(fpath) > 500000:
                    return True

    return False

def process_download_job(task_id: str, results: List[MovieResult], audio_quality: str):
    """Background worker downloading all tracks in parallel and packaging with cover art into a ZIP."""
    # Run automatic garbage collection to purge old zip files
    cleanup_old_downloads()

    task = TASKS.get(task_id)
    if not task:
        return

    # Collect all tracks
    all_tracks: List[Track] = []
    movie_covers: Dict[str, Optional[str]] = {}

    for movie in results:
        if movie.found and movie.tracks:
            safe_mname = sanitize_filename(movie.movie_query)
            movie_covers[safe_mname] = movie.artwork_url
            for track in movie.tracks:
                all_tracks.append(track)

    total = len(all_tracks)
    task["total_tracks"] = total

    if total == 0:
        task["status"] = "failed"
        task["error"] = "No valid tracks selected to download."
        return

    task["status"] = "in_progress"
    task_workspace = os.path.join(DOWNLOAD_DIR, task_id)
    os.makedirs(task_workspace, exist_ok=True)

    # Step 1: Download high-res cover art for each movie folder
    for movie_name, art_url in movie_covers.items():
        movie_dir = os.path.join(task_workspace, movie_name)
        os.makedirs(movie_dir, exist_ok=True)
        download_cover_image(art_url, movie_dir)

    # Step 2: Download tracks concurrently in parallel (optimized for cloud servers)
    completed = 0
    max_workers = min(4, total)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_track = {}
        for track in all_tracks:
            movie_dir_name = sanitize_filename(track.movie)
            movie_dir = os.path.join(task_workspace, movie_dir_name)
            cover_file = os.path.join(movie_dir, "cover.jpg")
            
            future = pool.submit(
                download_single_track,
                track,
                movie_dir,
                audio_quality,
                cover_file if os.path.exists(cover_file) else None
            )
            future_to_track[future] = track

        for future in as_completed(future_to_track):
            track = future_to_track[future]
            completed += 1
            task["completed_tracks"] = completed
            task["current_track"] = f"Finished: {track.movie} - {track.title}"
            task["progress"] = int((completed / total) * 90)

    # Step 3: Verify audio files were downloaded and create ZIP archive
    downloaded_audio = []
    for root, _, files in os.walk(task_workspace):
        for f in files:
            if f.endswith(('.mp3', '.flac', '.m4a', '.wav')) and not f.startswith('.'):
                downloaded_audio.append(f)

    if not downloaded_audio:
        task["status"] = "failed"
        task["error"] = "No audio tracks could be downloaded from streaming sources. Please check your connection and retry."
        shutil.rmtree(task_workspace, ignore_errors=True)
        return

    try:
        task["current_track"] = f"Compressing {len(downloaded_audio)} songs into final ZIP archive..."
        task["progress"] = 93

        if audio_quality == "flac":
            quality_suffix = "FLAC_Lossless"
        elif audio_quality == "mp3_320":
            quality_suffix = "320kbps_MP3"
        else:
            quality_suffix = "FullSongs_MP3"
        zip_filename = f"soundtracks_{quality_suffix}_{task_id[:8]}.zip"
        zip_path = os.path.join(DOWNLOAD_DIR, zip_filename)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(task_workspace):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, task_workspace)
                    zipf.write(file_path, rel_path)

        # Cleanup uncompressed directory
        shutil.rmtree(task_workspace, ignore_errors=True)

        task["status"] = "completed"
        task["progress"] = 100
        task["current_track"] = "Download complete!"
        task["zip_path"] = zip_path
        task["filename"] = zip_filename
        task["download_url"] = f"/api/export/audio-zip/download/{task_id}"

    except OSError as e:
        shutil.rmtree(task_workspace, ignore_errors=True)
        cleanup_old_downloads(max_age_seconds=0)  # Aggressively purge old zips
        if e.errno in (122, 28):  # EDQUOT (Disk quota exceeded) or ENOSPC (No space left)
            task["status"] = "failed"
            task["error"] = "Disk quota exceeded: temporary storage was full. We automatically cleaned up old files, please try downloading again."
        else:
            task["status"] = "failed"
            task["error"] = f"Packaging error: {str(e)}"
    except Exception as e:
        shutil.rmtree(task_workspace, ignore_errors=True)
        task["status"] = "failed"
        task["error"] = f"Packaging error: {str(e)}"

def start_audio_zip_task(results: List[MovieResult], audio_quality: str = "mp3_192") -> str:
    """Start asynchronous audio download and zip creation."""
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "progress": 0,
        "current_track": "Initializing parallel download engine...",
        "total_tracks": 0,
        "completed_tracks": 0,
        "zip_path": None,
        "filename": None,
        "download_url": None,
        "error": None,
    }
    # Run in a background thread
    ThreadPoolExecutor(max_workers=1).submit(process_download_job, task_id, results, audio_quality)
    return task_id

def get_task_status(task_id: str) -> Optional[dict]:
    """Get status of an audio zip download task."""
    return TASKS.get(task_id)

def get_zip_path(task_id: str) -> Optional[str]:
    """Retrieve the path to the completed ZIP file."""
    task = TASKS.get(task_id)
    if task and task.get("status") == "completed":
        return task.get("zip_path")
    return None
