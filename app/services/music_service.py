import asyncio
import re
import urllib.parse
from typing import Dict, List, Optional, Tuple, Set
import httpx
from app.models import MovieResult, Track
from app.services.exporter_service import format_duration

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
SAAVN_SEARCH_URL = "https://saavn.dev/api/search/albums"
SAAVN_ALBUM_URL = "https://saavn.dev/api/albums"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# In-memory search cache for zero-latency repeated queries
SEARCH_CACHE: Dict[str, MovieResult] = {}

KNOWN_LANGUAGES = ["telugu", "tamil", "hindi", "malayalam", "kannada", "english"]

# Common transliterations / typos in movie names
COMMON_ALIASES = {
    "jersy": "jersey",
    "bahubali": "baahubali",
    "kgf2": "kgf chapter 2",
    "pushpa2": "pushpa 2",
}

def clean_movie_name(name: str) -> str:
    """Normalize and clean user input movie title."""
    cleaned = re.sub(r"^[0-9]+[\.\-\)\s]+", "", name.strip())  # remove leading numbers like '1. Inception'
    cleaned = cleaned.strip("\"' \t\r\n")
    return cleaned

def extract_movie_and_language(movie_input: str, selected_language: Optional[str] = "all") -> Tuple[str, str]:
    """Extract base movie name and effective language (handling 'jersey telugu' or 'leo tamil')."""
    clean_input = clean_movie_name(movie_input)
    effective_lang = (selected_language or "all").strip().lower()

    # Check if user typed language at the end of the movie name
    for kl in KNOWN_LANGUAGES:
        pattern = r"\b" + kl + r"$"
        if re.search(pattern, clean_input, re.IGNORECASE):
            clean_input = re.sub(pattern, "", clean_input, flags=re.IGNORECASE).strip()
            if effective_lang == "all":
                effective_lang = kl
            break

    # Alias / typo fix
    m_lower = clean_input.lower()
    if m_lower in COMMON_ALIASES:
        clean_input = COMMON_ALIASES[m_lower]

    return clean_input, effective_lang

def upgrade_artwork_url(url: Optional[str]) -> Optional[str]:
    """Upgrade iTunes artwork URL to high-resolution (1000x1000)."""
    if not url:
        return None
    return re.sub(r"\d+x\d+bb\.", "1000x1000bb.", url)

def get_base_album_title(album_name: str) -> str:
    """Extract clean base title before parentheses or subtitle hyphens."""
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", album_name)
    s = s.split(" - ")[0].strip().lower()
    return s

def evaluate_soundtrack_album(album: dict, movie_name: str, language: str, is_from_lang_search: bool = False) -> int:
    """Score album strictly: MUST match movie name, prefer requested language and official OST."""
    aname = album.get("collectionName", "").lower()
    artist = album.get("artistName", "").lower()
    m_lower = movie_name.lower()
    base = get_base_album_title(album.get("collectionName", ""))
    
    # 1. STRICT MOVIE NAME CHECK
    pattern = r"\b" + re.escape(m_lower) + r"\b"
    if not re.search(pattern, aname) and not (m_lower in COMMON_ALIASES and COMMON_ALIASES[m_lower] in aname):
        return -999  # NEVER return an unrelated movie!

    # Penalize if base has extraneous words (e.g. 'vikram vedha' when searching 'vikram')
    if base != m_lower and len(base.split()) > len(m_lower.split()) and not m_lower.endswith(base):
        return -999

    score = 60
    if base == m_lower:
        score += 40

    if is_from_lang_search:
        score += 50

    # 2. LANGUAGE MATCHING & REGIONAL COMPOSERS
    if language and language != "all":
        lang_pattern = r"\b" + re.escape(language) + r"\b"
        if re.search(lang_pattern, aname):
            score += 70
        elif language == "telugu":
            if "telugu" in aname or "aditya music" in artist:
                score += 50
            # Telugu / South composer bonus
            if any(c in artist for c in ["anirudh", "devi sri prasad", "thaman", "keeravani", "mickey", "radhan"]):
                score += 40
            # Hindi remake penalty
            if any(c in artist for c in ["sachet", "parampara", "shellee", "mellow d"]):
                score -= 80
            elif "hindi" in aname or "tamil" in aname:
                score -= 60
        elif language == "tamil":
            if "tamil" in aname:
                score += 50
            if any(c in artist for c in ["anirudh", "rahman", "yuvan", "harris jayaraj", "santhosh narayanan", "gv prakash"]):
                score += 40
            elif "telugu" in aname or "hindi" in aname:
                score -= 60
        elif language == "hindi":
            if "hindi" in aname:
                score += 50
            if any(c in artist for c in ["sachet", "parampara", "pritam", "arijit", "vishal & shekhar", "sachin-jigar"]):
                score += 40
            elif "telugu" in aname or "tamil" in aname:
                score -= 60

    # 3. SOUNDTRACK TYPE PREFERENCE
    if "original motion picture soundtrack" in aname:
        score += 40
    elif "original background score" in aname or "background score" in aname:
        score += 25
    elif "soundtrack" in aname or "music from the motion picture" in aname:
        score += 25

    # 4. PENALIZE NON-ALBUM RELEASES & EPs vs Full OST
    tracks = album.get("trackCount", 0)
    if "- ep" in aname:
        score -= 25
    if "karaoke" in aname or "tribute" in aname:
        score -= 150
    if tracks == 1 and "single" in aname:
        score -= 40
    # Favor actual multi-song albums
    score += min(tracks * 2, 20)

    return score

