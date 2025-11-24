import os
import time
import yaml
import requests
import urllib3
from abc import ABC, abstractmethod
from typing import List

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

    @abstractmethod
    def last_values(self) -> List[float]:
        # List of last numeric values will be used for plot graph
        # If you do not want to draw a line graph or if your custom data has no numeric values, keep this function empty
        pass

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
        self._hist = []

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

    def _push(self, v):
        self._hist.append(v)
        if len(self._hist) > 200:
            self._hist.pop(0)

    def last_values(self):
        return self._hist[-40:]


class PlexStreamsSensor(PlexBaseSensor):
    def as_numeric(self):
        def fn():
            j = self._plex_get("/status/sessions") or {}
            mc = j.get("MediaContainer", {})
            return float(mc.get("size", 0))
        v = self._cached("streams", fn)
        self._push(v)
        return v
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
        v = self._cached("plex_movies", fn)
        self._push(v)
        return v
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
        v = self._cached("plex_shows", fn)
        self._push(v)
        return v
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
        v = self._cached("plex_eps", fn)
        self._push(v)
        return v
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
        v = self._cached("plex_alb", fn)
        self._push(v)
        return v
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
        v = self._cached("plex_sng", fn)
        self._push(v)
        return v
    def as_string(self):
        return f"{int(self._cache.get('plex_sng', 0))} songs"


# =====================================================================
# PROXMOX BASE + UPDATED SENSORS + NEW UPTIME SENSOR
# =====================================================================

class ProxmoxBaseSensor(CustomDataSource):
    """ Proxmox base class using API token only """
    def __init__(self, config=None):
        super().__init__()
        root = _load_root_config()
        prox = (root.get("CUSTOM") or {}).get("PROXMOX", {}) or {}
        cfg = config or {}

        self.host = cfg.get("host") or prox.get("host") or ""
        self.username = cfg.get("username") or prox.get("username")
        self.token_id = cfg.get("token_id") or prox.get("token_id")
        self.token_secret = cfg.get("token_secret") or prox.get("token_secret") or ""
        self.node = cfg.get("node") or prox.get("node") or "pve"
        self.verify_ssl = bool(cfg.get("verify_ssl", prox.get("verify_ssl", True)))
        self.cache_ttl = int(cfg.get("cache_ttl", prox.get("cache_ttl", 30)))

        self.api_base = self.host.rstrip("/") + "/api2/json" if self.host else ""
        self.headers = {"Accept": "application/json"}

        if self.token_id and self.token_secret:
            if "!" in self.token_id:
                token_full = f"{self.token_id}={self.token_secret}"
            else:
                token_full = f"{self.username}!{self.token_id}={self.token_secret}"
            self.headers["Authorization"] = f"PVEAPIToken={token_full}"

        self._cache = {}
        self._last = {}
        self._hist = []

    def _pmx_get(self, ep):
        try:
            r = requests.get(
                f"{self.api_base}{ep}",
                headers=self.headers,
                timeout=6,
                verify=self.verify_ssl
            )
            if r.status_code == 200:
                return r.json().get("data")
            print(f"[PROXMOX] HTTP {r.status_code} for {ep}")
        except Exception as e:
            print(f"[PROXMOX] ERROR: {e}")
        return None

    def _cached(self, key, fn):
        now = time.time()
        if key in self._cache and (now - self._last.get(key, 0)) < self.cache_ttl:
            return self._cache[key]
        v = fn()
        self._cache[key] = v
        self._last[key] = now
        return v

    def _push(self, v):
        self._hist.append(v)
        print("Pushed value:", v)
        print("History length:", len(self._hist))
        if len(self._hist) > 200:
            self._hist.pop(0)

    def last_values(self):
        return self._hist[-40:]


# ------------------------------
# NODE CPU
# ------------------------------

class ProxmoxNodeCPUUsageSensor(ProxmoxBaseSensor):
    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/status") or {}
        cpu = d.get("cpu")
        try:
            return float(cpu) * 100.0
        except:
            return 0.0

    def as_numeric(self):
        v = self._cached(f"nodecpu_{self.node}", self._calc)
        self._push(v)
        return v

    def as_string(self):
        return f"{self._cache.get(f'nodecpu_{self.node}', 0):.1f} %"


# ------------------------------
# NODE MEMORY
# ------------------------------

class ProxmoxNodeMemoryUsageSensor(ProxmoxBaseSensor):
    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/status") or {}
        mem = d.get("memory") or {}
        try:
            used = float(mem.get("used", 0))
            total = float(mem.get("total", 1))
            return used / total * 100.0
        except:
            return 0.0

    def as_numeric(self):
        v = self._cached(f"nodemem_{self.node}", self._calc)
        self._push(v)
        return v

    def as_string(self):
        return f"{self._cache.get(f'nodemem_{self.node}', 0):.1f} %"


