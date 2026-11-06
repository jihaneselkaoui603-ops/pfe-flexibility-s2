#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scénario S2 – Load shifting pur | Hôtel Al Wafa, Marrakech
PFE SELKAOUI Jihane – ENSAM Casablanca / IRESEN 2025-2026

Implémente la méthodologie du chapitre 2 (§2.3) :
  - CVC  : pré-conditionnement 22->20 °C (1-2 h avant pointe) puis décalage en pointe
           (inertie thermique, éq. 2.1-2.2, fraction flexible 40 %)
  - ECS / Buanderie : report vers les heures creuses (fenêtre max 6 h, Tab. 2.11)
  - Conservation de l'énergie (éq. 2.7) garantie par construction.

IMPORTANT (cohérence avec le binôme) :
  Utiliser EXACTEMENT le même profil baseline S0 que le peak shaving :
      python S2_load_shifting.py --baseline baseline_S0.csv
  CSV attendu : 8760 lignes, colonnes CVC, ECS, Cuisine, Eclairage, Buanderie, Autres
  (kW, pas horaire) + colonne optionnelle T_ext (°C).
  Sans --baseline, un baseline synthétique de secours est généré (résultats indicatifs).
"""
import argparse, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ───────────────────────── PARAMÈTRES (à garder identiques au binôme) ─────────────────────────
N = 8760
EUI, SURFACE = 241, 5000
E_ANNUELLE_KWH = EUI * SURFACE                      # 1 205 000 kWh

TARIF = {"pointe": 1.4157, "pleine": 1.0101, "creuse": 0.7398}   # MAD/kWh
PRIME_FIXE = 512.62                                  # DH/kVA/an
COS_PHI = 0.9                                        # Psouscrite = Pmax / cos(phi)  (§3.3)
TVA_ENERGIE = 0.0                                    # mettre 0.20 SEULEMENT si le binôme l'applique

TAU, T_COOL, T_PRECOOL, T_MAX = 12.0, 22.0, 20.0, 24.0
FRAC_CVC = 0.40
DT_MAX_SHIFT = 3.0                                   # h (Tab. 2.11 : 1-3 h)
PRECOOL_H = 2                                        # h de pré-conditionnement
PRECOOL_LOSS = 1.00                                  # >1 pour pénaliser le stockage (1.0 = éq. 2.7 stricte)
SEUIL_CVC, SEUIL_ECS, SEUIL_BUAN = 20.0, 10.0, 5.0   # kW (Tab. 2.13)
MAX_SHIFT_ECS_H, MAX_SHIFT_BUAN_H = 6, 6             # h (Tab. 2.11)
CAP_FACTOR = 1.0                                     # le report ne doit pas dépasser Pmax(S0)*CAP_FACTOR

# Investissement : HYPOTHÈSES ILLUSTRATIVES À REMPLACER par des devis/références
CAPEX = {"GTB / supervision CVC": 120_000, "Automatisation ECS (ballons)": 40_000,
         "Programmation buanderie": 10_000}
OPEX_ANNUEL = 5_000
TAUX_ACTU, DUREE = 0.08, 15

idx = pd.date_range("2025-01-01", periods=N, freq="h")
MOIS, HEURE = idx.month.values, idx.hour.values
ETE = (MOIS >= 4) & (MOIS <= 9)

# ───────────────────────── TARIFS ─────────────────────────
def periodes():
    p = np.full(N, "pleine", dtype=object)
    pointe = (ETE & (HEURE >= 18) & (HEURE < 23)) | (~ETE & (HEURE >= 17) & (HEURE < 22))
    creuse = (ETE & ((HEURE >= 23) | (HEURE < 7))) | (~ETE & ((HEURE >= 22) | (HEURE < 7)))
    p[pointe], p[creuse] = "pointe", "creuse"
    return p

PER = periodes()
TAR = np.array([TARIF[x] for x in PER])

# ───────────────────────── BASELINE ─────────────────────────
def baseline_synthetique(seed=42):
    rng = np.random.default_rng(seed)
    j = np.arange(N) / 24
    T = 20 + 16 * np.sin(2 * np.pi * (j - 80) / 365) \
        + 8 * np.maximum(np.sin(np.pi * ((np.arange(N) % 24) - 6) / 12), 0) + rng.normal(0, 1, N)
    occ_m = {1:.62,2:.65,3:.68,4:.72,5:.70,6:.55,7:.58,8:.60,9:.65,10:.72,11:.75,12:.78}
    occ = np.clip(np.array([occ_m[m] for m in MOIS]) *
                  np.where(HEURE < 7, .85, np.where(HEURE < 12, .6 + .3*(HEURE-7)/5,
                  np.where(HEURE < 18, .5, np.where(HEURE < 23, .8, .9)))), .2, 1)
    Tl = np.roll(T, 3)                                         # inertie : décalage de la charge froid
    nrm = lambda p, part: p * (part * E_ANNUELLE_KWH / p.sum())
    cvc = nrm(np.maximum(Tl-T_COOL,0)*4.5*occ + np.maximum(19-Tl,0)*3*occ + 5, .47)
    ecs = nrm(np.where((HEURE>=6)&(HEURE<=9),2.5,np.where((HEURE>=18)&(HEURE<=21),2.0,
              np.where((HEURE>=10)&(HEURE<=17),.8,.5)))*occ, .13)
    cui = nrm(np.where((HEURE>=7)&(HEURE<=10),2.5,np.where((HEURE>=12)&(HEURE<=14),3.0,
              np.where((HEURE>=19)&(HEURE<=22),3.5,.3)))*(.5+.5*occ), .14)
    ecl = nrm(np.where((HEURE>=7)&(HEURE<=22), .6+.4*np.sin(np.pi*(HEURE-7)/15), .3), .11)
    bua = nrm(np.where((HEURE>=8)&(HEURE<=18),1.5,np.where((HEURE>=18)&(HEURE<=20),.8,.1))*occ, .06)
    aut = nrm(.5+.5*occ, .09)
    return pd.DataFrame({"CVC":cvc,"ECS":ecs,"Cuisine":cui,"Eclairage":ecl,
                         "Buanderie":bua,"Autres":aut,"T_ext":T})

def charger_baseline(path):
    if path is None:
        print("⚠ Baseline synthétique de secours (pas de --baseline) : résultats indicatifs.")
        return baseline_synthetique()
    df = pd.read_csv(path)
    manque = {"CVC","ECS","Cuisine","Eclairage","Buanderie","Autres"} - set(df.columns)
    assert not manque and len(df) == N, f"CSV invalide (colonnes manquantes {manque}, lignes {len(df)})"
    if "T_ext" not in df: df["T_ext"] = baseline_synthetique()["T_ext"]
    return df

# ───────────────────────── ALGORITHME S2 ─────────────────────────
def dt_shift(T_ext):
    """Éq. 2.2 : durée max avant d'atteindre Tmax depuis Tprecool (bornée à DT_MAX_SHIFT)."""
    if T_ext <= T_MAX:
        return DT_MAX_SHIFT
    return float(min(-TAU * np.log((T_MAX - T_ext) / (T_PRECOOL - T_ext)), DT_MAX_SHIFT))

