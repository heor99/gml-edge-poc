# GML Edge — POC « Tablette Télématique » (GreenMove Logistics)

Preuve de concept des deux moteurs embarqués de la tablette durcie GML :

| Module | Rôle | Entrée | Sortie |
|---|---|---|---|
| **1. ZFE (Geo)** | Détecter l'entrée dans une Zone à Faibles Émissions **sans réseau** | `lyon_polygon.json` + `truck_gps.json` | Logs `[PRE-ALERT ZFE]` / `[ALERT ZFE]` |
| **2. Safety (Physics)** | Isoler les conduites dangereuses dans le bruit de l'accéléromètre | `accelerometer_data.csv` | `output/daily_score.json` |

Python 3.8 ou plus, **bibliothèque standard uniquement** : aucune installation, aucun accès réseau.

---

## 1. Procédure de test en local

```bash
git clone <URL_DU_DEPOT>
cd gml-edge-poc
python --version            # 3.8 minimum (python3 sous macOS / Linux)
```

### 1.1 Lancer le POC sur le jeu de données de l'énoncé

```bash
python main.py
```

Résultat attendu (extrait) :

```
[GPS] #1 08:00:00 (45.8100, 4.7500) -> OUT | bbox (O(1)) en 2 µs
[GPS] #2 08:00:10 (45.8000, 4.7800) -> OUT | bbox (O(1)) en 2 µs
[GPS] #3 08:00:20 (45.7850, 4.8050) -> APPROCHE | bord à 451 m | ray casting (O(n)) en 25 µs
[PRE-ALERT ZFE] ZFE Lyon à 451 m (≈ 18 s à 90 km/h) — préparer l'itinéraire de contournement
[GPS] #4 08:00:30 (45.7600, 4.8357) -> IN | ray casting (O(n)) en 5 µs
[ALERT ZFE] ENTRÉE dans ZFE Lyon — point #4 à 08:00:30 — événement horodaté enregistré localement
[SAFETY] Freinage Violent détecté — ligne de données 6, ts 1678880005, pic brut -3.45 m/s² (0.352 g) ...
[INFO] Score du jour : 90/100 (note B) — éligible bonus assurance : oui
[INFO] Fichier écrit : output/daily_score.json
```

### 1.2 Rejouer la trace GPS en temps réel (démonstration)

```bash
python main.py --realtime --speedup 10     # 10 s de trajet = 1 s à l'écran
```

### 1.3 Prouver la robustesse (fichiers corrompus ou absents)

```bash
python main.py --polygon data/corrupted/polygon_open.json \
               --gps data/corrupted/truck_gps_corrupted.json \
               --accel data/corrupted/accelerometer_corrupted.csv
python main.py --polygon data/absent.json --accel data/corrupted/empty.csv
```

Le programme ne plante jamais : chaque anomalie produit un `[WARN]` ou un `[ERROR]`, la donnée fautive est ignorée et le traitement continue. Le code de sortie vaut 0 si tout s'est bien passé, 1 si des erreurs ont été gérées.

### 1.4 Données réalistes à 100 Hz (bruit, nids-de-poule, vrai freinage)

```bash
python tools/generate_synthetic_100hz.py
python main.py --only safety --accel data/synthetic_100hz.csv --out output/daily_score_100hz.json
```

