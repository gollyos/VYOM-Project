"""Information intent handlers: Weather, News, Time, and IP details.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)


def get_weather(city: str = "Delhi") -> str:
    """Fetch live weather for city using OpenWeatherMap or Open-Meteo free API."""
    clean_city = city.strip() or "Delhi"
    api_key = os.getenv("OPENWEATHERMAP_API_KEY", "").strip()

    # 1. Try OpenWeatherMap if key is provided
    if api_key:
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={urllib.parse.quote(clean_city)}&appid={api_key}&units=metric"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                temp = data["main"]["temp"]
                desc = data["weather"][0]["description"]
                humidity = data["main"]["humidity"]
                return f"In {clean_city}, the temperature is currently {temp:.1f}°C with {desc} and {humidity}% humidity, sir."
        except Exception as exc:
            logger.warning("OpenWeatherMap request failed: %s", exc)

    # 2. Free Open-Meteo API fallback (No API key needed!)
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(clean_city)}&count=1&language=en&format=json"
        geo_resp = requests.get(geo_url, timeout=5)
        if geo_resp.status_code == 200:
            geo_data = geo_resp.json()
            if "results" in geo_data and len(geo_data["results"]) > 0:
                loc = geo_data["results"][0]
                lat = loc["latitude"]
                lon = loc["longitude"]
                name = loc.get("name", clean_city)
                country = loc.get("country", "")

                forecast_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code&wind_speed_unit=kmh"
                forecast_resp = requests.get(forecast_url, timeout=5)
                if forecast_resp.status_code == 200:
                    f_data = forecast_resp.json()
                    curr = f_data.get("current", {})
                    temp = curr.get("temperature_2m", "--")
                    hum = curr.get("relative_humidity_2m", "--")
                    return f"The current temperature in {name}{f', {country}' if country else ''} is {temp}°C with {hum}% humidity, sir."
    except Exception as exc:
        logger.warning("Open-Meteo fallback failed: %s", exc)

    return f"I could not retrieve the weather information for {clean_city} right now, sir."


def handle_weather(query: str) -> str:
    """Parse city name from weather query and return conditions."""
    cleaned = re.sub(r"\b(what is the|tell me the|check|weather|temperature|in|for|at|today|forecast|jarvis)\b", " ", query, flags=re.IGNORECASE)
    city = re.sub(r"\s+", " ", cleaned).strip()
    return get_weather(city or "Delhi")


def get_news(topic: str = "") -> str:
    """Fetch top 3 news headlines via NewsAPI or Google News RSS."""
    api_key = os.getenv("NEWS_API_KEY", "").strip()

    if api_key:
        try:
            url = f"https://newsapi.org/v2/top-headlines?country=in&apiKey={api_key}" if not topic else f"https://newsapi.org/v2/everything?q={urllib.parse.quote(topic)}&sortBy=publishedAt&apiKey={api_key}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                articles = resp.json().get("articles", [])[:3]
                if articles:
                    lines = [f"{i+1}. {a.get('title', '')} ({a.get('source', {}).get('name', 'News')})" for i, a in enumerate(articles)]
                    return "Here are the top headlines, sir:\n" + "\n".join(lines)
        except Exception as exc:
            logger.warning("NewsAPI request failed: %s", exc)

    # Free RSS fallback via Google News RSS
    try:
        rss_query = urllib.parse.quote(topic) if topic else "technology"
        rss_url = f"https://news.google.com/rss/search?q={rss_query}&hl=en-IN&gl=IN&ceid=IN:en" if topic else "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
        resp = requests.get(rss_url, timeout=6)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            items = root.findall("./channel/item")[:3]
            headlines = []
            for i, item in enumerate(items):
                title = item.findtext("title", "")
                if title:
                    headlines.append(f"{i+1}. {title}")
            if headlines:
                return "Here are the top news updates, sir:\n" + "\n".join(headlines)
    except Exception as exc:
        logger.warning("Google News RSS fallback failed: %s", exc)

    return "I am currently unable to fetch the latest news headlines, sir."


def handle_news(query: str) -> str:
    """Parse news query and return headlines."""
    cleaned = re.sub(r"\b(tell me the|what is the|give me|latest|top|news|headlines|updates|about|for|jarvis)\b", " ", query, flags=re.IGNORECASE)
    topic = re.sub(r"\s+", " ", cleaned).strip()
    return get_news(topic)


def handle_time(query: str = "") -> str:
    """Return formatted current time, date, and day."""
    now = datetime.datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%A, %B %d, %Y")
    if "date" in query.lower() or "day" in query.lower():
        return f"Today is {date_str}, and the time is {time_str}, sir."
    return f"The current time is {time_str}, sir."


def handle_ip(query: str = "") -> str:
    """Fetch public IP address."""
    try:
        resp = requests.get("https://api.ipify.org?format=json", timeout=4)
        if resp.status_code == 200:
            ip = resp.json().get("ip", "")
            return f"Your public IP address is {ip}, sir."
    except Exception as exc:
        logger.warning("IP lookup failed: %s", exc)
    return "I could not retrieve your external IP address at the moment, sir."
