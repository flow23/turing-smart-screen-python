from abc import ABC, abstractmethod
import os
import time
from typing import Dict, List
from functools import lru_cache

import requests
import urllib3
import yaml

from library.log import logger
from library.sensors.sensors_custom import CustomDataSource

# suppress InsecureRequestWarning when verify_ssl is False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =====================================================================
# CONFIG LOADING — ONLY "../../config.yaml"
# =====================================================================

@lru_cache(maxsize=1)
def _load_root_config():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../config.yaml")
    logger.debug(f"[PROXMOX] Loading config from {path}")
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
            logger.debug(f"[PROXMOX] HTTP {r.status_code} for {ep}")
        except Exception as e:
            logger.debug(f"[PROXMOX] ERROR: {e}")
        return None

    def _cluster_nodes(self) -> List[str]:
        """
        Return node names participating in the cluster.

        We prefer `/nodes` because it's simple and returns the node list; if it fails,
        we fall back to the configured `node` value.
        """
        nodes = self._pmx_get("/nodes") or []
        out: List[str] = []
        if isinstance(nodes, list):
            for n in nodes:
                if isinstance(n, dict):
                    name = n.get("node") or n.get("name")
                    if name:
                        out.append(str(name))
        out = sorted(set(out))
        if not out and self.node:
            out = [self.node]
        return out

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
# CLUSTER CPU (AGGREGATED)
# ------------------------------

class ProxmoxClusterCPUUsageSensor(ProxmoxBaseSensor):
    _history_store: Dict[str, List[int]] = {}
    _history_size = 50

    def _history_key(self) -> str:
        return self.api_base or "cluster"

    def _remember(self, value: int):
        hist = self._history_store.setdefault(self._history_key(), [])
        hist.append(int(value))
        if len(hist) > self._history_size:
            hist.pop(0)

    def _calc(self):
        nodes = self._cached("cluster_nodes", self._cluster_nodes) or []
        if not nodes:
            return 0

        weighted_cpu = 0.0
        total_weight = 0.0

        for n in nodes:
            d = self._pmx_get(f"/nodes/{n}/status") or {}
            cpu = d.get("cpu")
            if cpu is None:
                continue

            # Use CPU core/thread count if available for a more accurate aggregation.
            cpuinfo = d.get("cpuinfo") or {}
            weight = cpuinfo.get("cpus") or cpuinfo.get("cores") or 1

            try:
                weighted_cpu += float(cpu) * float(weight)
                total_weight += float(weight)
            except Exception:
                continue

        if total_weight <= 0:
            return 0

        cluster_fraction = weighted_cpu / total_weight
        return int(round(cluster_fraction * 100, 0))

    def as_numeric(self):
        key = f"cluster_cpu_{self._history_key()}"
        value = self._cached(key, self._calc)
        if value is not None:
            self._remember(value)
        return value

    def as_string(self):
        key = f"cluster_cpu_{self._history_key()}"
        return f"{self._cache.get(key, 0)}%"

    def last_values(self) -> List[int]:
        hist = self._history_store.get(self._history_key(), [])
        if not hist:
            current = self._cache.get(f"cluster_cpu_{self._history_key()}", None)
            if current is not None:
                self._remember(current)
            hist = self._history_store.get(self._history_key(), [])
        return hist[-self._history_size:]


# ------------------------------
# CLUSTER MEMORY (AGGREGATED)
# ------------------------------

class ProxmoxClusterMemoryUsageSensor(ProxmoxBaseSensor):
    _history_store: Dict[str, List[int]] = {}
    _history_size = 50

    def _history_key(self) -> str:
        return self.api_base or "cluster"

    def _remember(self, value: int):
        hist = self._history_store.setdefault(self._history_key(), [])
        hist.append(int(value))
        if len(hist) > self._history_size:
            hist.pop(0)

    def _calc(self):
        nodes = self._cached("cluster_nodes", self._cluster_nodes) or []
        if not nodes:
            return 0

        total_used = 0.0
        total_mem = 0.0

        for n in nodes:
            d = self._pmx_get(f"/nodes/{n}/status") or {}
            mem = d.get("memory") or {}

            try:
                used = float(mem.get("used", 0))
                total = float(mem.get("total", 0))
            except Exception:
                continue

            # If a node doesn't report total (unexpected), skip it.
            if total <= 0:
                continue
            total_used += used
            total_mem += total

        if total_mem <= 0:
            return 0

        return int(round((total_used / total_mem) * 100, 0))

    def as_numeric(self):
        key = f"cluster_mem_{self._history_key()}"
        value = self._cached(key, self._calc)
        if value is not None:
            self._remember(value)
        return value

    def as_string(self):
        key = f"cluster_mem_{self._history_key()}"
        return f"{self._cache.get(key, 0)}%"

    def last_values(self) -> List[int]:
        hist = self._history_store.get(self._history_key(), [])
        if not hist:
            current = self._cache.get(f"cluster_mem_{self._history_key()}", None)
            if current is not None:
                self._remember(current)
            hist = self._history_store.get(self._history_key(), [])
        return hist[-self._history_size:]


