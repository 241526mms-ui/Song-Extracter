import os
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    SearchRequest,
    SearchResponse,
    ExportTracklistRequest,
    DownloadAudioRequest,
)
from app.services.music_service import search_multiple_movies
from app.services.exporter_service import (
    export_as_csv,
    export_as_txt,
    export_as_json,
    export_as_m3u,
)
from app.services.downloader_service import (
    start_audio_zip_task,
    get_task_status,
    get_zip_path,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="Movie Soundtrack & Song Exporter API",
    description="Search movie soundtracks globally and export as CSV, TXT, JSON, or MP3 ZIP",
    version="1.0.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    """Serve frontend index.html."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Movie Song Fetcher API is running. UI not found."}

@app.post("/api/search", response_model=SearchResponse)
async def search_soundtracks(request: SearchRequest):
    """Search for soundtrack albums and songs across a list of movie names."""
    if not request.movies:
        raise HTTPException(status_code=400, detail="Please provide at least one movie name.")

    results = await search_multiple_movies(request.movies, language=request.language)
    total_tracks = sum(len(m.tracks) for m in results if m.found)
    
    return SearchResponse(
        results=results,
        total_movies=len(results),
        total_tracks=total_tracks,
    )

@app.post("/api/export/tracklist")
async def export_tracklist(request: ExportTracklistRequest):
    """Generate and download tracklist in CSV, TXT, JSON, or M3U format."""
    fmt = (request.format or "csv").lower()
    
    if fmt == "csv":
        content = export_as_csv(request.results)
        media_type = "text/csv; charset=utf-8"
        filename = "movie_soundtracks.csv"
    elif fmt == "txt":
        content = export_as_txt(request.results)
        media_type = "text/plain; charset=utf-8"
        filename = "movie_soundtracks.txt"
    elif fmt == "json":
        content = export_as_json(request.results)
        media_type = "application/json; charset=utf-8"
        filename = "movie_soundtracks.json"
    elif fmt == "m3u":
        content = export_as_m3u(request.results)
        media_type = "audio/x-mpegurl; charset=utf-8"
        filename = "movie_soundtracks.m3u"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported export format: {fmt}")

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )

@app.post("/api/export/audio-zip")
async def export_audio_zip(request: DownloadAudioRequest):
    """Start background task to download MP3 tracks and package into ZIP."""
    if not request.results:
        raise HTTPException(status_code=400, detail="No movies provided.")

    task_id = start_audio_zip_task(request.results, audio_quality=request.audio_quality)
    return {"task_id": task_id, "status": "queued"}

@app.get("/api/export/audio-zip/status/{task_id}")
async def check_audio_zip_status(task_id: str):
    """Check status and progress of an audio ZIP download task."""
    status = get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found.")
    return status

@app.get("/api/export/audio-zip/download/{task_id}")
async def download_audio_zip(task_id: str):
    """Download the completed audio ZIP file."""
    zip_path = get_zip_path(task_id)
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP file not ready or expired.")
    
    filename = f"soundtracks_{task_id[:8]}.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
    )

