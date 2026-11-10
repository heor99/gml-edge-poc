"""Module 2 — Moteur Safety (Physics).

Lit les données brutes de l'accéléromètre (m/s²), isole les comportements
dangereux cachés dans le bruit et produit un score journalier (daily_score.json).

Chaîne de traitement, en flux (une ligne à la fois : mémoire constante O(1)) :
  1. Lecture tolérante du CSV : les lignes illisibles sont ignorées et comptées.
  2. Filtre passe-bas du 1er ordre (moyenne mobile exponentielle) de constante
     de temps TAU = 0,1 s, adapté à la fréquence réelle d'échantillonnage :
       alpha = dt / (TAU + dt) ; filtré = alpha * brut + (1 - alpha) * filtré_précédent
     -> à 100 Hz, un choc isolé de 10 ms (nid-de-poule) est atténué de ~90 % ;
        un vrai freinage, qui dure plusieurs dixièmes de seconde, passe.
  3. Seuil avec hystérésis : un événement commence quand le signal filtré passe
     sous -2,5 m/s² et ne se termine que quand il remonte au-dessus de -1,5 m/s²
     -> un freinage = un seul événement, même si le signal oscille autour du seuil.
"""
import csv
import json
import math
import os
import tempfile
from datetime import datetime, timezone

from . import log

G = 9.80665

DEFAULTS = {
    "tau_s": 0.1,                       # constante de temps du filtre passe-bas
    "harsh_braking_ms2": -2.5,          # seuil Annexe 3 (décélération > 2,5 m/s²)
    "braking_release_ms2": -1.5,        # hystérésis
    "harsh_accel_ms2": 2.5,
    "accel_release_ms2": 1.5,
    "harsh_corner_ms2": 3.0,            # accélération latérale |acc_x|
    "corner_release_ms2": 2.0,
}

PENALTIES = {"HARSH_BRAKING": 10, "HARSH_ACCELERATION": 5, "HARSH_CORNERING": 8}


def read_samples(path, stats):
    """Générateur : renvoie (n° de ligne de données, ts, ax, ay, az). Ne lève jamais d'exception."""
    try:
        f = open(path, newline="", encoding="utf-8")
    except OSError as exc:
        log.emit("ERROR", f"Fichier accéléromètre inaccessible : {exc}")
        stats["file_error"] = str(exc)
        return
    with f:
        reader = csv.reader(f)
        last_ts = None
        data_row = 0
        for line_no, row in enumerate(reader, start=1):
            if line_no == 1 and row and row[0].strip().lower() == "timestamp":
                continue  # en-tête
            data_row += 1
            stats["total"] += 1
            try:
                if len(row) < 4:
                    raise ValueError(f"{len(row)} colonne(s) au lieu de 4")
                ts, ax, ay, az = (float(v) for v in row[:4])
                if not all(math.isfinite(v) for v in (ts, ax, ay, az)):
                    raise ValueError("valeur non finie (NaN/inf)")
                if last_ts is not None and ts <= last_ts:
                    raise ValueError(f"horodatage non croissant ({ts:.0f} après {last_ts:.0f})")
            except ValueError as exc:
                stats["rejected"] += 1
                log.emit("WARN", f"Ligne de données {data_row} ignorée ({exc}) — le moteur continue")
                continue
            last_ts = ts
            yield data_row, ts, ax, ay, az


class _Channel:
    """Détecteur à seuil + hystérésis sur un signal filtré."""

    def __init__(self, kind, trigger, release, sign):
        self.kind, self.trigger, self.release, self.sign = kind, trigger, release, sign
        self.active = None

    def update(self, row, ts, raw, filtered):
        value = filtered * self.sign
        if self.active is None:
            if value > self.trigger:
                self.active = {"type": self.kind, "data_row": row, "start_ts": ts,
                               "peak_raw_ms2": raw, "peak_filtered_ms2": filtered}
            return None
        if abs(raw) > abs(self.active["peak_raw_ms2"]):
            self.active["peak_raw_ms2"] = raw
        if abs(filtered) > abs(self.active["peak_filtered_ms2"]):
            self.active["peak_filtered_ms2"] = filtered
        if value < self.release:
            event, self.active = self._close(ts), None
            return event
        return None

    def _close(self, end_ts):
        e = self.active
        e["end_ts"] = end_ts
        e["duration_s"] = round(end_ts - e["start_ts"], 3)
        e["peak_raw_ms2"] = round(e["peak_raw_ms2"], 3)
        e["peak_filtered_ms2"] = round(e["peak_filtered_ms2"], 3)
        e["peak_g"] = round(abs(e["peak_raw_ms2"]) / G, 3)
        e["start_iso"] = datetime.fromtimestamp(e["start_ts"], tz=timezone.utc).isoformat()
        return e

    def flush(self, ts):
        if self.active is not None:
            return self._close(ts)
        return None


