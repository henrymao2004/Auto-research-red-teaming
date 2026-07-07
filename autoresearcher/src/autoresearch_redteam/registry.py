"""Plugin registry for plugins/{victims,scenarios,researchers}/."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


_REPO_AUTORES = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = _REPO_AUTORES / "plugins"


@dataclass(frozen=True)
class Manifest:
    name: str
    axis: str
    dir: Path
    entry: str | None
    data: dict[str, Any]

    @property
    def status(self) -> str:
        return str(self.data.get("status", "ready"))


def _load_yaml(path: Path) -> dict[str, Any]:
    if _HAS_YAML:
        return yaml.safe_load(path.read_text()) or {}
    # Flat YAML form.
    out: dict[str, Any] = {}
    cur_list_key: str | None = None
    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith(" ") or line.startswith("\t"):
            if cur_list_key and line.lstrip().startswith("- "):
                out.setdefault(cur_list_key, []).append(line.lstrip()[2:].strip())
            continue
        cur_list_key = None
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if not v:
            cur_list_key = k
            out[k] = []
        else:
            out[k] = v
    return out


def _discover(axis: str, manifest_filename: str) -> dict[str, Manifest]:
    out: dict[str, Manifest] = {}
    axis_dir = PLUGINS_ROOT / axis
    if not axis_dir.is_dir():
        return out
    for plugin_dir in sorted(axis_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / manifest_filename
        if not manifest_path.exists():
            continue
        data = _load_yaml(manifest_path)
        name = str(data.get("name") or plugin_dir.name)
        entry_key = manifest_filename.replace(".yaml", "")
        entry = data.get(entry_key)
        out[name] = Manifest(
            name=name, axis=axis, dir=plugin_dir,
            entry=str(entry) if entry else None, data=data,
        )
    return out


@lru_cache(maxsize=1)
def _victim_manifests() -> dict[str, Manifest]:
    return _discover("victims", "victim.yaml")


@lru_cache(maxsize=1)
def _scenario_manifests() -> dict[str, Manifest]:
    return _discover("scenarios", "scenario.yaml")


@lru_cache(maxsize=1)
def _researcher_manifests() -> dict[str, Manifest]:
    out: dict[str, Manifest] = {}
    axis_dir = PLUGINS_ROOT / "researchers"
    if not axis_dir.is_dir():
        return out
    for plugin_dir in sorted(axis_dir.iterdir()):
        if not plugin_dir.is_dir() or not (plugin_dir / "agents").is_dir():
            continue
        out[plugin_dir.name] = Manifest(
            name=plugin_dir.name, axis="researchers",
            dir=plugin_dir, entry=None, data={"status": "ready"},
        )
    return out


def list_victims() -> list[Manifest]:
    return list(_victim_manifests().values())


def list_scenarios() -> list[Manifest]:
    return list(_scenario_manifests().values())


def list_researchers() -> list[Manifest]:
    return list(_researcher_manifests().values())


def _resolve_entry(manifest: Manifest):
    """Load the plugin as a synthetic package and return the class in ``manifest.entry``."""
    if not manifest.entry:
        raise ValueError(f"plugin {manifest.name!r} has no entry point")
    if ":" not in manifest.entry:
        raise ValueError(
            f"plugin {manifest.name!r} entry must be 'pkg.mod:Class'; "
            f"got {manifest.entry!r}"
        )
    module_path, _, cls_name = manifest.entry.partition(":")
    parts = module_path.split(".")
    pkg_name = f"_arrt_plugin_{manifest.axis}_{manifest.name}"
    submodule = parts[-1] if len(parts) > 1 else parts[0]

    # Create synthetic package.
    if pkg_name not in sys.modules:
        pkg_init = manifest.dir / "__init__.py"
        if pkg_init.exists():
            pkg_spec = importlib.util.spec_from_file_location(
                pkg_name, pkg_init, submodule_search_locations=[str(manifest.dir)],
            )
        else:
            pkg_spec = importlib.machinery.ModuleSpec(
                pkg_name, loader=None, is_package=True,
            )
            pkg_spec.submodule_search_locations = [str(manifest.dir)]
        if pkg_spec is None:
            raise ImportError(f"could not synthesise package for {manifest.name!r}")
        pkg_mod = importlib.util.module_from_spec(pkg_spec)
        sys.modules[pkg_name] = pkg_mod
        if pkg_spec.loader is not None:
            pkg_spec.loader.exec_module(pkg_mod)

    # Load entry submodule.
    sub_full = f"{pkg_name}.{submodule}"
    if sub_full not in sys.modules:
        sub_path = manifest.dir / f"{submodule}.py"
        sub_spec = importlib.util.spec_from_file_location(
            sub_full, sub_path,
            submodule_search_locations=None,
        )
        if sub_spec is None or sub_spec.loader is None:
            raise ImportError(f"could not load {sub_full} from {sub_path}")
        sub_mod = importlib.util.module_from_spec(sub_spec)
        sub_mod.__package__ = pkg_name
        sys.modules[sub_full] = sub_mod
        sub_spec.loader.exec_module(sub_mod)
    return getattr(sys.modules[sub_full], cls_name)


def victim(name: str, **kwargs):
    """Instantiate the victim adapter named ``name``."""
    manifests = _victim_manifests()
    if name not in manifests:
        avail = ", ".join(sorted(manifests)) or "(none)"
        raise KeyError(f"unknown victim {name!r}. Available: {avail}")
    cls = _resolve_entry(manifests[name])
    return cls(**kwargs)


def scenario(name: str, **kwargs):
    """Instantiate the scenario plugin named ``name``."""
    manifests = _scenario_manifests()
    if name not in manifests:
        avail = ", ".join(sorted(manifests)) or "(none)"
        raise KeyError(f"unknown scenario {name!r}. Available: {avail}")
    cls = _resolve_entry(manifests[name])
    return cls(**kwargs)


def researcher(name: str = "default") -> Manifest:
    """Return the manifest of the named researcher agent."""
    manifests = _researcher_manifests()
    if name not in manifests:
        avail = ", ".join(sorted(manifests)) or "(none)"
        raise KeyError(f"unknown researcher {name!r}. Available: {avail}")
    return manifests[name]


def validate_cell(victim_name: str, scenario_name: str) -> None:
    """Raise if the (victim, scenario) cell isn't admissible."""
    v_manifests = _victim_manifests()
    s_manifests = _scenario_manifests()
    if victim_name not in v_manifests:
        raise KeyError(f"unknown victim {victim_name!r}")
    if scenario_name not in s_manifests:
        raise KeyError(f"unknown scenario {scenario_name!r}")
    v_supports = v_manifests[victim_name].data.get("supports_attack_families") or []
    s_family = s_manifests[scenario_name].data.get("native_attack_family")
    if s_family and s_family not in v_supports:
        raise ValueError(
            f"cell ({victim_name}, {scenario_name}) inadmissible: "
            f"scenario needs attack family {s_family!r}, victim supports "
            f"{tuple(v_supports)!r}."
        )


__all__ = [
    "Manifest", "PLUGINS_ROOT",
    "list_victims", "list_scenarios", "list_researchers",
    "victim", "scenario", "researcher", "validate_cell",
]