def deplacer(P, elig, nuit, autres_total, cap):
    """Reporte l'énergie des heures éligibles sur les heures creuses (remplissage par marge de puissance)."""
    E = P[elig].sum()
    if E <= 0 or len(nuit) == 0: return 0.0
    marge = np.maximum(cap - (autres_total[nuit] + P[nuit]), 0)
    if marge.sum() <= 0: return 0.0
    moved = min(E, marge.sum())
    P[nuit] += moved * marge / marge.sum()
    P[elig] *= (1 - moved / E)
    return moved

def load_shifting(bl):
    T = bl["T_ext"].values
    cvc, ecs, bua = (bl[c].values.copy() for c in ("CVC", "ECS", "Buanderie"))
    fixe = bl["Cuisine"].values + bl["Eclairage"].values + bl["Autres"].values
    cap = (bl[["CVC","ECS","Cuisine","Eclairage","Buanderie","Autres"]].sum(axis=1).max()) * CAP_FACTOR
    st = dict(e_red=0.0, e_pre=0.0, e_ecs=0.0, e_bua=0.0, h_shift=0, h_pre=0, viol=0)

    for d in range(364):                                  # le dernier jour n'a pas de nuit suivante
        hd, hf = d*24, d*24 + 24
        hp = [h for h in range(hd, hf) if PER[h] == "pointe"]
        t0, cs = hp[0], hd + (23 if ETE[hd] else 22)      # début pointe / début creuses

        # Phase 2 : décalage CVC en pointe (mode refroidissement uniquement)
        cpt, R = 0, 0.0
        for t in hp:
            if T[t] > T_COOL and cvc[t] > SEUIL_CVC and (cpt + 1) <= dt_shift(T[t]):
                Tc = T[t] + (T_PRECOOL - T[t]) * np.exp(-cpt / TAU)
                alpha = min((T_MAX - Tc) / (T_MAX - T_PRECOOL), 1.0) * FRAC_CVC
                r = cvc[t] * alpha; cvc[t] -= r; R += r; cpt += 1; st["h_shift"] += 1
        # Phase 1 : pré-conditionnement (compense exactement l'énergie décalée, éq. 2.7)
        if R > 0:
            pre = [h for h in range(t0 - PRECOOL_H, t0) if h >= hd]
            w = cvc[pre] / cvc[pre].sum()
            cvc[pre] += R * PRECOOL_LOSS * w
            st["e_pre"] += R * PRECOOL_LOSS; st["e_red"] += R; st["h_pre"] += len(pre)

        # ECS / Buanderie -> heures creuses de la nuit suivante
        nuit = np.arange(cs, hd + 31)
        for P, seuil, fen, key in ((ecs, SEUIL_ECS, MAX_SHIFT_ECS_H, "e_ecs"),
                                   (bua, SEUIL_BUAN, MAX_SHIFT_BUAN_H, "e_bua")):
            elig = np.array([t for t in range(hd, hf)
                             if PER[t] != "creuse" and (cs - t) <= fen and P[t] > seuil])
            if len(elig) == 0: continue
            autres = cvc + fixe + (bua if P is ecs else ecs)
            st[key] += deplacer(P, elig, nuit, autres, cap)

    s2 = bl.copy(); s2["CVC"], s2["ECS"], s2["Buanderie"] = cvc, ecs, bua
    return s2, st

