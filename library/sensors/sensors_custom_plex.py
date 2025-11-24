from abc import ABC, abstractmethod
import os
import time
from typing import List

import requests
import urllib3
import yaml

# suppress InsecureRequestWarning when verify_ssl is False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Custom data classes must be implemented in this file, inherit the CustomDataSource and implement its 2 methods
class CustomDataSource(ABC):
    @abstractmethod
    def as_numeric(self) -> float:
        # Numeric value will be used for graph and radial progress bars
        # If there is no numeric value, keep this function empty
        pass

    @abstractmethod
    def as_string(self) -> str:
        # Text value will be used for text display and radial progress bar inner text
        # Numeric value can be formatted here to be displayed as expected
        # It is also possible to return a text unrelated to the numeric value
        # If this function is empty, the numeric value will be used as string without formatting
        pass

    def last_values(self) -> List[float]:
        # List of last numeric values will be used for plot graph
        # If you do not want to draw a line graph or if your custom data has no numeric values, keep this function empty
        return []

# =====================================================================
# CONFIG LOADING — ONLY "../../config.yaml"
# =====================================================================

def _load_root_config():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../config.yaml")
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}

# =====================================================================
# PLEX BASE + SENSORS
# =====================================================================

class PlexBaseSensor(CustomDataSource):
    def __init__(self, config=None):
        super().__init__()
        cfg = (_load_root_config().get("CUSTOM") or {}).get("PLEX", {}) or {}

        self.url = cfg.get("url", "").rstrip("/")
        self.token = cfg.get("token", "")
        self.headers = {"Accept": "application/json"}
        if self.token:
            self.headers["X-Plex-Token"] = self.token

        self._cache = {}
        self._last = {}
        self._ttl = int(cfg.get("cache_ttl", 30))

    def _plex_get(self, ep):
        if not self.url:
            return None
        try:
            r = requests.get(f"{self.url}{ep}", headers=self.headers, timeout=6)
            if r.status_code == 200:
                return r.json()
        except:
            pass
        return None

    def _cached(self, key, fn):
        now = time.time()
        if key in self._cache and (now - self._last.get(key, 0)) < self._ttl:
            return self._cache[key]
        v = fn()
        self._cache[key] = v
        self._last[key] = now
        return v



class PlexStreamsSensor(PlexBaseSensor):
    def as_numeric(self):
        def fn():
            j = self._plex_get("/status/sessions") or {}
            mc = j.get("MediaContainer", {})
            return float(mc.get("size", 0))
        return self._cached("streams", fn)
    def as_string(self):
        return f"{int(self._cache.get('streams', 0))} streams"


class PlexMovieCountSensor(PlexBaseSensor):
    def as_numeric(self):
        def fn():
            sec = self._plex_get("/library/sections") or {}
            dirs = sec.get("MediaContainer", {}).get("Directory", [])
            total = 0
            for d in dirs:
                if d.get("type") == "movie":
                    key = d.get("key")
                    if key:
                        j = self._plex_get(f"/library/sections/{key}/all") or {}
                        total += int(j.get("MediaContainer", {}).get("size", 0))
            return float(total)
        return self._cached("plex_movies", fn)
    def as_string(self):
        return f"{int(self._cache.get('plex_movies', 0))} movies"


class PlexTVShowCountSensor(PlexBaseSensor):
    def as_numeric(self):
        def fn():
            sec = self._plex_get("/library/sections") or {}
            dirs = sec.get("MediaContainer", {}).get("Directory", [])
            t = 0
            for d in dirs:
                if d.get("type") == "show":
                    key = d.get("key")
                    j = self._plex_get(f"/library/sections/{key}/all") or {}
                    t += int(j.get("MediaContainer", {}).get("size", 0))
            return float(t)
        return self._cached("plex_shows", fn)
    def as_string(self):
        return f"{int(self._cache.get('plex_shows', 0))} shows"


class PlexEpisodesCountSensor(PlexBaseSensor):
    def as_numeric(self):
        def fn():
            sec = self._plex_get("/library/sections") or {}
            dirs = sec.get("MediaContainer", {}).get("Directory", [])
            t = 0
            for d in dirs:
                if d.get("type") == "show":
                    key = d.get("key")
                    j = self._plex_get(f"/library/sections/{key}/all?type=4") or {}
                    t += int(j.get("MediaContainer", {}).get("size", 0))
            return float(t)
        return self._cached("plex_eps", fn)
    def as_string(self):
        return f"{int(self._cache.get('plex_eps', 0))} episodes"


class PlexAlbumCountSensor(PlexBaseSensor):
    def as_numeric(self):
        def fn():
            sec = self._plex_get("/library/sections") or {}
            dirs = sec.get("MediaContainer", {}).get("Directory", [])
            t = 0
            for d in dirs:
                if d.get("type") == "artist":
                    key = d.get("key")
                    j = self._plex_get(f"/library/sections/{key}/all?type=8") or {}
                    t += int(j.get("MediaContainer", {}).get("size", 0))
            return float(t)
        return self._cached("plex_alb", fn)
    def as_string(self):
        return f"{int(self._cache.get('plex_alb', 0))} albums"


class PlexSongsCountSensor(PlexBaseSensor):
    def as_numeric(self):
        def fn():
            sec = self._plex_get("/library/sections") or {}
            dirs = sec.get("MediaContainer", {}).get("Directory", [])
            t = 0
            for d in dirs:
                if d.get("type") == "artist":
                    key = d.get("key")
                    j = self._plex_get(f"/library/sections/{key}/all?type=10") or {}
                    t += int(j.get("MediaContainer", {}).get("size", 0))
            return float(t)
        return self._cached("plex_sng", fn)
    def as_string(self):
        return f"{int(self._cache.get('plex_sng', 0))} songs"
