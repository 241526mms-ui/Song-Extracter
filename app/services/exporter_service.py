import csv
import io
import json
from typing import List
from app.models import MovieResult

def format_duration(ms: int) -> str:
    """Format milliseconds into MM:SS format."""
    if not ms or ms <= 0:
        return "00:00"
    total_seconds = int(ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"

def export_as_csv(results: List[MovieResult]) -> str:
    """Generate RFC 4180 compliant CSV string for movie soundtrack tracks."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    
    # Header
    writer.writerow([
        "Movie",
        "Album",
        "Track #",
        "Song Title",
        "Artist / Singers",
        "Duration",
        "Year",
        "Preview URL"
    ])
    
    for movie in results:
        if not movie.found or not movie.tracks:
            writer.writerow([
                movie.movie_query,
                movie.album_title or "Not Found",
                "-",
                "No tracks found",
                "-",
                "-",
                movie.year or "-",
                "-"
            ])
            continue
            
        for track in movie.tracks:
            writer.writerow([
                track.movie,
                track.album,
                track.track_number,
                track.title,
                track.artist,
                track.duration_formatted,
                track.year or movie.year or "",
                track.preview_url or ""
            ])
            
    return output.getvalue()

def export_as_txt(results: List[MovieResult]) -> str:
    """Generate a clean, structured plaintext representation."""
    lines = []
    separator = "=" * 80
    subseparator = "-" * 80
    
    lines.append(separator)
    lines.append("                    MOVIE SOUNDTRACKS & SONGS EXPORT")
    lines.append(separator)
    lines.append("")
    
    grand_total_tracks = 0
    
    for idx, movie in enumerate(results, start=1):
        lines.append(separator)
        header = f"[{idx}] MOVIE: {movie.movie_query.upper()}"
        if movie.year:
            header += f" ({movie.year})"
        lines.append(header)
        
        if not movie.found or not movie.tracks:
            lines.append(f"Status: No soundtrack or tracks found ({movie.error or 'Check movie name'})")
            lines.append(separator)
            lines.append("")
            continue
            
        lines.append(f"Album:  {movie.album_title or 'Soundtrack'}")
        lines.append(f"Artist: {movie.artist or 'Various Artists'}")
        lines.append(f"Tracks: {len(movie.tracks)} songs")
        lines.append(subseparator)
        
        for track in movie.tracks:
            grand_total_tracks += 1
            num = f"{track.track_number:02d}"
            dur = f"[{track.duration_formatted}]"
            lines.append(f"  {num}. {track.title} - {track.artist} {dur}")
            
        lines.append(separator)
        lines.append("")
        
    lines.append(f"TOTAL MOVIES: {len(results)} | TOTAL TRACKS: {grand_total_tracks}")
    lines.append(separator)
    return "\n".join(lines)

def export_as_json(results: List[MovieResult]) -> str:
    """Generate indented JSON string."""
    data = [movie.model_dump() for movie in results]
    return json.dumps(data, indent=2, ensure_ascii=False)

def export_as_m3u(results: List[MovieResult]) -> str:
    """Generate standard M3U playlist file format."""
    lines = ["#EXTM3U"]
    for movie in results:
        if not movie.found or not movie.tracks:
            continue
        for track in movie.tracks:
            duration_sec = int((track.duration_ms or 0) / 1000)
            if duration_sec <= 0:
                duration_sec = -1
            lines.append(f"#EXTINF:{duration_sec},{track.artist} - {track.title}")
            if track.preview_url:
                lines.append(track.preview_url)
            else:
                lines.append(f"{track.movie} - {track.title}.mp3")
    return "\n".join(lines)

