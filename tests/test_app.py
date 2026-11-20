import json
import unittest
from app.models import MovieResult, Track
from app.services.exporter_service import (
    format_duration,
    export_as_csv,
    export_as_txt,
    export_as_json,
    export_as_m3u,
)
from app.services.music_service import clean_movie_name
from fastapi.testclient import TestClient
from app.main import app

def get_sample_movie_results():
    track1 = Track(
        id="inc_1",
        track_number=1,
        title="Time",
        artist="Hans Zimmer",
        album="Inception (Music from the Motion Picture)",
        movie="Inception",
        duration_ms=275000,
        duration_formatted="04:35",
        year="2010"
    )
    movie1 = MovieResult(
        movie_query="Inception",
        found=True,
        album_title="Inception (Music from the Motion Picture)",
        artist="Hans Zimmer",
        year="2010",
        total_tracks=1,
        tracks=[track1]
    )

    track2 = Track(
        id="roja_1",
        track_number=1,
        title="Chinna Chinna Aasai",
        artist="A. R. Rahman, Minmini",
        album="Roja",
        movie="Roja",
        duration_ms=295000,
        duration_formatted="04:55",
        year="1992"
    )
    movie2 = MovieResult(
        movie_query="Roja",
        found=True,
        album_title="Roja",
        artist="A. R. Rahman",
        year="1992",
        total_tracks=1,
        tracks=[track2]
    )
    return [movie1, movie2]

class TestMovieApp(unittest.TestCase):

    def test_format_duration(self):
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(65000), "01:05")
        self.assertEqual(format_duration(295000), "04:55")
        self.assertEqual(format_duration(None), "00:00")

    def test_clean_movie_name(self):
        self.assertEqual(clean_movie_name("1. Inception"), "Inception")
        self.assertEqual(clean_movie_name(" 2) Roja "), "Roja")
        self.assertEqual(clean_movie_name('"Interstellar"'), "Interstellar")
        self.assertEqual(clean_movie_name("Leo"), "Leo")

    def test_export_as_csv(self):
        results = get_sample_movie_results()
        csv_out = export_as_csv(results)
        self.assertIn("Movie,Album,Track #", csv_out)
        self.assertIn("Inception,Inception (Music from the Motion Picture),1,Time", csv_out)
        self.assertIn("Roja,Roja,1,Chinna Chinna Aasai", csv_out)

    def test_export_as_txt(self):
        results = get_sample_movie_results()
        txt_out = export_as_txt(results)
        self.assertIn("MOVIE SOUNDTRACKS & SONGS EXPORT", txt_out)
        self.assertIn("MOVIE: INCEPTION (2010)", txt_out)
        self.assertIn("01. Time - Hans Zimmer [04:35]", txt_out)
        self.assertIn("MOVIE: ROJA (1992)", txt_out)
        self.assertIn("TOTAL MOVIES: 2 | TOTAL TRACKS: 2", txt_out)

    def test_export_as_json(self):
        results = get_sample_movie_results()
        json_out = export_as_json(results)
        parsed = json.loads(json_out)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["movie_query"], "Inception")
        self.assertEqual(parsed[1]["movie_query"], "Roja")

    def test_export_as_m3u(self):
        results = get_sample_movie_results()
        m3u_out = export_as_m3u(results)
        self.assertTrue(m3u_out.startswith("#EXTM3U"))
        self.assertIn("Hans Zimmer - Time", m3u_out)
        self.assertIn("A. R. Rahman, Minmini - Chinna Chinna Aasai", m3u_out)

    def test_fastapi_endpoints(self):
        client = TestClient(app)
        
        # 1. Test Root
        res_root = client.get("/")
        self.assertEqual(res_root.status_code, 200)

        # 2. Test Export Tracklist endpoint
        results = get_sample_movie_results()
        export_payload = {
            "results": [m.model_dump() for m in results],
            "format": "csv"
        }
        res_export = client.post("/api/export/tracklist", json=export_payload)
        self.assertEqual(res_export.status_code, 200)
        self.assertIn("text/csv", res_export.headers.get("content-type", ""))
        self.assertIn('attachment; filename="movie_soundtracks.csv"', res_export.headers.get("content-disposition", ""))
        self.assertIn("Time", res_export.text)
        # 3. Test Audio ZIP initiation with quality options
        audio_payload = {
            "results": [m.model_dump() for m in results],
            "audio_quality": "flac"
        }
        res_audio = client.post("/api/export/audio-zip", json=audio_payload)
        self.assertEqual(res_audio.status_code, 200)
        self.assertIn("task_id", res_audio.json())
        self.assertEqual(res_audio.json()["status"], "queued")

if __name__ == "__main__":
    unittest.main()
