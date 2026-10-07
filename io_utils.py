from __future__ import annotations
import pandas as pd, numpy as np
from engine import Inputs
import events as ev

SHEETS = ["Historis", "Dasar", "Pensiun", "Jalur", "Skenario_TPP"]
EVENT_SHEETS = ["Kejadian", "Asumsi_Kejadian"]          # opsional: boleh tidak ada / kosong
EVENT_COLS = {"Kejadian": ev.COLS_K, "Asumsi_Kejadian": ev.COLS_A}
EVENT_NUM = ["tahun_mulai", "nilai"]                     # kolom angka; sisanya teks (tahun_selesai boleh 'akhir')


def coerce_event_table(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Rapikan tabel kejadian untuk editor UI: kolom baku, angka -> float, teks -> str, baris kosong dibuang."""
    cols = EVENT_COLS[name]
    df = ev._prep(df, cols)
    out = pd.DataFrame(index=range(len(df)))
    for c in cols:
        if c in EVENT_NUM:
            out[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        else:
            def txt(v):
                if ev._blank(v):
                    return ""
                try:
                    f = float(v)
                    return str(int(f)) if f == int(f) else str(v)
                except (TypeError, ValueError):
                    return str(v).strip()
            out[c] = df[c].map(txt).astype(object)
    keep = ~(out[EVENT_NUM].isna().all(axis=1) & (out.drop(columns=EVENT_NUM) == "").all(axis=1))
    return out[keep].reset_index(drop=True)


def _year_cols(df):
    out = {}
    for c in df.columns:
        try:
            out[c] = int(float(str(c).strip()))
        except ValueError:
            pass
    return out


def tables_from_excel(file) -> dict:
    """Baca template -> dict of DataFrame mentah (untuk ditampilkan/diedit di UI)."""
    xl = pd.ExcelFile(file)
    miss = [s for s in SHEETS if s not in xl.sheet_names]
    if miss:
        raise ValueError(f"Sheet tidak ditemukan: {', '.join(miss)}. Gunakan template resmi aplikasi.")
    t = {s: xl.parse(s) for s in SHEETS}
    for s in EVENT_SHEETS:      # opsional
        t[s] = coerce_event_table(s, xl.parse(s) if s in xl.sheet_names else None)
    h = t["Historis"]
    h = h.rename(columns=_year_cols(h))
    t["Historis"] = h
    p = t["Pensiun"]
    t["Pensiun"] = p.rename(columns=_year_cols(p))
    return t


def normalize_tables(t: dict) -> dict:
    """Kolom tahun (teks/angka) -> int, agar tabel hasil edit di UI (kolom string) tetap terbaca."""
    out = {}
    for k, df in t.items():
        df = df.copy()
        if k not in EVENT_SHEETS:
            df.columns = [(_year_cols(df).get(c, c)) for c in df.columns]
        out[k] = df
    return out


def tables_to_ui(t: dict) -> dict:
    out = {}
    for k, df in t.items():
        df = df.copy()
        df.columns = [str(c) for c in df.columns]
        out[k] = df
    return out


def inputs_from_tables(t: dict) -> Inputs:
    t = normalize_tables(t)
    h = t["Historis"].copy()
    ycols = [c for c in h.columns if isinstance(c, (int, np.integer))]
    h = h.set_index("kode")[sorted(ycols)].apply(pd.to_numeric, errors="coerce")
    h.columns = [int(c) for c in h.columns]
    need = ["inflasi", "pajak", "retribusi", "kekayaan", "lain_pad", "trf_pusat", "trf_antar", "hibah", "pend_lain",
            "peg_total", "barjas", "belanja_hibah", "bansos", "modal", "btt", "transfer", "pemeliharaan"]
    miss = [k for k in need if k not in h.index]
    if miss:
        raise ValueError(f"Kode akun hilang di sheet Historis: {miss}")
    h = h.fillna({k: 0.0 for k in h.index if k != "inflasi"})
    d = t["Dasar"].set_index("kode")["nilai"].to_dict()
    for k in ["gaji_pns", "gaji_pppk", "tpp", "insentif_pajak", "insentif_retribusi", "tunjangan_guru", "asn_tpp_dasar", "silpa", "retribusi_kesehatan", "tahun_dasar"]:
        if k not in d:
            raise ValueError(f"Kode '{k}' hilang di sheet Dasar")
    d = {k: float(v) for k, v in d.items()}
    d["tahun_dasar"] = int(d["tahun_dasar"])
    p = t["Pensiun"].copy()
    yc = sorted([c for c in p.columns if isinstance(c, (int, np.integer))])
    tarif = pd.to_numeric(p["gaji_tunjangan_per_tahun"], errors="coerce").fillna(0)
    pen = pd.DataFrame({"orang": [pd.to_numeric(p[y], errors="coerce").fillna(0).sum() for y in yc],
                        "gaji": [float((pd.to_numeric(p[y], errors="coerce").fillna(0) * tarif).sum()) for y in yc]},
                       index=[int(y) for y in yc])
    j = t["Jalur"].copy().set_index("tahun")
    j.index = j.index.astype(int)
    j = j[["asn_penerima_tpp", "gaji_pppk"]].apply(pd.to_numeric, errors="coerce")
    j.columns = ["asn_tpp", "gaji_pppk"]
    if j.isna().any().any():
        raise ValueError("Sheet Jalur: ada sel kosong/non-angka")
    s = t["Skenario_TPP"].copy().set_index("tahun")
    s.index = s.index.astype(int)
    s = s.apply(pd.to_numeric, errors="coerce")
    kj = t.get("Kejadian")
    ak = t.get("Asumsi_Kejadian")
    return Inputs(hist=h, dasar=d, pensiun=pen, jalur=j, tpp_skenario=s,
                  kejadian=ev.empty_k() if kj is None else coerce_event_table("Kejadian", kj),
                  asumsi_kejadian=ev.empty_a() if ak is None else coerce_event_table("Asumsi_Kejadian", ak))


def load_inputs(file):
    return inputs_from_tables(tables_from_excel(file))
