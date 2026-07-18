"""Generate Pika sample 3MF projects for every supported Bambu printer x nozzle.

Method: take one hand-tuned donor 3MF (templates/X1C0.4mm_Sample.3mf), revert
its Pika overrides back to stock, retarget it to another printer/nozzle by
swapping exactly the keys whose *stock* values differ between the two systems
(both resolved from the official BambuStudio profile repo at a pinned tag, so
representations match), then re-apply the Pika delta from ../pika_delta.json.

Stock profile jsons are fetched with `gh api` and cached under ../cache/<ref>/.

Usage:
    python generate.py                  # all printers x nozzles -> ../profiles/bambu/
    python generate.py --validate       # also diff output against hand-made samples
"""
import argparse, json, subprocess, sys, urllib.parse, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = "v02.06.00.51"  # matches the Bambu Studio version the donor samples were made with
API_BASE = "repos/bambulab/BambuStudio/contents/resources/profiles/BBL"
CONFIG = "Metadata/project_settings.config"
TEMPLATE = Path(__file__).parent / "templates" / "X1C0.4mm_Sample.3mf"

PRINTERS = {  # short key -> official machine model name
    "X1C": "Bambu Lab X1 Carbon",
    "X1":  "Bambu Lab X1",
    "X1E": "Bambu Lab X1E",
    "P1S": "Bambu Lab P1S",
    "P1P": "Bambu Lab P1P",
}
NOZZLES = ["0.2", "0.4", "0.6", "0.8"]
FILAMENT = "Generic PLA"  # material shipped in the sample projects

DELTA = json.load(open(ROOT / "pika_delta.json", encoding="utf-8"))

# preset-file bookkeeping keys that must not be copied into a project config
META_KEYS = {"name", "inherits", "instantiation", "from", "setting_id", "type",
             "filament_id", "description", "include", "compatible_printers",
             "compatible_printers_condition", "compatible_prints",
             "compatible_prints_condition"}