# ------------------------------
# CLUSTER DISK (AGGREGATED)
# ------------------------------

class ProxmoxClusterDiskUsageSensor(ProxmoxBaseSensor):
    """
    Returns cluster rootfs usage in percent (0-100).
    Aggregates each node's `rootfs.used` / `rootfs.total` by summing used and total.
    """

    _history_store: Dict[str, List[int]] = {}
    _history_size = 50

    def _history_key(self) -> str:
        return self.api_base or "cluster"

    def _remember(self, value: int):
        hist = self._history_store.setdefault(self._history_key(), [])
        hist.append(int(value))
        if len(hist) > self._history_size:
            hist.pop(0)

    def _calc(self):
        nodes = self._cached("cluster_nodes", self._cluster_nodes) or []
        if not nodes:
            return 0

        total_used = 0.0
        total_size = 0.0

        for n in nodes:
            d = self._pmx_get(f"/nodes/{n}/status") or {}
            rootfs = d.get("rootfs") or {}
            try:
                total_size += float(rootfs.get("total", 0))
                total_used += float(rootfs.get("used", 0))
            except Exception:
                continue

        if total_size <= 0:
            return 0

        return int(round((total_used / total_size) * 100, 0))

    def as_numeric(self):
        key = f"cluster_dsk_{self._history_key()}"
        value = self._cached(key, self._calc)
        if value is not None:
            self._remember(value)
        return value

    def as_string(self):
        key = f"cluster_dsk_{self._history_key()}"
        return f"{self._cache.get(key, 0)}%"

    def last_values(self) -> List[int]:
        hist = self._history_store.get(self._history_key(), [])
        if not hist:
            current = self._cache.get(f"cluster_dsk_{self._history_key()}", None)
            if current is not None:
                self._remember(current)
            hist = self._history_store.get(self._history_key(), [])
        return hist[-self._history_size:]


# ------------------------------
# NODE CPU
# ------------------------------

class ProxmoxNodeCPUUsageSensor(ProxmoxBaseSensor):
    _history_store: Dict[str, List[int]] = {}
    _history_size = 50

    def _history_key(self) -> str:
        return f"{self.node}"

    def _remember(self, value: int):
        logger.debug(f"[PROXMOX] Remembering CPU value {value} for node {self.node}")
        hist = self._history_store.setdefault(self._history_key(), [])
        hist.append(int(value))
        if len(hist) > self._history_size:
            hist.pop(0)

    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/status") or {}
        cpu = d.get("cpu")
        rounded = int(round(cpu*100,0))
        try:
            return rounded
        except:
            return 0

    def as_numeric(self):
        value = self._cached(f"nodecpu_{self.node}", self._calc)
        if value is not None:
            self._remember(value)
        return value

    def as_string(self):
        return f"{self._cache.get(f'nodecpu_{self.node}')}%"
    
    def last_values(self) -> List[int]:
        hist = self._history_store.get(self._history_key(), [])
        if not hist:
            current = self._cache.get(f'nodecpu_{self.node}', None)
            if current is not None:
                self._remember(current)
            hist = self._history_store.get(self._history_key(), [])
        return hist[-self._history_size:]


# ------------------------------
# NODE MEMORY
# ------------------------------

class ProxmoxNodeMemoryUsageSensor(ProxmoxBaseSensor):
    _history_store: Dict[str, List[int]] = {}
    _history_size = 50

    def _history_key(self) -> str:
        return f"{self.node}"
    
    def _remember(self, value: int):
        logger.debug(f"[PROXMOX] Remembering MEMORY value {value} for node {self.node}")
        hist = self._history_store.setdefault(self._history_key(), [])
        hist.append(int(value))
        if len(hist) > self._history_size:
            hist.pop(0)

    def _calc(self):
        d = self._pmx_get(f"/nodes/{self.node}/status") or {}
        mem = d.get("memory") or {}
        try:
            used = float(mem.get("used", 0))
            total = float(mem.get("total", 1))
            rounded = int(round(used / total * 100))
            return rounded
        except:
            return 0

    def as_numeric(self):
        value = self._cached(f"nodemem_{self.node}", self._calc)
        if value is not None:
            self._remember(value)
        return value

    def as_string(self):
        return f"{self._cache.get(f'nodemem_{self.node}', 0)}%"

    def last_values(self) -> List[int]:
        hist = self._history_store.get(self._history_key(), [])
        if not hist:
            current = self._cache.get(f'nodemem_{self.node}', None)
            if current is not None:
                self._remember(current)
            hist = self._history_store.get(self._history_key(), [])
        return hist[-self._history_size:]


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
            rounded = int(round(used / total * 100))
            return rounded
        except:
            return 0

    def as_numeric(self):
        return self._cached(f"nodedsk_{self.node}", self._calc)

    def as_string(self):
        return f"{self._cache.get(f'nodedsk_{self.node}', 0)}%"

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
        #print("Network data:", d)
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