# ───────────────────────── FACTURE & INDICATEURS ─────────────────────────
POSTES = ["CVC","ECS","Cuisine","Eclairage","Buanderie","Autres"]

def facture(P):
    pmax, pmoy = P.max(), P.mean()
    psous = pmax / COS_PHI
    prime = psous * PRIME_FIXE
    cener = float(np.dot(P, TAR)) * (1 + TVA_ENERGIE)
    return dict(Pmax=pmax, Pmoy=pmoy, Psous=psous, FC=pmoy/pmax*100, PAR=pmax/pmoy,
                prime=prime, cener=cener, total=prime+cener)

def par_periode(P):
    return {k: P[PER == k].sum()/1000 for k in ("pointe","pleine","creuse")}

def van_tri_trs(gain, capex, opex=OPEX_ANNUEL, r=TAUX_ACTU, n=DUREE):
    flux = [-capex] + [gain - opex] * n
    van = sum(f / (1 + r) ** i for i, f in enumerate(flux))
    lo, hi, tri = -0.99, 10.0, np.nan
    f_ = lambda x: sum(c / (1 + x) ** i for i, c in enumerate(flux))
    if f_(lo) * f_(hi) < 0:
        for _ in range(200):
            m = (lo + hi) / 2
            lo, hi = (m, hi) if f_(lo) * f_(m) > 0 else (lo, m)
        tri = m
    trs = capex / (gain - opex) if gain > opex else np.inf
    return van, tri, trs