Les deux chocs isolés (nid-de-poule à −6 m/s², dos-d'âne à +5 m/s²) sont ignorés ; le freinage réel (t = 40 s) et le virage brusque (t = 50 s) sont détectés.

### 1.5 Tests automatiques et performance

```bash
python -m unittest discover -s tests -v     # 14 tests
python tools/bench.py                        # intérêt de la bounding box + mémoire
```

---

## 2. Structure

```
gml-edge-poc/
├── main.py                     # point d'entrée (options : python main.py --help)
├── gml_edge/
│   ├── geo.py                  # Module 1 : Bounding Box + Ray Casting + pré-alerte
│   ├── safety.py               # Module 2 : filtre passe-bas + seuil à hystérésis + score
│   └── log.py                  # journalisation console + logs/gml_edge.log
├── data/                       # jeux de données de l'énoncé (+ corrupted/ pour les tests)
├── examples/daily_score.example.json
├── tests/                      # tests unitaires (unittest, sans dépendance)
└── tools/                      # bench.py, generate_synthetic_100hz.py
```

---

## 3. Fonctionnement des algorithmes

### 3.1 Module ZFE (Geo)

1. **Bounding Box — O(1).** On calcule une fois le rectangle englobant du polygone. Un point hors de ce rectangle (élargi de la distance de pré-alerte) est rejeté avec 4 comparaisons. Sur une journée de livraison, c'est l'immense majorité des points.
2. **Ray Casting — O(n).** Pour un point candidat, on trace une demi-droite horizontale vers l'est et on compte les arêtes qu'elle traverse : impair = dedans, pair = dehors. La règle « semi-ouverte » `(yi > y) != (yj > y)` évite de compter deux fois un sommet ; un point exactement sur le bord est compté **dedans** (principe de prudence pour la conformité).
3. **Pré-alerte — O(n).** Si le point est dehors mais proche, on calcule la distance au bord le plus proche (projection locale en mètres). Sous 500 m (≈ 20 s à 90 km/h), on émet `[PRE-ALERT ZFE]`.
4. **Machine à états** `OUT → APPROCHE → IN` : une alerte n'est émise qu'au **changement** d'état, jamais répétée (pas de fatigue d'alerte pour le chauffeur).

Une seule boucle par point : aucun algorithme en O(n²), conformément à la contrainte du Zebra ET40.

### 3.2 Module Safety (Physics)

1. **Lecture en flux** ligne par ligne (mémoire constante), lignes illisibles ignorées et comptées.
2. **Filtre passe-bas du 1er ordre** (moyenne mobile exponentielle), constante de temps τ = 0,1 s, adaptée à la fréquence réelle : `alpha = dt / (τ + dt)`. À 100 Hz, un choc de 10 ms est atténué d'environ 90 % ; un freinage, qui dure plusieurs dixièmes de seconde, passe.
3. **Seuil à hystérésis** : début d'événement quand le signal filtré passe sous −2,5 m/s², fin quand il remonte au-dessus de −1,5 m/s² : un freinage = un seul événement.
4. Mêmes principes pour l'accélération brusque (+2,5 m/s² sur Y) et le virage brusque (|X| > 3,0 m/s²), demandés par l'assureur (« freinages, virages »).
5. **Score** : 100 − 10 par freinage violent − 5 par accélération brusque − 8 par virage brusque (plancher 0). Sans donnée valide, aucun score n'est produit (pas de preuve = pas de bonus).
6. Écriture **atomique** de `daily_score.json` (fichier temporaire puis renommage) : une coupure d'alimentation ne laisse jamais un fichier à moitié écrit.

---

## 4. Points d'attention relevés sur les données de l'énoncé

### Écart sur le point 3
Le point 3 (45.7850, 4.8050) est annoncé « IN (Bordure) ». Géométriquement, il est **à environ 451 m au nord** de l'arête (45.7800, 4.8000) → (45.7900, 4.8600), donc **hors** du polygone. Plutôt que de forcer le résultat, le moteur le classe en zone d'**APPROCHE** et déclenche une **pré-alerte**, ce qui correspond à l'intention métier (« bordure ») et laisse 18 s au chauffeur pour réagir à 90 km/h. L'alerte d'entrée se déclenche au point 4.

### Unité du seuil
La consigne mentionne « > 2.5G » mais l'Annexe 3 fixe le seuil à 2,5 **m/s²** (valeur < −2,5) avec des données en m/s². 2,5 g (24,5 m/s²) ne serait jamais atteint par un camion. Le seuil retenu est donc **−2,5 m/s² (≈ 0,25 g)**, paramétrable dans `gml_edge/safety.py`.

---

## 5. Limites du POC et suite

- Production : portage en Kotlin (Android natif) avec la même logique ; lecture des capteurs via l'API Android `SensorManager`.
- Plusieurs centaines de ZFE en Europe : index spatial (grille ou R-tree) pour ne tester que les polygones proches.
- Stockage local SQLite + agrégation à la minute pour la synchronisation 4G (voir la copie écrite).
- Calibrage des seuils sur données réelles de la flotte (taux de faux positifs à mesurer).
