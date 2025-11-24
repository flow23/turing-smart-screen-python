from abc import ABC, abstractmethod
import os
import time
from typing import List

import requests
import urllib3
import yaml

from library.sensors.sensors_custom import CustomDataSource

# suppress InsecureRequestWarning when verify_ssl is False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
# PROXMOX BASE + UPDATED SENSORS + NEW UPTIME SENSOR
# =====================================================================

class ProxmoxBaseSensor(CustomDataSource):
    """ Proxmox base class using API token only """

    def __init__(self, config=None):
        root = _load_root_config()
        prox = (root.get("CUSTOM") or {}).get("PROXMOX", {}) or {}
        cfg = config or {}
        super().__init__()

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
        # only update cache if fetch succeeded
        if v is None:
            return self._cache.get(key)
            
        self._cache[key] = v
        self._last[key] = now
        return v


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
        return self._cached(f"nodecpu_{self.node}", self._calc)

    def as_string(self):
        return f"{self._cache.get(f'nodecpu_{self.node}', 0):.1f} %"
    
    def last_values(self) -> List[float]:
        return [self._cache.get(f'nodecpu_{self.node}', 0)]


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
        return self._cached(f"nodemem_{self.node}", self._calc)

    def as_string(self):
        return f"{self._cache.get(f'nodemem_{self.node}', 0):.1f} %"    

    def last_values(self) -> List[float]:
        return [self._cache.get(f'nodemem_{self.node}', 0)]


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
        return self._cached(f"nodedsk_{self.node}", self._calc)

    def as_string(self):
        return f"{self._cache.get(f'nodedsk_{self.node}', 0):.1f} %"    

    def last_values(self) -> List[float]:
        return [self._cache.get(f'nodedsk_{self.node}', 0)]


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
        return sec / 3600.0

    def as_string(self):
        sec = self._cache.get(f"nodeupt_{self.node}", 0)
        d = int(sec // 86400)
        h = int((sec % 86400) // 3600)
        m = int((sec % 3600) // 60)
        return f"{d}d {h}h {m}m"
    
    def last_values(self) -> List[float]:
        return [self._cache.get(f'nodeupt_{self.node}', 0)]


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
        return self._cached(f"nodenet_{self.node}", self._calc)

    def as_string(self):
        mb = self._cache.get(f"nodenet_{self.node}", 0)
        return f"{mb:.1f} MB"

    def last_values(self) -> List[float]:
        return [self._cache.get(f'nodenet_{self.node}', 0)]


# ------------------------------
# VM COUNT
# ------------------------------

class ProxmoxVMCountSensor(ProxmoxBaseSensor):
    def _calc(self):
        q = self._pmx_get(f"/nodes/{self.node}/qemu") or []
        return float(len(q))

    def as_numeric(self):
        return self._cached(f"vmcnt_{self.node}", self._calc)

    def as_string(self):
        return f"{int(self._cache.get(f'vmcnt_{self.node}', 0))} VMs"

    def last_values(self) -> List[float]:
        return [self._cache.get(f'vmcnt_{self.node}', 0)]


# ------------------------------
# LXC COUNT
# ------------------------------

class ProxmoxLXCCountSensor(ProxmoxBaseSensor):
    def _calc(self):
        q = self._pmx_get(f"/nodes/{self.node}/lxc") or []
        return float(len(q))

    def as_numeric(self):
        return self._cached(f"lxccnt_{self.node}", self._calc)

    def as_string(self):
        return f"{int(self._cache.get(f'lxccnt_{self.node}', 0))} LXC"


    def last_values(self) -> List[float]:
        return [self._cache.get(f'lxccnt_{self.node}', 0)]


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
        return self._cached(f"vmcpu_{self.node}_{self.vmid}", self._calc)

    def as_string(self):
        return f"{self._cache.get(f'vmcpu_{self.node}_{self.vmid}', 0):.1f} %"

    def last_values(self) -> List[float]:
        return [self._cache.get(f'vmcpu_{self.node}_{self.vmid}', 0)]


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
        return self._cached(f"vmmem_{self.node}_{self.vmid}", self._calc)

    def as_string(self):
        return f"{self._cache.get(f'vmmem_{self.node}_{self.vmid}', 0):.1f} %"

    def last_values(self) -> List[float]:
        return [self._cache.get(f'vmmem_{self.node}_{self.vmid}', 0)]       