def fmt(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


# ---------------------------------------------------------------- repo access
def fetch(folder: str, preset: str, ref: str) -> dict:
    cache = ROOT / "cache" / ref / folder / (preset + ".json")
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        enc = urllib.parse.quote(f"{folder}/{preset}.json")
        r = subprocess.run(
            ["gh", "api", f"{API_BASE}/{enc}?ref={ref}", "-H", "Accept: application/vnd.github.raw"],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"fetch failed for {folder}/{preset}.json @ {ref}: {r.stderr.strip()[:200]}")
        cache.write_text(r.stdout, encoding="utf-8")
    return json.loads(cache.read_text(encoding="utf-8"))


def load_preset(folder: str, preset: str, ref: str) -> dict:
    """Load one preset file, inlining its "include" references (e.g. the
    'Bambu Lab P1S 0.4 nozzle template machine_start_gcode' gcode files)."""
    d = fetch(folder, preset, ref)
    if "include" not in d:
        return d
    merged = {}
    for inc in d["include"]:
        merged.update(load_preset(folder, inc, ref))
    merged.update({k: v for k, v in d.items() if k != "include"})
    return merged


def resolve(folder: str, leaf: str, ref: str) -> dict:
    """Flatten an inheritance chain: child values win over parent values."""
    chain = []
    preset = leaf
    while preset:
        d = load_preset(folder, preset, ref)
        chain.append(d)
        preset = d.get("inherits")
    flat = {}
    for d in reversed(chain):  # parents first, children overwrite
        flat.update(d)
    return flat


# ------------------------------------------------------------- config surgery
def shaped(new, existing):
    """Adapt a preset value to the shape the project config already uses."""
    if isinstance(existing, list) and not isinstance(new, list):
        return [new] * len(existing)
    if isinstance(existing, list) and isinstance(new, list) and len(new) == 1 and len(existing) > 1:
        return new * len(existing)
    return new


def overlay(cfg: dict, src_flat: dict, dst_flat: dict) -> None:
    """Rewrite cfg keys whose stock value differs between source and target system."""
    for key in set(src_flat) | set(dst_flat):
        if key in META_KEYS:
            continue
        sv, dv = src_flat.get(key), dst_flat.get(key)
        if sv == dv:
            continue  # same stock value in both systems -> project value already right
        if dv is None:
            cfg.pop(key, None)  # defined only for the source system -> stale
        else:
            cfg[key] = shaped(dv, cfg.get(key))


def line_width_rule(nozzle: str) -> dict:
    return DELTA["line_width_rules"].get(nozzle, DELTA["line_width_rules"]["default"])


def apply_delta(cfg: dict, nozzle: str) -> None:
    """Apply the Pika recipe and record overrides in different_settings_to_system."""
    changed_process, changed_filament = [], []

    for key, mult in line_width_rule(nozzle).items():
        new = fmt(mult * float(nozzle))
        if cfg.get(key) != new:
            cfg[key] = new
            changed_process.append(key)

    if cfg.get("infill_combination") != DELTA["infill_combination"]:
        cfg["infill_combination"] = DELTA["infill_combination"]
        changed_process.append("infill_combination")

    types = cfg.get("filament_type", [])
    speeds = list(cfg.get("filament_max_volumetric_speed", []))
    for i, ftype in enumerate(types):
        cap = DELTA["flow_caps_mm3s"].get(ftype, {}).get(nozzle)
        if cap is not None and i < len(speeds) and float(speeds[i]) < cap:
            speeds[i] = fmt(cap)
            if "filament_max_volumetric_speed" not in changed_filament:
                changed_filament.append("filament_max_volumetric_speed")
    cfg["filament_max_volumetric_speed"] = speeds

    dsts = cfg.get("different_settings_to_system", ["", "", ""])
    for idx, adds in ((0, changed_process), (1, changed_filament)):
        cur = [k for k in dsts[idx].split(";") if k]
        dsts[idx] = ";".join(sorted(set(cur) | set(adds)))
    cfg["different_settings_to_system"] = dsts


def build_config(template_cfg: dict, printer_key: str, nozzle: str, ref: str) -> dict:
    cfg = json.loads(json.dumps(template_cfg))  # deep copy

    # source system = the donor template's presets
    src_machine = resolve("machine", template_cfg["printer_settings_id"], ref)
    src_process = resolve("process", template_cfg["print_settings_id"], ref)
    src_filament = resolve("filament", template_cfg["filament_settings_id"][0], ref)

    # 1. revert donor's Pika overrides to stock so the project is clean stock
    dsts = template_cfg.get("different_settings_to_system", ["", "", ""])
    for slot, flat in ((0, src_process), (1, src_filament), (2, src_machine)):
        for key in [k for k in dsts[slot].split(";") if k]:
            if key in flat:
                cfg[key] = shaped(flat[key], cfg.get(key))
    cfg["different_settings_to_system"] = ["", "", ""]

    # 2. retarget to the destination printer/nozzle
    machine_name = f"{PRINTERS[printer_key]} {nozzle} nozzle"
    dst_machine = resolve("machine", machine_name, ref)
    process_name = dst_machine["default_print_profile"]
    dst_process = resolve("process", process_name, ref)
    dst_filament = resolve("filament", FILAMENT, ref)

    overlay(cfg, src_machine, dst_machine)
    overlay(cfg, src_process, dst_process)
    overlay(cfg, src_filament, dst_filament)

    cfg["printer_settings_id"] = machine_name
    cfg["printer_model"] = PRINTERS[printer_key]
    cfg["printer_variant"] = nozzle
    cfg["print_settings_id"] = process_name
    cfg["filament_settings_id"] = [FILAMENT]
    cfg["print_compatible_printers"] = fetch("process", process_name, ref)["compatible_printers"]
    cfg["version"] = ref.lstrip("v")

    # 3. Pika-fy
    apply_delta(cfg, nozzle)
    return cfg


def write_3mf(cfg: dict, out_path: Path) -> None:
    with zipfile.ZipFile(TEMPLATE) as zin, \
         zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = json.dumps(cfg, indent=4, ensure_ascii=False) if item.filename == CONFIG \
                else zin.read(item.filename)
            zout.writestr(item, data)


# ------------------------------------------------------------------ validation
def read_cfg(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(CONFIG).decode("utf-8"))


def validate(outdir: Path) -> bool:
    """Diff generated files against Luke's four hand-made samples."""
    samples = Path("C:/Users/luke/Projects/projects/pika-hotends-site/Pika Profiles")
    # 0.6 files are expected to differ ONLY by the new 45 mm3/s PLA flow cap
    expect = {
        "X1C0.4mm_Sample.3mf": ("Pika_X1C_0.4mm_Sample.3mf", {}),
        "P1S0.4mm_Sample.3mf": ("Pika_P1S_0.4mm_Sample.3mf", {}),
        "X1C0.6mm_Sample.3mf": ("Pika_X1C_0.6mm_Sample.3mf",
                                {"filament_max_volumetric_speed": (["30"], ["45"])}),
        "P1S0.6mm_Sample.3mf": ("Pika_P1S_0.6mm_Sample.3mf",
                                {"filament_max_volumetric_speed": (["30"], ["45"])}),
    }
    ok = True
    for sample, (generated, allowed) in expect.items():
        ref_cfg = read_cfg(samples / sample)
        gen_cfg = read_cfg(outdir / generated)
        diffs = {k: (ref_cfg.get(k), gen_cfg.get(k))
                 for k in set(ref_cfg) | set(gen_cfg) if ref_cfg.get(k) != gen_cfg.get(k)}
        unexpected = {k: v for k, v in diffs.items() if allowed.get(k) != v}
        status = "OK" if not unexpected else f"FAIL ({len(unexpected)} unexpected diffs)"
        print(f"  {sample:26s} vs {generated:28s} {status}")
        for k, (rv, gv) in sorted(unexpected.items()):
            print(f"      {k}: sample={json.dumps(rv)[:70]} generated={json.dumps(gv)[:70]}")
            ok = False
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=REF)
    ap.add_argument("--out", default=str(ROOT / "profiles" / "bambu"))
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    template_cfg = read_cfg(TEMPLATE)

    manifest = []
    for pkey in PRINTERS:
        for noz in NOZZLES:
            cfg = build_config(template_cfg, pkey, noz, args.ref)
            name = f"Pika_{pkey}_{noz}mm_Sample.3mf"
            write_3mf(cfg, outdir / name)
            manifest.append({
                "file": name, "printer": PRINTERS[pkey], "nozzle": noz,
                "process": cfg["print_settings_id"], "filament": FILAMENT,
                "flow_cap_mm3s": cfg["filament_max_volumetric_speed"][0],
                "overrides": cfg["different_settings_to_system"],
            })
            print(f"generated {name}  (flow cap {cfg['filament_max_volumetric_speed'][0]} mm3/s)")

    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{len(manifest)} profiles written to {outdir}")

    if args.validate:
        print("\nvalidation against hand-made samples:")
        sys.exit(0 if validate(outdir) else 1)


if __name__ == "__main__":
    main()
