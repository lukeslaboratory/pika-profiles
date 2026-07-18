"""Pika-fy a user's own Bambu Studio / Orca Slicer 3MF project.

Applies the Pika hotend recipe from ../pika_delta.json to the project's
settings, scaled to the file's nozzle diameter and filament material(s),
without touching anything else. This is also the reference implementation
for the future browser-based converter on pikahotends.com.

Usage:
    python pikafy.py MyProject.3mf MyProject_Pika.3mf
"""
import json, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DELTA = json.load(open(ROOT / "pika_delta.json", encoding="utf-8"))
CONFIG = "Metadata/project_settings.config"

NOZZLE_BUCKETS = ["0.2", "0.4", "0.6", "0.8"]


def fmt(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def bucket(nozzle: float) -> str:
    """Nearest standard nozzle size; ties round down (conservative caps)."""
    return min(NOZZLE_BUCKETS, key=lambda b: (abs(float(b) - nozzle), float(b)))


def apply_delta(cfg: dict) -> list:
    """Patch cfg in place; return a human-readable change log."""
    nozzle = float(cfg["nozzle_diameter"][0])
    buck = bucket(nozzle)
    rules = DELTA["line_width_rules"]["0.2"] if nozzle < 0.3 else DELTA["line_width_rules"]["default"]
    log, changed_process, changed_filament = [], [], []

    for key, mult in rules.items():
        # skin/skeleton infill are newer Bambu-only keys: patch only if present
        if key not in cfg and key in ("skin_infill_line_width", "skeleton_infill_line_width"):
            continue
        new = fmt(mult * nozzle)
        if cfg.get(key) != new:
            log.append(f"{key}: {cfg.get(key)} -> {new}")
            cfg[key] = new
            changed_process.append(key)

    if cfg.get("infill_combination") != DELTA["infill_combination"]:
        log.append(f"infill_combination: {cfg.get('infill_combination')} -> {DELTA['infill_combination']}")
        cfg["infill_combination"] = DELTA["infill_combination"]
        changed_process.append("infill_combination")

    types = cfg.get("filament_type", [])
    speeds = list(cfg.get("filament_max_volumetric_speed", []))
    for i, ftype in enumerate(types):
        cap = DELTA["flow_caps_mm3s"].get(ftype, {}).get(buck)
        if cap is not None and i < len(speeds) and float(speeds[i]) < cap:
            log.append(f"filament_max_volumetric_speed[{i}] ({ftype}): {speeds[i]} -> {fmt(cap)}")
            speeds[i] = fmt(cap)
            if "filament_max_volumetric_speed" not in changed_filament:
                changed_filament.append("filament_max_volumetric_speed")
    cfg["filament_max_volumetric_speed"] = speeds

    if "different_settings_to_system" in cfg or changed_process or changed_filament:
        dsts = cfg.get("different_settings_to_system", ["", "", ""])
        for idx, adds in ((0, changed_process), (1, changed_filament)):
            cur = [k for k in dsts[idx].split(";") if k]
            dsts[idx] = ";".join(sorted(set(cur) | set(adds)))
        cfg["different_settings_to_system"] = dsts
    return log


def pikafy(src: str, dst: str) -> None:
    with zipfile.ZipFile(src) as zin:
        cfg = json.loads(zin.read(CONFIG).decode("utf-8"))
        log = apply_delta(cfg)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = json.dumps(cfg, indent=4, ensure_ascii=False) if item.filename == CONFIG \
                    else zin.read(item.filename)
                zout.writestr(item, data)
    print(f"pikafied {src} -> {dst}")
    for line in log:
        print("  ", line)
    if not log:
        print("   (already Pika-tuned, no changes needed)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pikafy(sys.argv[1], sys.argv[2])