async def fetch_itunes_tracks(client: httpx.AsyncClient, collection_id: int, country: str = "IN") -> List[dict]:
    """Fetch complete tracklist for an iTunes collection ID."""
    params = {
        "id": collection_id,
        "entity": "song",
        "limit": 100,
        "country": country
    }
    try:
        resp = await client.get(ITUNES_LOOKUP_URL, params=params, headers=HEADERS, timeout=6.0)
        if resp.status_code == 200:
            data = resp.json()
            return [item for item in data.get("results", []) if item.get("wrapperType") == "track"]
    except Exception:
        pass
    return []

async def search_movie_songs(movie_query: str, language: Optional[str] = "all", client: Optional[httpx.AsyncClient] = None) -> MovieResult:
    """Find the exact official album and its complete tracklist for a movie in the chosen language."""
    movie_name, effective_lang = extract_movie_and_language(movie_query, language)
    if not movie_name:
        return MovieResult(
            movie_query=movie_query,
            found=False,
            error="Empty movie name"
        )

    # Check cache
    cache_key = f"{movie_name.lower()}::{effective_lang}"
    if cache_key in SEARCH_CACHE:
        return SEARCH_CACHE[cache_key]

    owns_client = False
    if client is None:
        limits = httpx.Limits(max_keepalive_connections=15, max_connections=30)
        client = httpx.AsyncClient(limits=limits, timeout=10.0)
        owns_client = True

    try:
        # Run concurrent iTunes search queries
        lang_tasks = []
        general_tasks = []

        if effective_lang and effective_lang != "all":
            enc_lang = urllib.parse.quote(f"{movie_name} {effective_lang} soundtrack")
            lang_tasks.append(client.get(f"{ITUNES_SEARCH_URL}?term={enc_lang}&entity=album&limit=12&country=IN", headers=HEADERS))
            lang_tasks.append(client.get(f"{ITUNES_SEARCH_URL}?term={enc_lang}&entity=album&limit=10&country=US", headers=HEADERS))

        enc_general = urllib.parse.quote(f"{movie_name} soundtrack")
        general_tasks.append(client.get(f"{ITUNES_SEARCH_URL}?term={enc_general}&entity=album&limit=12&country=IN", headers=HEADERS))
        general_tasks.append(client.get(f"{ITUNES_SEARCH_URL}?term={enc_general}&entity=album&limit=10&country=US", headers=HEADERS))

        # Also search bare title
        enc_bare = urllib.parse.quote(movie_name)
        general_tasks.append(client.get(f"{ITUNES_SEARCH_URL}?term={enc_bare}&entity=album&limit=8&country=IN", headers=HEADERS))

        all_tasks = lang_tasks + general_tasks
        resps = await asyncio.gather(*all_tasks, return_exceptions=True)

        candidates: List[Tuple[dict, bool]] = []
        seen_collection_ids: Set[int] = set()

        for idx, resp in enumerate(resps):
            is_lang_q = idx < len(lang_tasks)
            if isinstance(resp, httpx.Response) and resp.status_code == 200:
                for alb in resp.json().get("results", []):
                    cid = alb.get("collectionId")
                    if cid and cid not in seen_collection_ids:
                        seen_collection_ids.add(cid)
                        candidates.append((alb, is_lang_q))

        # Score candidates strictly
        scored_albums: List[Tuple[int, dict]] = []
        for alb, is_lang_q in candidates:
            score = evaluate_soundtrack_album(alb, movie_name, effective_lang, is_from_lang_search=is_lang_q)
            if score > 0:
                scored_albums.append((score, alb))

        scored_albums.sort(key=lambda x: x[0], reverse=True)

        # If a valid official album was found on iTunes
        if scored_albums:
            best_score, best_album = scored_albums[0]
            collection_id = best_album.get("collectionId")
            album_title = best_album.get("collectionName", f"{movie_name} Soundtrack")
            artist_name = best_album.get("artistName", "Various Artists")
            year = (best_album.get("releaseDate") or "")[:4] or None
            artwork = upgrade_artwork_url(best_album.get("artworkUrl100"))

            # Fetch the exact tracks of THIS album
            raw_tracks = await fetch_itunes_tracks(client, collection_id)
            if raw_tracks:
                tracks: List[Track] = []
                for idx, item in enumerate(raw_tracks, start=1):
                    tname = item.get("trackName", f"Track {idx}").strip()
                    dur_ms = item.get("trackTimeMillis", 0)
                    art = upgrade_artwork_url(item.get("artworkUrl100")) or artwork
                    t_num = item.get("trackNumber", idx)

                    tracks.append(Track(
                        id=f"{movie_name}_{idx}",
                        track_number=t_num,
                        title=tname,
                        artist=item.get("artistName", artist_name),
                        album=album_title,
                        movie=movie_name,
                        duration_ms=dur_ms,
                        duration_formatted=format_duration(dur_ms),
                        preview_url=item.get("previewUrl"),
                        artwork_url=art,
                        year=year,
                        source="itunes"
                    ))

                result = MovieResult(
                    movie_query=movie_name,
                    found=True,
                    album_title=album_title,
                    artist=artist_name,
                    language=effective_lang.capitalize() if effective_lang != "all" else None,
                    year=year,
                    artwork_url=artwork,
                    total_tracks=len(tracks),
                    tracks=tracks
                )
                SEARCH_CACHE[cache_key] = result
                return result

        # Step 2: Fallback to JioSaavn if iTunes had no matching album
        try:
            saavn_query = f"{movie_name} {effective_lang}" if effective_lang != "all" else movie_name
            enc_saavn = urllib.parse.quote(saavn_query)
            saavn_resp = await client.get(f"{SAAVN_SEARCH_URL}?query={enc_saavn}&page=1&limit=5", headers=HEADERS, timeout=5.0)
            if saavn_resp.status_code == 200:
                results = saavn_resp.json().get("data", {}).get("results", [])
                for alb in results:
                    aname = alb.get("name", "").lower()
                    if movie_name.lower() in aname:
                        alb_id = alb.get("id")
                        alb_detail = await client.get(f"{SAAVN_ALBUM_URL}?id={alb_id}", headers=HEADERS, timeout=5.0)
                        if alb_detail.status_code == 200:
                            alb_data = alb_detail.json().get("data", {})
                            album_title = alb_data.get("name")
                            artist_name = alb_data.get("primaryArtists") or "Various Artists"
                            year = str(alb_data.get("year", "")) or None
                            imgs = alb_data.get("image", [])
                            artwork = imgs[-1].get("url") if isinstance(imgs, list) and imgs else None

                            songs = alb_data.get("songs", [])
                            if songs:
                                tracks: List[Track] = []
                                for idx, s in enumerate(songs, start=1):
                                    tname = s.get("name", f"Track {idx}").strip()
                                    dur_ms = int(s.get("duration", 0)) * 1000
                                    dl_urls = s.get("downloadUrl", [])
                                    dl_url = dl_urls[-1].get("url") if isinstance(dl_urls, list) and dl_urls else None

                                    tracks.append(Track(
                                        id=f"{movie_name}_{idx}",
                                        track_number=idx,
                                        title=tname,
                                        artist=s.get("primaryArtists") or artist_name,
                                        album=album_title,
                                        movie=movie_name,
                                        duration_ms=dur_ms,
                                        duration_formatted=format_duration(dur_ms),
                                        preview_url=dl_url,
                                        artwork_url=artwork,
                                        year=year,
                                        source="saavn"
                                    ))

                                result = MovieResult(
                                    movie_query=movie_name,
                                    found=True,
                                    album_title=album_title,
                                    artist=artist_name,
                                    language=effective_lang.capitalize() if effective_lang != "all" else None,
                                    year=year,
                                    artwork_url=artwork,
                                    total_tracks=len(tracks),
                                    tracks=tracks
                                )
                                SEARCH_CACHE[cache_key] = result
                                return result
        except Exception:
            pass

        # If completely not found, return clean error without returning false movies
        lang_msg = f" in {effective_lang.capitalize()}" if effective_lang != "all" else ""
        return MovieResult(
            movie_query=movie_name,
            found=False,
            error=f"No official soundtrack found for '{movie_name}'{lang_msg}. Please check the spelling or language."
        )

    except Exception as e:
        return MovieResult(
            movie_query=movie_name,
            found=False,
            error=f"Search error: {str(e)}"
        )
    finally:
        if owns_client:
            await client.aclose()

async def search_multiple_movies(movie_list: List[str], language: Optional[str] = "all") -> List[MovieResult]:
    """Search for multiple movies concurrently with the selected language filter."""
    clean_list = [clean_movie_name(m) for m in movie_list if clean_movie_name(m)]
    if not clean_list:
        return []

    limits = httpx.Limits(max_keepalive_connections=15, max_connections=30)
    async with httpx.AsyncClient(limits=limits, timeout=12.0) as client:
        tasks = [search_movie_songs(m, language=language, client=client) for m in clean_list]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)
