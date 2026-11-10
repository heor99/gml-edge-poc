#!/usr/bin/env python3
"""Point d'entrée du POC GML Edge : exécute le moteur ZFE puis le moteur Safety.

Exemples :
  python main.py                       # jeu de données de l'énoncé
  python main.py --realtime            # rejoue la trace GPS en (quasi) temps réel
  python main.py --gps data/corrupted/truck_gps_corrupted.json \
                 --accel data/corrupted/accelerometer_corrupted.csv
"""
import argparse
import os
import sys

from gml_edge import geo, log, safety

HERE = os.path.dirname(os.path.abspath(__file__))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="POC GML Edge : moteur ZFE (Geo) + moteur Safety (Physics)")
    p.add_argument("--polygon", default=os.path.join(HERE, "data", "lyon_polygon.json"))
    p.add_argument("--gps", default=os.path.join(HERE, "data", "truck_gps.json"))
    p.add_argument("--accel", default=os.path.join(HERE, "data", "accelerometer_data.csv"))
    p.add_argument("--out", default=os.path.join(HERE, "output", "daily_score.json"))
    p.add_argument("--log", default=os.path.join(HERE, "logs", "gml_edge.log"))
    p.add_argument("--prealert-m", type=float, default=500.0, help="distance de pré-alerte ZFE en mètres")
    p.add_argument("--speed-kmh", type=float, default=90.0, help="vitesse de référence pour le délai d'alerte")
    p.add_argument("--realtime", action="store_true", help="rejoue la trace GPS en temps réel accéléré")
    p.add_argument("--speedup", type=float, default=10.0, help="facteur d'accélération du temps réel")
    p.add_argument("--only", choices=["zfe", "safety"], help="n'exécuter qu'un module")
    return p.parse_args(argv)


def main(argv=None):
    log.use_utf8_console()
    args = parse_args(argv)
    log.setup(args.log)
    ok = True
    try:
        if args.only in (None, "zfe"):
            stats = geo.run_zfe(args.polygon, args.gps, args.prealert_m, args.speed_kmh,
                                args.realtime, args.speedup)
            ok = ok and stats is not None
        if args.only in (None, "safety"):
            result = safety.run_safety(args.accel, args.out)
            ok = ok and result.get("status") == "OK"
    except KeyboardInterrupt:
        log.emit("INFO", "Arrêt demandé par l'utilisateur")
    except Exception as exc:  # filet de sécurité ultime : jamais de plantage brutal à bord
        log.emit("ERROR", f"Erreur inattendue interceptée : {type(exc).__name__}: {exc}")
        ok = False
    finally:
        log.emit("INFO", "Fin d'exécution " + ("sans erreur bloquante" if ok else "avec des erreurs gérées (voir [ERROR]/[WARN])"))
        log.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
