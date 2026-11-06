# Load shifting for a hotel building (scenario S2)

Python simulation of **load shifting** for a 5,000 m² hotel in Marrakech under the Moroccan ONEE medium-voltage tariff.
Part of my final-year project at IRESEN (ENSAM Casablanca, 2026): *techno-economic modelling of distributed flexibility in smart grids*.

## What the code does

Starting from an hourly load profile (8,760 h, kW per end use), `S2_load_shifting.py`:

- shifts part of the **HVAC** load out of the tariff peak using a first-order thermal inertia model (time constant 12 h) and a pre-cooling period before the peak;
- shifts **hot water** and **laundry** loads to off-peak night hours (maximum shift window of 6 h);
- conserves energy by construction (checked in the output);
- computes the annual bill (energy by tariff period + subscribed-power fee), peak power, load factor, peak-to-average ratio, and NPV / IRR / payback for illustrative investment costs;
- saves two figures and two CSV files.

It is a deterministic, rule-based algorithm (no optimisation solver).

## Run it

```bash
pip install -r requirements.txt
python S2_load_shifting.py --out results
```

`baseline_S0.csv` must have 8,760 rows and the columns `CVC, ECS, Cuisine, Eclairage, Buanderie, Autres` (kW, hourly), plus an optional `T_ext` column (outdoor temperature, °C).
Without `--baseline`, the script generates a **synthetic fallback profile**; results are then indicative only.

## Status and limitations

- The load profile of the study is synthetic (no metered data from the hotel).
- Economic parameters (investment cost, discount rate, 15-year horizon) are illustrative assumptions.
- This script follows a load-shifting method that differs from scenario S2 of the final report in some respects (for example, kitchen loads are not shifted here). Figures in the report come from the full project pipeline and are not reproduced by running this script alone.
- Thermal model: single time constant, no building simulation.

## Author

Jihane Selkaoui, ENSAM Casablanca. Contact: jihaneselkaoui603@gmail.com
