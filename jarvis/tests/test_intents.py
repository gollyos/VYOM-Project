"""Comprehensive test suite for JARVIS Desktop Assistant.

Tests database CRUD, text helpers, regex intent matching,
intent handlers with mocked subsystems, and fallback behaviors.
"""

from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from jarvis.backend import db, helper, router
from jarvis.backend.intents import (
    chat,
    communication,
    info,
    open_close,
    search,
    system,
)


import tempfile

@pytest.fixture
def temp_db():
    """Create an isolated temporary SQLite database for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    test_db_path = tmp.name
    db.init_db(test_db_path)
    yield test_db_path
    try:
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
    except Exception:
        pass


class TestDatabase:
    """Test SQLite database operations."""

    def test_init_db_creates_tables(self, temp_db):
        conn = db.get_conn(temp_db)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cur.fetchall()}
        conn.close()

        assert "contacts" in tables
        assert "app_paths" in tables
        assert "command_history" in tables

    def test_contact_crud(self, temp_db):
        # Insert
        c_id = db.add_contact("Tony Stark", "+1234567890", "tony@stark.com", db_path=temp_db)
        assert c_id > 0

        # Find exact & partial
        phone = db.find_contact_number("Tony Stark", db_path=temp_db)
        assert phone == "+1234567890"

        phone_partial = db.find_contact_number("tony", db_path=temp_db)
        assert phone_partial == "+1234567890"

        # Not found
        assert db.find_contact_number("Pepper Potts", db_path=temp_db) is None

        # List all
        all_contacts = db.get_all_contacts(db_path=temp_db)
        assert len(all_contacts) == 1
        assert all_contacts[0]["name"] == "Tony Stark"

    def test_app_paths_crud(self, temp_db):
        db.register_app_path("blender", "C:/Program Files/Blender/blender.exe", db_path=temp_db)
        path = db.get_app_path("blender", db_path=temp_db)
        assert path == "C:/Program Files/Blender/blender.exe"

        # Update
        db.register_app_path("blender", "D:/Blender/blender.exe", db_path=temp_db)
        updated_path = db.get_app_path("blender", db_path=temp_db)
        assert updated_path == "D:/Blender/blender.exe"

    def test_command_history(self, temp_db):
        log_id = db.log_command("open chrome", "Opening Chrome, sir.", db_path=temp_db)
        assert log_id > 0

        history = db.get_recent_history(limit=10, db_path=temp_db)
        assert len(history) == 1
        assert history[0]["query"] == "open chrome"
        assert history[0]["response"] == "Opening Chrome, sir."


class TestHelper:
    """Test text preprocessing and query extractors."""

    def test_clean_query(self):
        assert helper.clean_query("  Open   NOTEPAD  ") == "open notepad"
        assert helper.clean_query("") == ""

    def test_remove_words(self):
        text = "jarvis please open the application chrome"
        cleaned = helper.remove_words(text, ["jarvis", "please", "the", "application"])
        assert cleaned == "open chrome"

    def test_extract_yt_term(self):
        assert helper.extract_yt_term("jarvis play lofi hip hop on youtube") == "lofi hip hop"
        assert helper.extract_yt_term("play song Shape of You") == "shape of you"

    def test_extract_search_term(self):
        assert helper.extract_search_term("google search quantum computing") == "quantum computing"
        assert helper.extract_search_term("jarvis search for best laptops 2026") == "best laptops 2026"

    def test_extract_wikipedia_query(self):
        assert helper.extract_wikipedia_query("who is Albert Einstein") == "albert einstein"
        assert helper.extract_wikipedia_query("tell me about Artificial Intelligence") == "artificial intelligence"

    def test_extract_app_name(self):
        assert helper.extract_app_name("jarvis open chrome") == "chrome"
        assert helper.extract_app_name("close notepad") == "notepad"

    def test_extract_contact_and_message(self):
        name, msg = helper.extract_contact_and_message("send whatsapp message to John hello there")
        assert name.lower() == "john"
        assert "hello there" in msg.lower()


class TestIntentHandlers:
    """Test individual intent handlers with mocked side-effects."""

    @patch("webbrowser.open")
    def test_handle_search(self, mock_web_open):
        res = search.handle_search("search google for python tutorial")
        assert "python tutorial" in res.lower()
        mock_web_open.assert_called_once()

    @patch("jarvis.backend.intents.search.webbrowser.open")
    def test_handle_youtube(self, mock_web_open):
        res = search.handle_youtube("play interstellar theme on youtube")
        assert "interstellar theme" in res.lower()

    @patch("jarvis.backend.intents.open_close.webbrowser.open")
    def test_handle_open_website(self, mock_web_open):
        res = open_close.handle_open("open youtube")
        assert "youtube" in res.lower()
        mock_web_open.assert_called_with("https://www.youtube.com")

    @patch("jarvis.backend.intents.open_close.subprocess.run")
    def test_handle_close_allowed_app(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        res = open_close.handle_close("close notepad")
        assert "closed notepad" in res.lower()

    def test_handle_close_disallowed(self):
        res = open_close.handle_close("close critical_system_process")
        assert "not permitted" in res.lower()

    @patch("jarvis.backend.intents.info.get_weather")
    def test_handle_weather(self, mock_get_weather):
        mock_get_weather.return_value = "The temperature in Mumbai is 28°C."
        res = info.handle_weather("weather in Mumbai")
        assert "28°c" in res.lower()

    def test_handle_time(self):
        res = info.handle_time("what is the time")
        assert "current time is" in res.lower()

    @patch("psutil.sensors_battery")
    def test_handle_system_status_battery(self, mock_battery):
        mock_bat_obj = MagicMock()
        mock_bat_obj.percent = 85
        mock_bat_obj.power_plugged = True
        mock_battery.return_value = mock_bat_obj

        res = system.handle_system_status("battery status")
        assert "85%" in res
        assert "plugged in" in res

    def test_chat_rule_fallback(self):
        res = chat.llm_fallback("hello jarvis")
        assert "assist you" in res.lower() or "hello" in res.lower()


class TestRouter:
    """Test top-level router pattern matching and fallback dispatch."""

    def test_route_youtube(self, temp_db):
        with patch("jarvis.backend.intents.search.handle_youtube", return_value="Playing song on YouTube"):
            res = router.route("play believer on youtube", db_path=temp_db)
            assert res == "Playing song on YouTube"

    def test_route_open(self, temp_db):
        with patch("jarvis.backend.intents.open_close.handle_open", return_value="Opening Spotify, sir."):
            res = router.route("open Spotify", db_path=temp_db)
            assert res == "Opening Spotify, sir."

    def test_route_weather(self, temp_db):
        with patch("jarvis.backend.intents.info.handle_weather", return_value="Weather is sunny."):
            res = router.route("what is the weather today", db_path=temp_db)
            assert res == "Weather is sunny."

    def test_route_battery(self, temp_db):
        with patch("jarvis.backend.intents.system.handle_system_status", return_value="Battery is 90%"):
            res = router.route("check battery", db_path=temp_db)
            assert res == "Battery is 90%"

    def test_route_time(self, temp_db):
        with patch("jarvis.backend.intents.info.handle_time", return_value="The current time is 02:30 PM"):
            res = router.route("what time is it", db_path=temp_db)
            assert res == "The current time is 02:30 PM"

    def test_route_llm_fallback(self, temp_db):
        with patch("jarvis.backend.intents.chat.llm_fallback", return_value="I am feeling great!"):
            res = router.route("how are you doing my friend", db_path=temp_db)
            assert res == "I am feeling great!"