# ───────────────────────── MAIN ─────────────────────────
def main(path_baseline, out):
    os.makedirs(out, exist_ok=True)
    bl = charger_baseline(path_baseline)
    s2, st = load_shifting(bl)
    P0, P2 = bl[POSTES].sum(axis=1).values, s2[POSTES].sum(axis=1).values
    f0, f2 = facture(P0), facture(P2)
    eco_p, eco_e, eco_t = f0["prime"]-f2["prime"], f0["cener"]-f2["cener"], f0["total"]-f2["total"]
    pp0, pp2 = par_periode(P0), par_periode(P2)
    cons = (P2.sum()-P0.sum())/P0.sum()*100
    # Éq. 2.11 (CVC) : énergie décalée valorisée pointe -> pleine (le pré-cond. est facturé en pleine)
    gain_cvc = st["e_red"]*(TARIF["pointe"]-TARIF["pleine"])
    gain_ecs = st["e_ecs"]*(TARIF["pleine"]-TARIF["creuse"])   # borne haute (une partie vient de la pointe)

    print("="*70, "\n  SCÉNARIO S2 – LOAD SHIFTING PUR | Hôtel Al Wafa\n", "="*70, sep="")
    print(f"Conservation énergie S2 vs S0 : {cons:+.4f} %  ({P0.sum()/1e3:.1f} -> {P2.sum()/1e3:.1f} MWh)")
    print(f"\n{'Indicateur':<28}{'Baseline':>14}{'S2':>14}{'Écart':>14}")
    for lab, k, fmt in [("Puissance max (kW)","Pmax","{:.1f}"),("Puissance souscrite (kVA)","Psous","{:.1f}"),
                        ("Facteur de charge (%)","FC","{:.1f}"),("PAR","PAR","{:.2f}"),
                        ("Prime fixe (MAD/an)","prime","{:,.0f}"),("Coût énergie (MAD/an)","cener","{:,.0f}"),
                        ("Facture totale (MAD/an)","total","{:,.0f}")]:
        a, b = f0[k], f2[k]
        print(f"{lab:<28}{fmt.format(a):>14}{fmt.format(b):>14}{fmt.format(b-a):>14}")
    print(f"\nÉconomie prime fixe   : {eco_p:>10,.0f} MAD/an")
    print(f"Économie énergie      : {eco_e:>10,.0f} MAD/an")
    print(f"ÉCONOMIE TOTALE       : {eco_t:>10,.0f} MAD/an  ({eco_t/f0['total']*100:.2f} % de la facture)")
    print("\nÉnergie par période tarifaire (MWh/an)")
    for k in ("pointe","pleine","creuse"):
        print(f"  {k:<8}{pp0[k]:>10.1f}{pp2[k]:>10.1f}{pp2[k]-pp0[k]:>+10.1f}")
    print(f"\nÉnergie décalée : CVC {st['e_red']/1e3:.1f} MWh | ECS {st['e_ecs']/1e3:.1f} MWh | Buanderie {st['e_bua']/1e3:.1f} MWh")
    print(f"Pré-conditionnement : {st['e_pre']/1e3:.1f} MWh ; heures de décalage CVC : {st['h_shift']}")
    print(f"Contrôle éq. 2.11 (gain CVC {gain_cvc:,.0f} + ECS {gain_ecs:,.0f} + Buan "
          f"{st['e_bua']*(TARIF['pleine']-TARIF['creuse']):,.0f} MAD) vs économie énergie réelle {eco_e:,.0f} MAD")

    capex = sum(CAPEX.values())
    if eco_t > 0:
        van, tri, trs = van_tri_trs(eco_t, capex)
        print(f"\nRentabilité (CAPEX {capex:,.0f} MAD = hypothèse illustrative, r={TAUX_ACTU:.0%}, {DUREE} ans):")
        print(f"  VAN = {van:,.0f} MAD | TRI = {tri*100 if tri==tri else float('nan'):.1f} % | TRS = {trs:.1f} ans")
    else:
        print("\nÉconomie totale <= 0 : pas de calcul VAN/TRI/TRS.")

    # ── Figures ──
    fig, ax = plt.subplots(2, 1, figsize=(11, 9))
    for a, m, titre in ((ax[0], ETE, "Été (avril à septembre)"), (ax[1], ~ETE, "Hiver (octobre à mars)")):
        h0 = pd.Series(P0[m]).groupby(HEURE[m]).mean(); h2 = pd.Series(P2[m]).groupby(HEURE[m]).mean()
        a.plot(h0.index, h0, "k-", lw=2, label="Baseline S0"); a.plot(h2.index, h2, "--", lw=2, label="Load shifting S2")
        a.fill_between(h0.index, h2, h0, where=h0 > h2, color="g", alpha=.25, label="énergie retirée")
        a.fill_between(h0.index, h2, h0, where=h2 > h0, color="orange", alpha=.25, label="énergie ajoutée")
        a.set_title(f"Profil horaire moyen – {titre}"); a.set_xlabel("Heure"); a.set_ylabel("kW")
        a.set_xticks(range(24)); a.grid(alpha=.3); a.legend()
    plt.tight_layout(); plt.savefig(f"{out}/S2_profils_saisonniers.png", dpi=150); plt.close()

    fig, ax = plt.subplots(1, 3, figsize=(16, 5))
    ax[0].bar(["Prime fixe","Énergie"], [eco_p, eco_e], color=["#7b78e0","#f0a030"])
    ax[0].set_title(f"Décomposition de l'économie (total {eco_t:,.0f} MAD/an)"); ax[0].set_ylabel("MAD/an")
    ax[1].bar(["S0","S2"], [f0["prime"], f2["prime"]], label="Prime fixe", color="#FF9800")
    ax[1].bar(["S0","S2"], [f0["cener"], f2["cener"]], bottom=[f0["prime"], f2["prime"]], label="Énergie", color="#2196F3")
    ax[1].legend(); ax[1].set_title("Facture annuelle")
    x = np.arange(3); w = .35
    ax[2].bar(x-w/2, [pp0[k] for k in pp0], w, label="S0"); ax[2].bar(x+w/2, [pp2[k] for k in pp2], w, label="S2")
    ax[2].set_xticks(x); ax[2].set_xticklabels(list(pp0)); ax[2].set_ylabel("MWh/an"); ax[2].legend()
    ax[2].set_title("Énergie par période tarifaire")
    plt.tight_layout(); plt.savefig(f"{out}/S2_evaluation_economique.png", dpi=150); plt.close()

    pd.DataFrame({"Indicateur": ["Pmax kW","Psouscrite kVA","FC %","PAR","Prime fixe","Cout energie","Facture totale"],
                  "Baseline": [f0[k] for k in ("Pmax","Psous","FC","PAR","prime","cener","total")],
                  "S2": [f2[k] for k in ("Pmax","Psous","FC","PAR","prime","cener","total")]}
                 ).to_csv(f"{out}/S2_resultats.csv", index=False, encoding="utf-8-sig")
    s2.assign(Total=P2).to_csv(f"{out}/S2_profil_horaire.csv", index=False)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=None, help="CSV baseline S0 du binôme (8760 lignes)")
    ap.add_argument("--out", default="/mnt/user-data/outputs")
    a = ap.parse_args(); main(a.baseline, a.out)
