"""Poster und Hintergrundbilder – optional, daher steht das Abschalten im Vordergrund."""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import artwork

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\0" * 64


def settings_for(tmp_path, **extra):
    return {
        "movie_target": str(tmp_path / "movies"),
        "series_target": str(tmp_path / "series"),
        "anime_target": str(tmp_path / "anime"),
        "download_artwork": True,
        **extra,
    }


def movie_item(**extra):
    return {
        "src": "/in/film.mkv", "category": "movie", "is_subtitle": False, "guess": {},
        "match": {"provider": "tmdb", "id": 1, "title": "Der Pate",
                  "poster_url": "https://bilder/poster.jpg",
                  "fanart_url": "https://bilder/fanart.jpg"},
        **extra,
    }


def series_item(**extra):
    return {
        "src": "/in/dark.mkv", "category": "series", "is_subtitle": False,
        "guess": {"season": 2, "episodes": [5]},
        "thumb_url": "https://bilder/thumb.jpg",
        "match": {"provider": "tvdb", "id": 1, "title": "Dark",
                  "poster_url": "https://bilder/poster.jpg",
                  "fanart_url": "https://bilder/fanart.jpg",
                  "season_posters": {2: "https://bilder/s2.jpg"}},
        **extra,
    }


# --- Wohin die Bilder gehören ------------------------------------------------

def test_movie_in_own_folder(tmp_path):
    dest = tmp_path / "movies" / "Der Pate (1972)" / "Der Pate (1972).mkv"
    plan = artwork.targets(movie_item(), str(dest), settings_for(tmp_path))
    names = [p.name for _, p in plan]
    assert names == ["poster.jpg", "fanart.jpg"]
    assert all(p.parent == dest.parent for _, p in plan)


def test_movie_directly_in_target_gets_prefixed_names(tmp_path):
    """Ohne eigenen Ordner würde poster.jpg für alle Filme gelten – daher Präfix."""
    dest = tmp_path / "movies" / "Der Pate (1972).mkv"
    plan = artwork.targets(movie_item(), str(dest), settings_for(tmp_path))
    assert [p.name for _, p in plan] == \
        ["Der Pate (1972)-poster.jpg", "Der Pate (1972)-fanart.jpg"]


def test_series_artwork_lands_in_show_and_season_folder(tmp_path):
    dest = tmp_path / "series" / "Dark" / "Season 02" / "Dark - S02E05 - Lost.mkv"
    plan = artwork.targets(series_item(), str(dest), settings_for(tmp_path))
    by_name = {p.name: p for _, p in plan}
    show = tmp_path / "series" / "Dark"
    assert by_name["poster.jpg"].parent in (show, dest.parent)
    assert by_name["fanart.jpg"].parent == show
    assert by_name["season02-poster.jpg"].parent == show
    assert by_name["Dark - S02E05 - Lost-thumb.jpg"].parent == dest.parent


def test_season_poster_also_in_season_folder(tmp_path):
    dest = tmp_path / "series" / "Dark" / "Season 02" / "x.mkv"
    plan = artwork.targets(series_item(), str(dest), settings_for(tmp_path))
    season_targets = [p for url, p in plan if url.endswith("s2.jpg")]
    assert (tmp_path / "series" / "Dark" / "Season 02" / "poster.jpg") in season_targets


def test_missing_urls_produce_no_targets(tmp_path):
    item = movie_item(match={"provider": "tmdb", "id": 1, "title": "X"})
    dest = tmp_path / "movies" / "X (2020)" / "X (2020).mkv"
    assert artwork.targets(item, str(dest), settings_for(tmp_path)) == []


def test_anime_uses_its_own_target(tmp_path):
    item = series_item(category="anime")
    dest = tmp_path / "anime" / "Frieren" / "Frieren - 012.mkv"
    plan = artwork.targets(item, str(dest), settings_for(tmp_path))
    assert any(str(p).startswith(str(tmp_path / "anime" / "Frieren")) for _, p in plan)


# --- Herunterladen -----------------------------------------------------------

def run_download(items, destinations, settings, handler):
    async def go():
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        # Der Download nutzt einen eigenen Client; den ersetzen wir für den Test.
        artwork.httpx.AsyncClient = lambda **kw: real_client(transport=transport, **kw)
        try:
            return await artwork.download(items, destinations, settings)
        finally:
            artwork.httpx.AsyncClient = real_client
    return asyncio.run(go())


def image_handler(request):
    return httpx.Response(200, content=PNG, headers={"content-type": "image/jpeg"})


def test_disabled_by_default_downloads_nothing(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return image_handler(request)

    dest = tmp_path / "movies" / "Der Pate (1972)" / "Der Pate (1972).mkv"
    written = run_download([movie_item()], {"/in/film.mkv": str(dest)},
                           settings_for(tmp_path, download_artwork=False), handler)
    assert written == 0
    assert calls == []


def test_downloads_and_writes_files(tmp_path):
    dest = tmp_path / "movies" / "Der Pate (1972)" / "Der Pate (1972).mkv"
    written = run_download([movie_item()], {"/in/film.mkv": str(dest)},
                           settings_for(tmp_path), image_handler)
    assert written == 2
    assert (dest.parent / "poster.jpg").read_bytes() == PNG
    assert (dest.parent / "fanart.jpg").exists()


def test_existing_images_are_kept(tmp_path):
    dest = tmp_path / "movies" / "Der Pate (1972)" / "Der Pate (1972).mkv"
    dest.parent.mkdir(parents=True)
    (dest.parent / "poster.jpg").write_bytes(b"meins")
    written = run_download([movie_item()], {"/in/film.mkv": str(dest)},
                           settings_for(tmp_path), image_handler)
    assert written == 1                                   # nur fanart.jpg
    assert (dest.parent / "poster.jpg").read_bytes() == b"meins"


def test_subtitles_get_no_artwork(tmp_path):
    item = movie_item(is_subtitle=True)
    dest = tmp_path / "movies" / "Film" / "Film.srt"
    assert run_download([item], {"/in/film.mkv": str(dest)},
                        settings_for(tmp_path), image_handler) == 0


def test_html_error_page_is_not_saved(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"<html>Fehler</html>",
                              headers={"content-type": "text/html"})

    dest = tmp_path / "movies" / "Film" / "Film.mkv"
    assert run_download([movie_item()], {"/in/film.mkv": str(dest)},
                        settings_for(tmp_path), handler) == 0
    assert not (dest.parent / "poster.jpg").exists()


def test_server_error_is_survived(tmp_path):
    def handler(request):
        return httpx.Response(500)

    dest = tmp_path / "movies" / "Film" / "Film.mkv"
    assert run_download([movie_item()], {"/in/film.mkv": str(dest)},
                        settings_for(tmp_path), handler) == 0


def test_oversized_image_is_skipped(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"\0" * (artwork.MAX_BYTES + 1),
                              headers={"content-type": "image/jpeg"})

    dest = tmp_path / "movies" / "Film" / "Film.mkv"
    assert run_download([movie_item()], {"/in/film.mkv": str(dest)},
                        settings_for(tmp_path), handler) == 0


@pytest.mark.parametrize("dests", [{}, {"/anderer/pfad.mkv": "/x/y.mkv"}])
def test_files_that_were_not_moved_are_ignored(tmp_path, dests):
    assert run_download([movie_item()], dests, settings_for(tmp_path), image_handler) == 0
