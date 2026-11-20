from typing import List, Optional
from pydantic import BaseModel, Field

class Track(BaseModel):
    id: str
    track_number: int = 1
    title: str
    artist: str
    album: str
    movie: str
    duration_ms: int = 0
    duration_formatted: str = "00:00"
    preview_url: Optional[str] = None
    artwork_url: Optional[str] = None
    year: Optional[str] = None
    source: Optional[str] = "itunes"

class MovieResult(BaseModel):
    movie_query: str
    found: bool = True
    album_title: Optional[str] = None
    artist: Optional[str] = None
    language: Optional[str] = None
    year: Optional[str] = None
    artwork_url: Optional[str] = None
    total_tracks: int = 0
    tracks: List[Track] = Field(default_factory=list)
    error: Optional[str] = None

class SearchRequest(BaseModel):
    movies: List[str]
    language: Optional[str] = "all"  # all, telugu, tamil, hindi, malayalam, kannada, english

class SearchResponse(BaseModel):
    results: List[MovieResult]
    total_movies: int
    total_tracks: int

class ExportTracklistRequest(BaseModel):
    results: List[MovieResult]
    format: str = "csv"  # csv, txt, json, m3u

class DownloadAudioRequest(BaseModel):
    results: List[MovieResult]
    audio_quality: str = "mp3_192"  # flac, mp3_320, mp3_192
