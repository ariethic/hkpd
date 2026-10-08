"""Lapisan preskriptif di atas engine.run(): apa yang boleh/perlu dilakukan pemda."""
from __future__ import annotations
from dataclasses import replace
import numpy as np
import pandas as pd
from engine import Inputs, Params, Result, run, all_scenarios, KEBIJAKAN_LAMA
import events as ev


def rp(x: float, unit: str | None = None) -> str:
    """Format Rupiah ringkas (T/M/jt)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    a = abs(x)
    s = "-" if x < 0 else ""
    if unit == "jt" or (unit is None and a < 1e9):
        return f"{s}Rp{a/1e6:,.1f} jt".replace(",", "X").replace(".", ",").replace("X", ".")
    if unit == "T" or (unit is None and a >= 1e12):
        return f"{s}Rp{a/1e12:,.2f} T".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s}Rp{a/1e9:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float, d: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    if not np.isfinite(x):
        return ">100%"
    return f"{x*100:.{d}f}%".replace(".", ",")


# ---------------------------------------------------------------- Pasal 146
def tpp_headroom(res: Result) -> pd.DataFrame:
    """TPP maksimum yang masih menjaga rasio belanja pegawai <= batas (komponen lain tetap)."""
    p, d = res.params, res.df
    non_tpp = d.belanja_pegawai_rasio - d.tpp
    tpp_max = np.clip(p.batas_pegawai * d.belanja - non_tpp, 0, None)
    idx = {y: i for i, y in enumerate(d.index, 1)}
    pc_protect = np.array([res.base["tpp_per_pegawai"] * (1 + p.inflasi_tpp) ** idx[y] for y in d.index])
    out = pd.DataFrame({
        "tpp_skenario": d.tpp, "tpp_maks": tpp_max, "selisih": tpp_max - d.tpp,
        "perlu_dipotong_pct": np.clip((d.tpp - tpp_max) / d.tpp, 0, None),
        "tpp_per_pegawai_skenario": d.tpp / d.asn_tpp, "tpp_per_pegawai_maks": tpp_max / d.asn_tpp,
        "tpp_per_pegawai_terlindungi": pc_protect,
    }, index=d.index)
    out["maks_per_bulan"] = out.tpp_per_pegawai_maks / 12
    out["melindungi_thp"] = out.tpp_per_pegawai_maks >= out.tpp_per_pegawai_terlindungi
    return out


def _glide(start: float, end: float, years, base_year: int, target: int) -> pd.Series:
    span = max(target - base_year, 1)
    return pd.Series({y: (start + (end - start) * min((y - base_year) / span, 1.0)) for y in years})


def jalur_pegawai(res: Result) -> pd.DataFrame:
    """Jalur linear rasio pegawai dari kondisi tahun dasar ke batas pada tahun target -> TPP maks per tahun."""
    p, d, b = res.params, res.df, res.base
    target = _glide(b["rasio_pegawai"], p.batas_pegawai, d.index, b["tahun"], p.tahun_target)
    target = target.clip(upper=max(b["rasio_pegawai"], p.batas_pegawai))
    non_tpp = d.belanja_pegawai_rasio - d.tpp
    tpp_path = np.clip(target * d.belanja - non_tpp, 0, None)
    return pd.DataFrame({"rasio_target": target, "rasio_proyeksi": d.rasio_pegawai,
                         "tpp_maks_jalur": tpp_path, "tpp_skenario": d.tpp,
                         "tpp_per_pegawai_jalur": tpp_path / d.asn_tpp}, index=d.index)


# ---------------------------------------------------------------- Pasal 147
def infra_kebutuhan(res: Result) -> pd.DataFrame:
    p, d, b = res.params, res.df, res.base
    target = _glide(b["rasio_infra"], p.batas_infra, d.index, b["tahun"], p.tahun_target)
    need = np.clip(target * d.denom_infra - d.infra, 0, None)
    avail = np.clip(d.pool_barjas_hibah_bansos - d.pemeliharaan - d.kredit_barjas, 0, None)
    share = np.where(avail > 0, need / avail, np.inf)
    full_need = np.clip(p.batas_infra * d.denom_infra - d.infra, 0, None)
    def label(s, n):
        if n <= 0: return "Patuh"
        if s <= 0.25: return "Dapat dicapai"
        if s <= 0.50: return "Berat"
        if s <= 1.0: return "Sangat berat"
        return "Tidak layak"
    return pd.DataFrame({"rasio_target": target, "rasio_proyeksi": d.rasio_infra, "infra_proyeksi": d.infra,
                         "realokasi_jalur": need, "realokasi_penuh_40": full_need,
                         "pool_tersedia": avail, "porsi_pool": share,
                         "status": [label(s, n) for s, n in zip(share, need)]}, index=d.index)


# ---------------------------------------------------------------- Sensitivitas & risiko
def _ratios(inp, p, tpp, scen):
    r = run(inp, p, tpp, scen).df.loc[p.tahun_target]
    return r.rasio_pegawai, r.rasio_infra


def tornado(inp: Inputs, p: Params, scen: str) -> pd.DataFrame:
    tpp = all_scenarios(inp, p)[scen]
    b_peg, b_inf = _ratios(inp, p, tpp, scen)
    cases = [
        ("Pendapatan asli daerah tumbuh +2 poin/tahun", dict(delta_pad=+0.02)),
        ("Pendapatan asli daerah tumbuh -2 poin/tahun", dict(delta_pad=-0.02)),
        ("Rasio belanja/pendapatan +3%", dict(k_shift=+0.03)),
        ("Rasio belanja/pendapatan -3%", dict(k_shift=-0.03)),
        ("TPP lebih rendah 10%", dict(tpp_scale=p.tpp_scale * 0.9)),
        ("TPP lebih tinggi 10%", dict(tpp_scale=p.tpp_scale * 1.1)),
        ("Pensiun 25% lebih banyak dari data", dict(pensiun_scale=1.25)),
        ("Pensiun 25% lebih sedikit dari data", dict(pensiun_scale=0.75)),
        ("Efek pensiun separuh tahun (realistis)", dict(faktor_pensiun=0.5)),
        ("Pusat menanggung 50% gaji PPPK (keluar dari APBD)", dict(pppk_pusat_pct=0.5, pppk_pusat_mode="keluar")),
        ("Pusat menambah DAU = 50% gaji PPPK", dict(pppk_pusat_pct=0.5, pppk_pusat_mode="tambah_dau")),
        ("Transfer pusat hanya 50% mengikuti gaji ASN", dict(passthrough_dau=0.5)),
        ("50% barjas non-pemeliharaan diakui infrastruktur", dict(kredit_barjas_pct=0.5)),
    ]
    rows = []
    for name, kw in cases:
        rp_, ri_ = _ratios(inp, replace(p, **kw), tpp, scen)
        rows.append((name, (rp_ - b_peg) * 100, (ri_ - b_inf) * 100))
    out = pd.DataFrame(rows, columns=["Perubahan asumsi", "Δ rasio pegawai (poin %)", "Δ rasio infra (poin %)"])
    out["_abs"] = out["Δ rasio pegawai (poin %)"].abs()
    return out.sort_values("_abs", ascending=False).drop(columns="_abs").reset_index(drop=True)


def monte_carlo(inp: Inputs, p: Params, scen: str, n: int = 400, sd_pad: float = 0.05, sd_k: float = 0.02, seed: int = 7) -> dict:
    tpp = all_scenarios(inp, p)[scen]
    rng = np.random.default_rng(seed)
    rp_, ri_ = [], []
    for _ in range(n):
        q = replace(p, delta_pad=p.delta_pad + rng.normal(0, sd_pad), k_shift=p.k_shift + rng.normal(0, sd_k))
        a, b = _ratios(inp, q, tpp, scen)
        rp_.append(a); ri_.append(b)
    rp_, ri_ = np.array(rp_), np.array(ri_)
    return dict(p_peg=float((rp_ <= p.batas_pegawai).mean()), p_infra=float((ri_ >= p.batas_infra).mean()),
                peg_q=np.quantile(rp_, [0.05, 0.5, 0.95]), infra_q=np.quantile(ri_, [0.05, 0.5, 0.95]), draws=rp_)


# ---------------------------------------------------------------- Data quality
def data_checks(inp: Inputs, res: Result) -> list[tuple[str, str]]:
    out = []
    j = inp.jalur.asn_tpp
    base_n = inp.dasar["asn_tpp_dasar"]
    if j.iloc[0] / base_n > 1.5:
        out.append(("warning", f"Jumlah penerima TPP melonjak {j.iloc[0]/base_n:.2f}x dari tahun dasar ({int(base_n):,} → {int(j.iloc[0]):,}). "
                    "Pastikan cakupan penerima sama (mis. PPPK baru/guru ikut dihitung?) karena TPP/pegawai kebijakan lama dihitung dari tahun dasar."))
    h = inp.hist
    by = inp.dasar["tahun_dasar"]
    if abs(h.loc["modal", by] - h.loc["modal", by - 1]) / max(h.loc["modal", by - 1], 1) > 0.3:
        out.append(("info", "Belanja modal tahun dasar berubah >30% dari tahun sebelumnya; proyeksi memakai laju normal historis, bukan tren terbaru."))
    if (inp.hist.loc["pemeliharaan"] <= 0).any():
        out.append(("warning", "Ada nilai pemeliharaan ≤ 0 pada data historis."))
    d = res.df
    if (d.sisa_silpa < 0).any():
        y = d.index[d.sisa_silpa < 0][0]
        out.append(("warning", f"Defisit tahunan melampaui SiLPA mulai {y}: asumsi 'SiLPA konstan' perlu dikaji."))
    cum = d.surplus.cumsum() + inp.dasar["silpa"]
    if (cum < 0).any():
        y = d.index[cum < 0][0]
        out.append(("warning", f"Jika SiLPA habis terpakai (tidak diisi ulang), defisit kumulatif melampaui SiLPA mulai {y}."))
    if (d.belanja <= 0).any() or (d.denom_infra <= 0).any():
        y = d.index[(d.belanja <= 0) | (d.denom_infra <= 0)][0]
        out.append(("warning", f"Total belanja (atau belanja di luar transfer) ≤ 0 pada {y}: guncangan yang diisi terlalu besar sehingga rasio tidak terdefinisi (n/a, dihitung tidak patuh)."))
    if (d.pool_barjas_hibah_bansos < 0).any():
        y = d.index[d.pool_barjas_hibah_bansos < 0][0]
        out.append(("warning", f"Pagu barang-jasa/hibah/bansos menjadi NEGATIF mulai {y}: gaji, TPP, modal, BTT dan transfer sudah melampaui total belanja. "
                    "Total belanja tidak cukup menampung komponen yang dikunci; periksa kejadian/asumsi yang diisi."))
    for w in getattr(res, "event_warnings", []):
        out.append(("warning", w))
    if inp.pensiun.index.max() < d.index.max():
        out.append(("info", f"Data pensiun hanya sampai {inp.pensiun.index.max()}; tahun sesudahnya diasumsikan sama dengan tahun terakhir."))
    return out


# ---------------------------------------------------------------- Saran (rule-based, dikuantifikasi)
CATATAN_REGULASI = (
    "Per 29 September 2026 DPR mengesahkan UU APBN 2027 yang (menurut pemberitaan) menunda pemberlakuan batas 30% belanja pegawai "
    "dan 40% belanja infrastruktur, serta memindahkan pembiayaan gaji PPPK daerah ke pusat (sekitar Rp23 T). Pasal, tenggat baru, "
    "dan mekanisme teknisnya belum diverifikasi terhadap naskah UU/juknis. Aplikasi tetap mengukur jarak ke ambang UU HKPD (30%/40%) "
    "sehingga berguna sebagai ukuran kesiapan pada masa transisi."
)


def build_advice(inp: Inputs, p: Params, results: dict, torn: pd.DataFrame | None = None) -> list[dict]:
    T = p.tahun_target
    adv = []
    names = list(results)
    hr = {n: tpp_headroom(r) for n, r in results.items()}
    ik = {n: infra_kebutuhan(r) for n, r in results.items()}
    # 1. Pasal 146 per skenario
    for n in names:
        r = results[n].df.loc[T]
        h = hr[n].loc[T]
        if r.rasio_pegawai <= p.batas_pegawai:
            adv.append(dict(level="ok", judul=f"Pasal 146 — {n}",
                isi=f"Rasio belanja pegawai {T} = {pct(r.rasio_pegawai)} (≤ {pct(p.batas_pegawai,0)}). Masih ada ruang TPP {rp(h.selisih)} "
                    f"(plafon TPP {rp(h.tpp_maks)} ≈ {rp(h.maks_per_bulan,'jt')}/pegawai/bulan)."))
        else:
            thp = "plafon ini masih di atas TPP/pegawai tahun dasar yang disesuaikan inflasi" if h.melindungi_thp else \
                  "plafon ini DI BAWAH TPP/pegawai tahun dasar yang disesuaikan inflasi — take home pay tidak dapat dilindungi"
            adv.append(dict(level="bad", judul=f"Pasal 146 — {n}",
                isi=f"Rasio belanja pegawai {T} = {pct(r.rasio_pegawai)} (> {pct(p.batas_pegawai,0)}). Agar patuh, total TPP maksimum {rp(h.tpp_maks)} "
                    f"(≈ {rp(h.maks_per_bulan,'jt')}/pegawai/bulan), berarti pemangkasan {pct(h.perlu_dipotong_pct,1)} dari skenario; {thp}."))
    # 2. Pasal 147
    k = ik[names[0]].loc[T]
    r0 = results[names[0]].df.loc[T]
    if k.realokasi_penuh_40 <= 0:
        adv.append(dict(level="ok", judul="Pasal 147 — Belanja infrastruktur",
            isi=f"Rasio infrastruktur {T} = {pct(r0.rasio_infra)} (≥ {pct(p.batas_infra,0)})."))
    else:
        lvl = "bad" if k.porsi_pool > 0.25 else "warn"
        real = {"Sangat berat": "tidak realistis tanpa tambahan pendapatan atau reklasifikasi",
                "Tidak layak": "tidak layak: kebutuhan melebihi seluruh belanja barjas/hibah/bansos yang tersedia",
                "Berat": "berat namun masih mungkin dengan prioritisasi",
                "Dapat dicapai": "dapat dicapai"}.get(k.status, "")
        adv.append(dict(level=lvl, judul="Pasal 147 — Belanja infrastruktur",
            isi=f"Rasio infrastruktur {T} = {pct(r0.rasio_infra)} (< {pct(p.batas_infra,0)}). Perlu realokasi {rp(k.realokasi_penuh_40)} dari belanja barang-jasa/hibah/bansos "
                f"= {pct(k.porsi_pool,0)} dari pagu yang tersedia ({real}). Kebutuhan ini sama untuk semua skenario TPP: TPP hanya menggeser komposisi "
                "di dalam total belanja yang ditentukan oleh pendapatan. Definisi 'belanja infrastruktur pelayanan publik' sangat menentukan hasil (lihat tab Risiko)."))
    # 3. Keberlanjutan fiskal
    d = results[names[0]].df
    if (d.sisa_silpa < 0).any() or (d.surplus.cumsum() + inp.dasar["silpa"] < 0).any():
        adv.append(dict(level="warn", judul="Keberlanjutan fiskal",
            isi=f"Proyeksi defisit tahunan {rp(d.surplus.min())} s.d. {rp(d.surplus.max())}; defisit kumulatif {d.index[0]}–{T} = {rp(d.surplus.cumsum().loc[T])} "
                f"vs SiLPA tahun dasar {rp(inp.dasar['silpa'])}. Asumsi 'SiLPA konstan' berarti SiLPA harus terisi ulang tiap tahun."))
    # 4. Tuas
    if torn is not None and len(torn):
        top = torn.iloc[0]
        adv.append(dict(level="info", judul="Tuas paling berpengaruh pada rasio pegawai",
            isi="; ".join(f"{r['Perubahan asumsi']} → {r['Δ rasio pegawai (poin %)']:+.2f} poin" for _, r in torn.head(3).iterrows()) + "."))
    # 5. Rekomendasi jalur
    best = min(names, key=lambda n: results[n].df.loc[T, "rasio_pegawai"])
    worst = max(names, key=lambda n: results[n].df.loc[T, "rasio_pegawai"])
    if results[worst].df.loc[T, "rasio_pegawai"] > p.batas_pegawai:
        adv.append(dict(level="info", judul="Rekomendasi kebijakan TPP",
            isi=f"Skenario '{worst}' tidak patuh pada {T}. Gunakan jalur penyesuaian bertahap (tab Batas TPP) agar rasio turun linear ke {pct(p.batas_pegawai,0)}, "
                f"atau tetapkan TPP ≤ plafon tahunan. Skenario '{best}' adalah yang terdekat dengan kepatuhan."))
    return adv


# ---------------------------------------------------------------- Kejadian tak terduga
def dampak_kejadian(res: Result, res0: Result) -> pd.DataFrame:
    """Perbandingan hasil DENGAN vs TANPA kejadian (satu skenario TPP), per tahun."""
    a, b = res.df, res0.df
    p = res.params
    h1, h0 = tpp_headroom(res), tpp_headroom(res0)
    return pd.DataFrame({
        "pendapatan_dasar": b.pendapatan, "pendapatan_kejadian": a.pendapatan, "d_pendapatan": a.pendapatan - b.pendapatan,
        "belanja_dasar": b.belanja, "belanja_kejadian": a.belanja, "d_belanja": a.belanja - b.belanja,
        "rasio_pegawai_dasar": b.rasio_pegawai, "rasio_pegawai_kejadian": a.rasio_pegawai, "d_rasio_pegawai": a.rasio_pegawai - b.rasio_pegawai,
        "rasio_infra_dasar": b.rasio_infra, "rasio_infra_kejadian": a.rasio_infra, "d_rasio_infra": a.rasio_infra - b.rasio_infra,
        "pagu_barjas_dasar": b.pool_barjas_hibah_bansos, "pagu_barjas_kejadian": a.pool_barjas_hibah_bansos,
        "tpp_maks_dasar": h0.tpp_maks, "tpp_maks_kejadian": h1.tpp_maks, "d_tpp_maks": h1.tpp_maks - h0.tpp_maks,
        "surplus_dasar": b.surplus, "surplus_kejadian": a.surplus,
    }, index=a.index)


def dampak_per_kejadian(inp: Inputs, p: Params, scen: str, names: list | None = None) -> pd.DataFrame:
    """Atribusi: jalankan model dengan HANYA satu kejadian pada satu waktu (dibanding tanpa kejadian) pada tahun target."""
    from engine import run as _run
    T = p.tahun_target
    inp0 = ev.without_events(inp)
    tpp0 = all_scenarios(inp0, p)[scen]
    bdf = _run(inp0, p, tpp0, scen).df
    b = bdf.loc[T]
    rows = []
    for nm in (names if names is not None else ev.Shocks(inp, list(inp.jalur.index)).names()):
        i1 = ev.only_event(inp, nm)
        rdf = _run(i1, p, all_scenarios(i1, p)[scen], scen).df
        r = rdf.loc[T]
        dd = (rdf.rasio_pegawai - bdf.rasio_pegawai) * 100
        di = (rdf.rasio_infra - bdf.rasio_infra) * 100
        def _peak(x):
            return "n/a (rasio tidak terdefinisi)" if x.notna().sum() == 0 else f"{x[x.abs().idxmax()]:+.2f} poin ({x.abs().idxmax()})"
        rows.append({"Kejadian": nm, "Puncak Δ rasio pegawai": _peak(dd), "Puncak Δ rasio infra": _peak(di), "Δ pendapatan (Rp M)": (r.pendapatan - b.pendapatan) / 1e9, "Δ belanja (Rp M)": (r.belanja - b.belanja) / 1e9,
                     "Δ rasio pegawai (poin %)": (r.rasio_pegawai - b.rasio_pegawai) * 100, "Δ rasio infra (poin %)": (r.rasio_infra - b.rasio_infra) * 100,
                     "Δ pagu barjas/hibah/bansos (Rp M)": (r.pool_barjas_hibah_bansos - b.pool_barjas_hibah_bansos) / 1e9,
                     "Δ SiLPA tersedia (Rp M)": (r.sisa_silpa - b.sisa_silpa) / 1e9})
    out = pd.DataFrame(rows)
    if len(out):
        out["_a"] = (out["Δ pendapatan (Rp M)"].abs() + out["Δ belanja (Rp M)"].abs() + out["Δ rasio pegawai (poin %)"].abs() * 1e3
                     + out["Δ rasio infra (poin %)"].abs() * 1e3).fillna(0)
        out = out.sort_values("_a", ascending=False).drop(columns="_a").reset_index(drop=True)
    return out


def advice_kejadian(inp: Inputs, p: Params, results: dict, results0: dict) -> list[dict]:
    """Saran adaptif bila ada kejadian: seberapa besar guncangan, apakah status kepatuhan berubah, apa yang harus digeser."""
    T = p.tahun_target
    adv = []
    n0 = list(results)[0]
    c = dampak_kejadian(results[n0], results0[n0]).loc[T]
    dpend, dB = c.d_pendapatan, c.d_belanja
    adv.append(dict(level="info", judul=f"Kejadian tak terduga — ukuran guncangan pada {T}",
        isi=f"Dibanding tanpa kejadian: pendapatan {rp(dpend)}, total belanja {rp(dB)}, pagu barang-jasa/hibah/bansos "
            f"{rp(c.pagu_barjas_kejadian - c.pagu_barjas_dasar)}. Rasio pegawai {pct(c.rasio_pegawai_dasar)} → {pct(c.rasio_pegawai_kejadian)}, "
            f"rasio infrastruktur {pct(c.rasio_infra_dasar)} → {pct(c.rasio_infra_kejadian)}."))
    if dpend < 0:
        adv.append(dict(level="info", judul="Catatan asumsi saat pendapatan turun",
            isi="Belanja modal dan pemeliharaan dianggap TIDAK ikut terpotong kecuali Anda mengisinya sebagai baris kejadian, sehingga rasio infrastruktur "
                "dapat tampak membaik hanya karena total belanja mengecil. Bila pemda juga memangkas modal/pemeliharaan, isi barisnya agar hasil realistis."))
    # pegawai: status berbalik?
    for n in results:
        a, b = results[n].df.loc[T], results0[n].df.loc[T]
        h1, h0 = tpp_headroom(results[n]).loc[T], tpp_headroom(results0[n]).loc[T]
        if b.rasio_pegawai <= p.batas_pegawai < a.rasio_pegawai:
            adv.append(dict(level="bad", judul=f"Kejadian membalik status Pasal 146 — {n}",
                isi=f"Tanpa kejadian skenario ini patuh ({pct(b.rasio_pegawai)}); dengan kejadian menjadi {pct(a.rasio_pegawai)}. "
                    f"Plafon TPP turun dari {rp(h0.tpp_maks)} menjadi {rp(h1.tpp_maks)} (selisih {rp(h1.tpp_maks - h0.tpp_maks)}); "
                    f"TPP skenario {rp(h1.tpp_skenario)} perlu dipangkas {pct(h1.perlu_dipotong_pct,1)} agar patuh."))
        elif a.rasio_pegawai > p.batas_pegawai and a.rasio_pegawai > b.rasio_pegawai + 1e-9:
            adv.append(dict(level="warn", judul=f"Kejadian memperberat Pasal 146 — {n}",
                isi=f"Rasio {pct(b.rasio_pegawai)} → {pct(a.rasio_pegawai)} (sudah di atas batas sebelum kejadian). Pemangkasan TPP yang diperlukan "
                    f"naik dari {pct(h0.perlu_dipotong_pct,1)} menjadi {pct(h1.perlu_dipotong_pct,1)}."))
        elif b.rasio_pegawai > p.batas_pegawai >= a.rasio_pegawai:
            adv.append(dict(level="ok", judul=f"Kejadian memperbaiki Pasal 146 — {n}",
                isi=f"Rasio {pct(b.rasio_pegawai)} → {pct(a.rasio_pegawai)}: skenario menjadi patuh."))
    # belanja non-pegawai yang harus menyerap
    pool0, pool1 = c.pagu_barjas_dasar, c.pagu_barjas_kejadian
    if pool0 > 0 and pool1 < pool0:
        lvl = "bad" if pool1 <= 0 else ("warn" if (pool0 - pool1) / pool0 > 0.25 else "info")
        isi = (f"Karena gaji/TPP relatif kaku, guncangan diserap pagu barang-jasa/hibah/bansos: turun {rp(pool0 - pool1)} "
               f"({pct((pool0 - pool1) / pool0, 0)} dari pagu {T}).")
        if pool1 <= 0:
            isi += " Pagu itu habis: komponen kaku sudah melebihi total belanja — perlu tambahan pendapatan, pembiayaan, atau pemangkasan TPP/pegawai."
        adv.append(dict(level=lvl, judul="Penyerap guncangan: belanja barang-jasa, hibah, bansos", isi=isi))
    # infrastruktur
    k1, k0 = infra_kebutuhan(results[n0]).loc[T], infra_kebutuhan(results0[n0]).loc[T]
    if k1.realokasi_penuh_40 > 0 and abs(k1.realokasi_penuh_40 - k0.realokasi_penuh_40) > 1e6:
        adv.append(dict(level="warn" if k1.porsi_pool <= 0.5 else "bad", judul="Pasal 147 setelah kejadian",
            isi=f"Realokasi untuk mencapai {pct(p.batas_infra,0)}: {rp(k0.realokasi_penuh_40)} → {rp(k1.realokasi_penuh_40)}; "
                f"porsi dari pagu yang tersedia {pct(k0.porsi_pool,0)} → {pct(k1.porsi_pool,0)} ({k1.status})."))
    # fiskal
    d1 = results[n0].df
    cum1 = d1.surplus.cumsum() + inp.dasar["silpa"]
    if (d1.surplus.loc[:T] < 0).any() and (c.surplus_kejadian < c.surplus_dasar):
        adv.append(dict(level="warn", judul="Kondisi kas setelah kejadian",
            isi=f"Surplus/defisit {T}: {rp(c.surplus_dasar)} → {rp(c.surplus_kejadian)}; defisit kumulatif s.d. {T} {rp(d1.surplus.cumsum().loc[T])} "
                f"vs SiLPA {rp(inp.dasar['silpa'])}" + (f" (SiLPA habis mulai {d1.index[cum1 < 0][0]})." if (cum1 < 0).any() else ".")))
    return adv
#---
