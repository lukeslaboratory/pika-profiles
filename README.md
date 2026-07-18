# Pika Profiles

Print profiles for the [Pika Hotend](https://pikahotends.com) (Luke's
Laboratory) on Bambu Lab printers. Each `.3mf` in `profiles/bambu/` is a
ready-to-print sample project: open it in Bambu Studio (or Orca Slicer),
and the Pika-tuned printer/process/filament settings come with it.

## Supported machines

X1 Carbon, X1, X1E, P1S, P1P — each with 0.2 / 0.4 / 0.6 / 0.8 mm nozzles
(20 combinations, Generic PLA). See `profiles/bambu/manifest.json`.

## What the Pika tune changes vs stock

Everything else — including the machine profile — is bone stock. The Pika is
a drop-in: no printer-profile changes at all.

| Setting | Rule | 0.2 | 0.4 | 0.6 | 0.8 |
|---|---|---|---|---|---|
| `infill_combination` | on | on | on | on | on |
| `internal_solid_infill_line_width` | 1.4 × nozzle (1.2 × at 0.2) | 0.24 | 0.56 | 0.84 | 1.12 |
| `sparse/skin/skeleton_infill_line_width` | 1.8 × nozzle (1.2 × at 0.2) | 0.24 | 0.72 | 1.08 | 1.44 |

Flow ceilings (`filament_max_volumetric_speed`, mm³/s) by material and nozzle:

| Material | 0.2 | 0.4 | 0.6 | 0.8 |
|---|---|---|---|---|
| PLA | 30 | 30 | 45 | 65 |
| PETG | 33 | 33 | 50 | 70 |
| ABS / ASA | 35 | 35 | 55 | 75 |

TPU and PC are intentionally left untouched. The 0.2 mm nozzle is
pressure-limited, not melt-limited — the caps are academic there.

The whole recipe lives in [`pika_delta.json`](pika_delta.json); everything
else in this repo is machinery that applies it.

## Convert your own profile

Have your own dialed-in project? Apply the Pika tune to it without losing
your settings (existing higher flow ceilings are never lowered):

```bash
python generator/pikafy.py MyProject.3mf MyProject_Pika.3mf
```

## Regenerating the matrix

`generator/generate.py` rebuilds every sample from official stock profiles
(fetched from the [BambuStudio](https://github.com/bambulab/BambuStudio) repo
at pinned tag `v02.06.00.51`, cached in `cache/`) plus the delta. Requires
Python 3 and an authenticated `gh` CLI.

```bash
python generator/generate.py --validate
```

`--validate` diffs the output against the original hand-tuned samples the
delta was extracted from; all four must match exactly.
