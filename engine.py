"""
Mesin proyeksi kepatuhan pemda terhadap UU 1/2022 (HKPD) Pasal 146 (belanja pegawai) & 147 (belanja infrastruktur).
Replikasi logika kertas kerja Kab. Magelang (sheet F1/F2/F3) + parameter skenario tambahan (default = perilaku Excel).
Semua nilai dalam Rupiah penuh.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import numpy as np
import pandas as pd
import events as ev

OWN_SOURCE = ["pajak", "retribusi", "kekayaan", "lain_pad", "hibah"]   # tumbuh dua fase (pemulihan -> normal)
REV_KEYS = ["pajak", "retribusi", "kekayaan", "lain_pad", "trf_pusat", "trf_antar", "hibah", "pend_lain"]
EXP_KEYS = ["peg_total", "barjas", "belanja_hibah", "bansos", "modal", "btt", "transfer"]
KEBIJAKAN_LAMA = "Kebijakan lama (TPP tahun dasar + inflasi)"


@dataclass
class Inputs:
    hist: pd.DataFrame          # index=kode, kolom=tahun(int)
    dasar: dict                 # nilai tahun dasar
    pensiun: pd.DataFrame       # index=tahun, kolom: orang, gaji (Rp/tahun)
    jalur: pd.DataFrame         # index=tahun proyeksi, kolom: asn_tpp, gaji_pppk
    tpp_skenario: pd.DataFrame  # index=tahun proyeksi, kolom=nama skenario -> total TPP
    kejadian: pd.DataFrame = field(default_factory=ev.empty_k)          # opsional: dampak kejadian tak terduga
    asumsi_kejadian: pd.DataFrame = field(default_factory=ev.empty_a)   # opsional: perubahan asumsi akibat kejadian


@dataclass
class Params:
    pendekatan: str = "A3"          # A1 | A2 | A3 (lihat narasi Bab 4.2.5)
    n_pemulihan: int = 2            # jumlah tahun proyeksi memakai laju "pemulihan"
    tahun_normal: tuple = (2017, 2018, 2019)      # tahun yang laju tumbuhnya dirata-rata sebagai laju "normal"
    tahun_rata: tuple = (2016, 2017, 2018, 2019)   # rata-rata level: BTT, rasio belanja/pendapatan (A1), (opsional) inflasi
    tahun_abnormal: tuple = ()      # tahun tak normal (mis. pandemi): tak dipakai; laju yang menyentuh tahun ini dibuang dari rata-rata normal
    tahun_pemulihan: tuple | None = None   # tahun yang pertumbuhannya dipakai sbg laju pemulihan (dirata-rata); None = tahun dasar
    outlier_cap: float = 5.0        # laju tumbuh > cap dibuang dari rata-rata (mis. hibah 2018 = 28,5x)
    floor_pemulihan: bool = True    # laju pemulihan < 1 dianggap 1 (sama dengan tahun sebelumnya)
    inflasi_tpp: float = 0.0278
    batas_pegawai: float = 0.30
    batas_infra: float = 0.40
    tahun_target: int = 2027
    r_insentif_pajak: float = 0.05
    r_insentif_retribusi: float = 0.05
    # --- tuas skenario (default = perilaku Excel) ---
    faktor_pensiun: float = 1.0     # 1 = efek penuh di tahun pensiun (Excel); 0.5 = rata-rata pensiun di tengah tahun
    pensiun_scale: float = 1.0
    passthrough_dau: float = 1.0    # porsi perubahan gaji ASN yang mengalir ke transfer pusat
    pppk_pusat_pct: float = 0.0     # dukungan pusat atas gaji PPPK (ilustratif, belum ada juknis)
    pppk_pusat_mode: str = "keluar" # keluar = belanja & pendapatan transfer sama-sama turun | tambah_dau = pendapatan naik
    kredit_barjas_pct: float = 0.0  # % barjas non-pemeliharaan yang diakui sbg infrastruktur pelayanan publik
    delta_pad: float = 0.0          # tambahan laju tumbuh pendapatan sendiri (mis. 0.02 = +2 poin/thn)
    k_shift: float = 0.0            # pergeseran relatif rasio belanja/pendapatan
    tpp_scale: float = 1.0
    respon_belanja_a2: float = 1.0  # hanya A2: porsi perubahan pendapatan (akibat kejadian) yang diteruskan ke total belanja


# ------------------------------------------------------------------ helpers
def _growth(s: pd.Series) -> dict:
    s = s.astype(float)
    return {y: s[y] / s[y - 1] for y in s.index if (y - 1) in s.index and s[y - 1] and not np.isnan(s[y]) and not np.isnan(s[y - 1])}


def rec_factor(s: pd.Series, p: Params, base_year: int) -> float:
    g = _growth(s)
    v = [g[y] for y in (p.tahun_pemulihan or (base_year,)) if y in g]
    f = float(np.mean(v)) if v else 1.0
    return 1.0 if (p.floor_pemulihan and f < 1) else f


def nor_factor(s: pd.Series, p: Params) -> float:
    g = _growth(s)
    abn = set(p.tahun_abnormal)
    v = [g[y] for y in p.tahun_normal if y in g and g[y] <= p.outlier_cap and y not in abn and (y - 1) not in abn]
    return float(np.mean(v)) if v else 1.0


def _two_phase(base: float, rec: float, nor: float, n: int, n_rec: int) -> list:
    out, cur = [], base
    for i in range(n):
        cur *= rec if i < n_rec else nor
        out.append(cur)
    return out


def _ratio(num, den):
    """Rasio aman: penyebut <= 0 (mis. total belanja habis akibat kejadian ekstrem) -> NaN, dihitung 'tidak patuh'."""
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    return np.divide(num, den, out=np.full(num.shape, np.nan), where=den > 0)


def _derived_hist(h: pd.DataFrame) -> pd.DataFrame:
    h = h.copy()
    h.loc["operasi"] = h.loc[["peg_total", "barjas", "belanja_hibah", "bansos"]].sum()
    h.loc["pendapatan"] = h.loc[REV_KEYS].sum()
    h.loc["belanja"] = h.loc[EXP_KEYS].sum()
    return h


def tpp_kebijakan_lama(inp: Inputs, p: Params) -> pd.Series:
    d = inp.dasar
    pc = d["tpp"] / d["asn_tpp_dasar"]
    infl = ev.Shocks(inp, list(inp.jalur.index)).param(p, "inflasi_tpp")
    out, f = {}, 1.0
    for i, y in enumerate(inp.jalur.index):
        f *= 1 + infl[i]
        out[y] = pc * f * inp.jalur.loc[y, "asn_tpp"]
    return pd.Series(out, name=KEBIJAKAN_LAMA)


def all_scenarios(inp: Inputs, p: Params) -> pd.DataFrame:
    sc = pd.DataFrame({KEBIJAKAN_LAMA: tpp_kebijakan_lama(inp, p)})
    ext = inp.tpp_skenario.reindex(inp.jalur.index)
    return pd.concat([sc, ext], axis=1)


# ------------------------------------------------------------------ inti proyeksi
@dataclass
class Result:
    df: pd.DataFrame        # indeks = tahun proyeksi
    base: dict              # angka tahun dasar
    params: Params
    scenario: str
    event_warnings: list = field(default_factory=list)
    event_active: bool = False


def run(inp: Inputs, p: Params, tpp_total: pd.Series, scenario: str = "") -> Result:
    h = _derived_hist(inp.hist)
    d = inp.dasar
    by = int(d["tahun_dasar"])
    years = list(inp.jalur.index)
    n = len(years)
    sh = ev.Shocks(inp, years)                      # kejadian tak terduga (kosong -> tidak berpengaruh)
    P = {k: sh.param(p, k) for k in ev.PARAMETER}   # asumsi per tahun (default = nilai Params)
    tpp = tpp_total.reindex(years).astype(float).values * P["tpp_scale"]

    # ---------- pendapatan
    rev = {}
    for k in OWN_SOURCE:
        rec = rec_factor(h.loc[k], p, by)
        nor = nor_factor(h.loc[k], p)
        cur, vals = float(h.loc[k, by]), []
        for i in range(n):
            cur *= (rec if i < p.n_pemulihan else nor) + P["delta_pad"][i]
            vals.append(cur)
        rev[k] = vals
    rev["trf_antar"] = [h.loc["trf_antar", by]] * n
    rev["pend_lain"] = [h.loc["pend_lain", by]] * n

    # ---------- gaji PNS (dikurangi pensiun), PPPK (jalur input), transfer pusat (terkait gaji)
    pen_raw = inp.pensiun["gaji"].astype(float)
    def pens(y):
        return float(pen_raw.get(y, pen_raw.iloc[-1])) if len(pen_raw) else 0.0
    gaji_pns, tr, pns_prev, tr_prev = [], [], d["gaji_pns"], h.loc["trf_pusat", by]
    pppk_prev = d["gaji_pppk"]
    for i, y in enumerate(years):
        s_now = P["pensiun_scale"][i]
        s_prev = P["pensiun_scale"][i - 1] if i > 0 else s_now
        eff = p.faktor_pensiun * (pens(y) * s_now) + (1 - p.faktor_pensiun) * (pens(y - 1) * s_prev)
        pns_prev = pns_prev - eff
        gaji_pns.append(pns_prev)
        pppk_y = float(inp.jalur.loc[y, "gaji_pppk"])
        tr_prev = tr_prev - P["passthrough_dau"][i] * eff + P["passthrough_dau"][i] * (pppk_y - pppk_prev)
        tr.append(tr_prev)
        pppk_prev = pppk_y
    pppk = inp.jalur["gaji_pppk"].astype(float).values
    pusat = P["pppk_pusat_pct"] * pppk
    if p.pppk_pusat_mode == "keluar":
        pppk_eff = pppk - pusat
        tr_eff = np.array(tr) - pusat
    else:
        pppk_eff = pppk
        tr_eff = np.array(tr) + pusat
    rev["trf_pusat"] = list(tr_eff)
    pend0 = sum(np.array(rev[k]) for k in REV_KEYS)         # pendapatan sebelum kejadian
    rev = {k: list(v) for k, v in sh.apply_rev(rev).items()} if sh.rec_k else rev
    pend = sum(np.array(rev[k]) for k in REV_KEYS)
    pad = sum(np.array(rev[k]) for k in ["pajak", "retribusi", "kekayaan", "lain_pad"])

    # ---------- total belanja (ditentukan metode; kejadian masuk lewat pendapatan / baris belanja_total)
    rata = [y for y in p.tahun_rata if y not in set(p.tahun_abnormal)]
    btt = float(h.loc["btt", rata].mean())
    trf_b = np.array([h.loc["transfer", by]] * n, dtype=float)
    pem = _two_phase(h.loc["pemeliharaan", by], 1.0, nor_factor(h.loc["pemeliharaan"], p), n, 0)
    if p.pendekatan == "A2":
        oper = _two_phase(h.loc["operasi", by], rec_factor(h.loc["operasi"], p, by), nor_factor(h.loc["operasi"], p), n, p.n_pemulihan)
        modal = _two_phase(h.loc["modal", by], rec_factor(h.loc["modal"], p, by), nor_factor(h.loc["modal"], p), n, p.n_pemulihan)
        B = np.array(oper) + np.array(modal) + btt + trf_b + p.respon_belanja_a2 * (pend - pend0)
    else:
        modal = _two_phase(h.loc["modal", by], 1.0, nor_factor(h.loc["modal"], p), n, 0)
        k0 = h.loc["belanja", by] / h.loc["pendapatan", by]
        if p.pendekatan == "A1":
            k_norm = float((h.loc["belanja", rata] / h.loc["pendapatan", rata]).mean())
            k = np.array([k0 if i < p.n_pemulihan else k_norm for i in range(n)])
        else:
            k = np.full(n, k0)
        B = k * (1 + P["k_shift"]) * pend
    B = np.maximum(B + sh.delta("belanja_total", B), 0.0)
    d_trf_tot = np.maximum(sh.delta("belanja_transfer_total", trf_b), -trf_b)   # pemda memotong/menambah transfer ke bawahan -> total belanja ikut
    B = np.maximum(B + d_trf_tot, 0.0)
    modal, pem = np.array(modal, dtype=float), np.array(pem, dtype=float)

    # ---------- dampak kejadian pada komposisi belanja (total belanja tetap; selisih diserap barjas/hibah/bansos)
    tpp = np.maximum(tpp + sh.delta("tpp", tpp), 0.0)
    modal = np.maximum(modal + sh.delta("modal", modal), 0.0)
    pem = np.maximum(pem + sh.delta("pemeliharaan", pem), 0.0)
    btt_arr = np.full(n, btt)
    btt_arr = np.maximum(btt_arr + sh.delta("btt", btt_arr), 0.0)
    trf_b = np.maximum(trf_b + sh.delta("belanja_transfer", trf_b) + d_trf_tot, 0.0)

    # ---------- belanja pegawai
    ins_p = P["r_insentif_pajak"] * np.array(rev["pajak"])
    ins_r = P["r_insentif_retribusi"] * np.array(rev["retribusi"]) + d["retribusi_kesehatan"]
    guru = d["tunjangan_guru"]
    lain_const = (h.loc["peg_total", by] - d["gaji_pns"] - d["gaji_pppk"] - d["tpp"]
                  - d["insentif_pajak"] - d["insentif_retribusi"] - guru)
    lain_arr = ins_p + ins_r + lain_const
    lain_arr = lain_arr + sh.delta("peg_lain", lain_arr)
    peg = np.array(gaji_pns) + pppk_eff + tpp + guru + lain_arr
    peg_rasio = peg - guru

    # ---------- infrastruktur
    pool = B - peg - modal - btt_arr - trf_b                # barjas + hibah + bansos
    kredit = P["kredit_barjas_pct"] * np.clip(pool - pem, 0, None)
    infra = modal + pem + kredit
    denom_infra = B - trf_b

    df = pd.DataFrame({
        "pendapatan": pend, "pad": pad, "transfer_pusat": np.array(rev["trf_pusat"]),
        "belanja": B, "belanja_pegawai_total": peg, "belanja_pegawai_rasio": peg_rasio,
        "gaji_pns": gaji_pns, "gaji_pppk": pppk_eff, "tpp": tpp,
        "pegawai_lain": peg - np.array(gaji_pns) - pppk_eff - tpp - guru,
        "tunjangan_guru": guru, "modal": modal, "pemeliharaan": pem, "kredit_barjas": kredit,
        "infra": infra, "btt": btt_arr, "belanja_transfer": trf_b, "pool_barjas_hibah_bansos": pool,
        "rasio_pegawai": _ratio(peg_rasio, B), "rasio_infra": _ratio(infra, denom_infra), "denom_infra": denom_infra,
        "surplus": pend - B, "asn_tpp": inp.jalur["asn_tpp"].astype(float).values,
        "dampak_pendapatan": pend - pend0,
    }, index=years)
    df["sisa_silpa"] = d["silpa"] + sh.delta("silpa", np.zeros(n)) + df["surplus"]

    b_B = h.loc["belanja", by]
    b_peg = h.loc["peg_total", by] - guru
    b_infra = h.loc["modal", by] + h.loc["pemeliharaan", by]
    base = dict(tahun=by, belanja=b_B, pendapatan=h.loc["pendapatan", by], rasio_pegawai=b_peg / b_B,
                rasio_infra=b_infra / (b_B - h.loc["transfer", by]), tpp=d["tpp"],
                tpp_per_pegawai=d["tpp"] / d["asn_tpp_dasar"], silpa=d["silpa"], pegawai_rasio=b_peg)
    res = Result(df, base, p, scenario)
    res.event_warnings = list(sh.warnings)
    res.event_active = sh.aktif
    return res


def run_all(inp: Inputs, p: Params) -> dict:
    sc = all_scenarios(inp, p)
    return {c: run(inp, p, sc[c], c) for c in sc.columns if sc[c].notna().all()}