def analyse(path, params=None):
    p = dict(DEFAULTS, **(params or {}))
    stats = {"total": 0, "rejected": 0}
    channels = {
        "y_brake": _Channel("HARSH_BRAKING", -p["harsh_braking_ms2"], -p["braking_release_ms2"], -1),
        "y_accel": _Channel("HARSH_ACCELERATION", p["harsh_accel_ms2"], p["accel_release_ms2"], 1),
        "x_left": _Channel("HARSH_CORNERING", p["harsh_corner_ms2"], p["corner_release_ms2"], 1),
        "x_right": _Channel("HARSH_CORNERING", p["harsh_corner_ms2"], p["corner_release_ms2"], -1),
    }
    events = []
    fy = fx = None
    prev_ts = first_ts = last_ts = None
    dts = []
    for row, ts, ax, ay, az in read_samples(path, stats):
        if prev_ts is None:
            fy, fx, first_ts = ay, ax, ts       # initialisation du filtre
        else:
            dt = ts - prev_ts
            dts.append(dt)
            alpha = dt / (p["tau_s"] + dt)      # filtre adapté à la fréquence réelle
            fy = alpha * ay + (1 - alpha) * fy
            fx = alpha * ax + (1 - alpha) * fx
        prev_ts = last_ts = ts
        for key, raw, filt in (("y_brake", ay, fy), ("y_accel", ay, fy), ("x_left", ax, fx), ("x_right", ax, fx)):
            ev = channels[key].update(row, ts, raw, filt)
            if ev:
                events.append(ev)
                _log_event(ev)
    for ch in channels.values():
        ev = ch.flush(last_ts)
        if ev:
            events.append(ev)
            _log_event(ev)

    valid = stats["total"] - stats["rejected"]
    rate = round(1.0 / (sum(dts) / len(dts)), 2) if dts else None
    counts = {k: sum(1 for e in events if e["type"] == k) for k in PENALTIES}
    penalty = sum(PENALTIES[k] * n for k, n in counts.items())
    score = max(0, 100 - penalty) if valid > 0 else None   # pas de donnée = pas de score
    return {
        "schema_version": "1.0",
        "date": datetime.fromtimestamp(first_ts, tz=timezone.utc).date().isoformat() if first_ts else None,
        "source_file": os.path.basename(path),
        "samples": {"total": stats["total"], "valid": valid, "rejected": stats["rejected"],
                    "sampling_rate_hz": rate,
                    "duration_s": (last_ts - first_ts) if first_ts is not None else 0},
        "parameters": {"unit": "m/s2", "filter": "passe-bas 1er ordre (EMA)", **p},
        "events": events,
        "counts": counts,
        "score": {"value": score, "max": 100, "grade": _grade(score) if score is not None else "N/A",
                  "method": "100 - 10 x freinage violent - 5 x accélération brusque - 8 x virage brusque (plancher 0)"},
        "insurance": {"bonus_eligible": score is not None and score >= 80, "threshold": 80},
        "status": "OK" if valid > 0 else "NO_VALID_DATA",
    }


def _grade(score):
    return "A" if score >= 95 else "B" if score >= 85 else "C" if score >= 70 else "D"


def _log_event(ev):
    label = {"HARSH_BRAKING": "Freinage Violent", "HARSH_ACCELERATION": "Accélération brusque",
             "HARSH_CORNERING": "Virage brusque"}[ev["type"]]
    log.emit("SAFETY", f"{label} détecté — ligne de données {ev['data_row']}, ts {ev['start_ts']:.0f} "
                       f"({ev['start_iso']}), pic brut {ev['peak_raw_ms2']} m/s² ({ev['peak_g']} g), "
                       f"pic filtré {ev['peak_filtered_ms2']} m/s², durée {ev['duration_s']} s")


def write_json_atomic(data, out_path):
    """Écriture atomique : un fichier à moitié écrit (coupure de courant) ne remplace jamais l'ancien."""
    folder = os.path.dirname(out_path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def run_safety(csv_path, out_path, vehicle_id="GML-POC-001"):
    log.emit("INFO", "=== Module 2 : moteur Safety (Physics) ===")
    result = analyse(csv_path)
    result = {"vehicle_id": vehicle_id, **result}
    s = result["samples"]
    rate = f"{s['sampling_rate_hz']} Hz" if s['sampling_rate_hz'] else "inconnue"
    log.emit("INFO", f"Bilan Safety : {s['valid']}/{s['total']} lignes valides, {s['rejected']} rejetée(s), "
                     f"fréquence mesurée {rate}")
    if result["score"]["value"] is None:
        log.emit("WARN", "Aucune donnée exploitable : score non calculé, journée non éligible au bonus (aucune preuve)")
    else:
        log.emit("INFO", f"Score du jour : {result['score']['value']}/100 (note {result['score']['grade']}) — "
                         f"éligible bonus assurance : {'oui' if result['insurance']['bonus_eligible'] else 'non'}")
    try:
        write_json_atomic(result, out_path)
        log.emit("INFO", f"Fichier écrit : {out_path}")
    except OSError as exc:
        log.emit("ERROR", f"Écriture de {out_path} impossible ({exc}) ; le score reste en mémoire")
    return result
