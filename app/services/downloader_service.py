import os
import re
import shutil
import tempfile
import time
import urllib.request
import uuid
import zipfile
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    output_tmpl = os.path.join(movie_folder, f"{track.track_number:02d} - {safe_title}.%(ext)s")

    # yt-dlp pure audio extraction configuration (Fast stream, full track)
    ydl_opts = {
        "format": "ba/b[ext=m4a]/ba*/best",
        "outtmpl": output_tmpl,
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "default_search": "ytsearch1",
        "ignoreerrors": True,
        "socket_timeout": 15,
        "retries": 1,
        "fragment_retries": 1,
    }

    # Primary search query: Movie + Song Title + Artist + audio
    artist_part = f" {track.artist}" if track.artist and "various" not in track.artist.lower() else ""
    primary_query = f"ytsearch1:{track.movie} {track.title}{artist_part} audio"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([primary_query])
    except Exception as e:
        print(f"Primary audio search failed for {track.title}: {e}")

    # Check if download succeeded (>500KB indicates full song, not a short snippet)
    if os.path.exists(movie_folder):
        for f in os.listdir(movie_folder):
            if f.startswith(f"{track.track_number:02d} - {safe_title}.") and f.endswith(('.mp3', '.flac', '.m4a', '.wav', '.opus', '.aac')):
                fpath = os.path.join(movie_folder, f)
                if os.path.getsize(fpath) > 500000:
                    return True

    # Fallback search query if primary query didn't yield a file: Movie + Title + song
    fallback_query = f"ytsearch1:{track.movie} {track.title} song"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([fallback_query])
    except Exception as e:
        print(f"Fallback audio search failed for {track.title}: {e}")

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