# ------------------------------
# NODE DISK
# ------------------------------

class ProxmoxNodeDiskUsageSensor(ProxmoxBaseSensor):
    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/status") or {}
        rootfs = d.get("rootfs") or {}
        try:
            total = float(rootfs.get("total", 0))
            used = float(rootfs.get("used", 0))
            return used / total * 100.0 if total else 0.0
        except:
            return 0.0

    def as_numeric(self):
        v = self._cached(f"nodedsk_{self.node}", self._calc)
        self._push(v)
        return v

    def as_string(self):
        return f"{self._cache.get(f'nodedsk_{self.node}', 0):.1f} %"


# ------------------------------
# NODE UPTIME (NEW)
# ------------------------------

class ProxmoxNodeUptimeSensor(ProxmoxBaseSensor):
    """ Returns uptime in hours (numeric) + 'Xd Yh Zm' string """
    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/status") or {}
        return float(d.get("uptime", 0))

    def as_numeric(self):  # used for graphs
        sec = self._cached(f"nodeupt_{self.node}", self._calc)
        hrs = sec / 3600.0
        self._push(hrs)
        return hrs

    def as_string(self):
        sec = self._cache.get(f"nodeupt_{self.node}", 0)
        d = int(sec // 86400)
        h = int((sec % 86400) // 3600)
        m = int((sec % 3600) // 60)
        return f"{d}d {h}h {m}m"

# ------------------------------
# NODE NETWORK (NEW)
# ------------------------------

class ProxmoxNodeNetworkSensor(ProxmoxBaseSensor):
    """ Returns total network traffic in MB (numeric) + 'X.Y MB' string """
    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/netstat") or []
        print("Network data:", d)
        total_rx = 0.0
        total_tx = 0.0
        for iface in d:
            total_rx += float(iface.get("in", 0))
            total_tx += float(iface.get("out", 0))
        total_mb = (total_rx + total_tx) / (1024 * 1024)
        return total_mb

    def as_numeric(self):  # used for graphs
        mb = self._cached(f"nodenet_{self.node}", self._calc)
        self._push(mb)
        return mb

    def as_string(self):
        mb = self._cache.get(f"nodenet_{self.node}", 0)
        return f"{mb:.1f} MB"


# ------------------------------
# VM COUNT
# ------------------------------

class ProxmoxVMCountSensor(ProxmoxBaseSensor):
    def _calc(self):
        q = self._pmx_get(f"/nodes/{self.node}/qemu") or []
        return float(len(q))

    def as_numeric(self):
        v = self._cached(f"vmcnt_{self.node}", self._calc)
        self._push(v)
        return v

    def as_string(self):
        return f"{int(self._cache.get(f'vmcnt_{self.node}', 0))} VMs"


# ------------------------------
# LXC COUNT
# ------------------------------

class ProxmoxLXCCountSensor(ProxmoxBaseSensor):
    def _calc(self):
        q = self._pmx_get(f"/nodes/{self.node}/lxc") or []
        return float(len(q))

    def as_numeric(self):
        v = self._cached(f"lxccnt_{self.node}", self._calc)
        self._push(v)
        return v

    def as_string(self):
        return f"{int(self._cache.get(f'lxccnt_{self.node}', 0))} LXC"


# ------------------------------
# VM CPU
# ------------------------------

class ProxmoxVMCPUUsageSensor(ProxmoxBaseSensor):
    def __init__(self, config=None):
        super().__init__(config)
        self.vmid = int((config or {}).get("vm_id", 0))

    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/qemu/{self.vmid}/status/current") or {}
        cpu = d.get("cpu")
        try:
            return float(cpu) * 100.0
        except:
            return 0.0

    def as_numeric(self):
        v = self._cached(f"vmcpu_{self.node}_{self.vmid}", self._calc)
        self._push(v)
        return v

    def as_string(self):
        return f"{self._cache.get(f'vmcpu_{self.node}_{self.vmid}', 0):.1f} %"


# ------------------------------
# VM MEMORY
# ------------------------------

class ProxmoxVMMemoryUsageSensor(ProxmoxBaseSensor):
    def __init__(self, config=None):
        super().__init__(config)
        self.vmid = int((config or {}).get("vm_id", 0))

    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/qemu/{self.vmid}/status/current") or {}
        try:
            used = float(d.get("mem", 0))
            total = float(d.get("maxmem", 1))
            return used / total * 100.0
        except:
            return 0.0

    def as_numeric(self):
        v = self._cached(f"vmmem_{self.node}_{self.vmid}", self._calc)
        self._push(v)
        return v

    def as_string(self):
        return f"{self._cache.get(f'vmmem_{self.node}_{self.vmid}', 0):.1f} %"
