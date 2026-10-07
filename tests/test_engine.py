"""Tes regresi: angka diambil dari narasi kajian (Tabel 4.11, 4.15-4.22) dan kertas kerja Excel."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
from engine import Params, run, run_all, all_scenarios, KEBIJAKAN_LAMA
from io_utils import load_inputs

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "template_input_hkpd.xlsx"
inp = load_inputs(DATA)
sc = all_scenarios(inp, Params())


def ratios(approach, scen):
    return (run(inp, Params(pendekatan=approach), sc[scen]).df.rasio_pegawai * 100).round(2).tolist()


def test_ratio_pegawai_tabel_4_11():
    assert ratios("A1", KEBIJAKAN_LAMA) == [35.02, 33.91, 29.08, 27.52, 25.85]
    assert ratios("A2", KEBIJAKAN_LAMA) == [36.68, 36.33, 35.53, 34.62, 33.82]
    assert ratios("A3", KEBIJAKAN_LAMA) == [35.02, 33.91, 32.45, 30.71, 28.85]


def test_ratio_pegawai_skenario_tpp():
    assert ratios("A3", "Kepmen 900-4700") == [44.18, 42.74, 40.88, 38.60, 36.17]
    assert ratios("A3", "RPJMD") == [34.28, 34.54, 33.08, 31.33, 29.44]


def test_rasio_infra_dan_realokasi():
    for approach, expected in [("A1", 904241412775), ("A2", 572971325543), ("A3", 754201581720)]:
        d = run(inp, Params(pendekatan=approach), sc[KEBIJAKAN_LAMA]).df.loc[2027]
        need = 0.4 * d.denom_infra - d.infra
        assert abs(need - expected) < 1.0, (approach, need)
    d = run(inp, Params(), sc[KEBIJAKAN_LAMA]).df
    assert (d.rasio_infra * 100).round(2).tolist() == [11.57, 11.58, 11.37, 11.08, 10.68]


def test_kondisi_tahun_dasar():
    b = run(inp, Params(), sc[KEBIJAKAN_LAMA]).base
    assert round(b["rasio_pegawai"] * 100, 2) == 32.77 and round(b["rasio_infra"] * 100, 2) == 11.55


def test_tpp_kebijakan_lama_tabel_4_6():
    assert abs(sc[KEBIJAKAN_LAMA].loc[2027] - 164728065045) < 1.0


def test_tuas_arah_benar():
    base = run(inp, Params(), sc["Kepmen 900-4700"]).df.loc[2027, "rasio_pegawai"]
    assert run(inp, Params(tpp_scale=0.5), sc["Kepmen 900-4700"]).df.loc[2027, "rasio_pegawai"] < base
    assert run(inp, Params(pppk_pusat_pct=0.5), sc["Kepmen 900-4700"]).df.loc[2027, "rasio_pegawai"] < base
    assert run(inp, Params(kredit_barjas_pct=0.5), sc[KEBIJAKAN_LAMA]).df.loc[2027, "rasio_infra"] > 0.1068


def test_horizon_diperpanjang():
    import copy, pandas as pd
    i2 = copy.deepcopy(inp)
    last = i2.jalur.iloc[-1]
    for y in (2028, 2029, 2030):
        i2.jalur.loc[y] = last
        i2.tpp_skenario.loc[y] = i2.tpp_skenario.iloc[-1]
    r = run_all(i2, Params(tahun_target=2030))
    assert len(r[KEBIJAKAN_LAMA].df) == 8 and np.isfinite(r["RPJMD"].df.rasio_pegawai).all()


# ---------------------------------------------------------------- modul kejadian tak terduga
import pickle
import pandas as pd
from dataclasses import replace
import events as ev
from io_utils import coerce_event_table
import advisor as ad


def _with(k=None, a=None):
    return replace(inp, kejadian=coerce_event_table("Kejadian", pd.DataFrame(k or [], columns=ev.COLS_K)),
                   asumsi_kejadian=coerce_event_table("Asumsi_Kejadian", pd.DataFrame(a or [], columns=ev.COLS_A)))


def _df(i, **kw):
    p = Params(**kw)
    return run(i, p, all_scenarios(i, p)[KEBIJAKAN_LAMA]).df


def test_kejadian_kosong_identik():
    base = _df(inp)
    for i2 in (ev.without_events(inp), _with(), _with([["", None, "", "", "", None, "catatan saja"]])):
        d = _df(i2)
        assert np.allclose(d.values, base.values, rtol=1e-12, atol=1e-6)
    # sheet contoh tidak boleh ikut terbaca dari template
    assert len(inp.kejadian) == 0 and len(inp.asumsi_kejadian) == 0


def test_potong_transfer_pusat_persen():
    b = _df(inp)
    d = _df(_with([["DAU", 2026, "akhir", "trf_pusat", "persen", -10, ""]]))
    assert np.allclose(d.transfer_pusat.loc[[2023, 2024, 2025]], b.transfer_pusat.loc[[2023, 2024, 2025]])
    assert np.allclose(d.transfer_pusat.loc[[2026, 2027]], 0.9 * b.transfer_pusat.loc[[2026, 2027]])
    assert (d.belanja.loc[[2026, 2027]] < b.belanja.loc[[2026, 2027]]).all()
    assert d.rasio_pegawai.loc[2027] > b.rasio_pegawai.loc[2027]      # gaji kaku -> rasio naik
    assert abs(d.dampak_pendapatan.loc[2027] + 0.1 * b.transfer_pusat.loc[2027]) < 1.0


def test_mode_rupiah_dan_agregat_pad():
    b = _df(inp)
    d = _df(_with([["x", 2025, 2026, "pad", "rupiah", -10e9, ""]]))
    assert abs((d.pad - b.pad).loc[2025] + 10e9) < 1.0 and abs((d.pad - b.pad).loc[2027]) < 1.0
    d2 = _df(_with([["x", 2025, None, "pendapatan_total", "persen", -5, ""]]))
    assert abs(d2.pendapatan.loc[2025] / b.pendapatan.loc[2025] - 0.95) < 1e-9 and abs(d2.pendapatan.loc[2026] - b.pendapatan.loc[2026]) < 1.0


def test_belanja_total_geser_komposisi_dan_silpa():
    b = _df(inp)
    d = _df(_with([["x", 2027, None, "belanja_total", "rupiah", -30e9, ""], ["x", 2027, None, "silpa", "rupiah", 7e9, ""],
                   ["x", 2027, None, "modal", "persen", -10, ""]]))
    assert abs(d.belanja.loc[2027] - b.belanja.loc[2027] + 30e9) < 1.0
    assert abs(d.sisa_silpa.loc[2027] - b.sisa_silpa.loc[2027] - (7e9 + 30e9)) < 1.0
    assert abs(d.modal.loc[2027] / b.modal.loc[2027] - 0.9) < 1e-9
    # modal turun 10% dengan total belanja tetap -> pagu barjas naik sebesar selisih modal
    d3 = _df(_with([["x", 2027, None, "modal", "persen", -10, ""]]))
    assert abs((d3.pool_barjas_hibah_bansos - b.pool_barjas_hibah_bansos).loc[2027] - 0.1 * b.modal.loc[2027]) < 1.0


def test_asumsi_kejadian():
    b = _df(inp)
    d = _df(_with(a=[["a", 2026, "akhir", "passthrough_dau", "ganti", 50, ""]]))
    assert np.allclose(d.transfer_pusat.loc[[2023, 2024, 2025]], b.transfer_pusat.loc[[2023, 2024, 2025]])
    assert (d.transfer_pusat.loc[[2026, 2027]] > b.transfer_pusat.loc[[2026, 2027]]).all()   # pensiun mengurangi gaji -> pass-through separuh
    d2 = _df(_with(a=[["a", 2024, 2024, "delta_pad", "tambah", -5, ""]]))
    assert d2.pad.loc[2024] < b.pad.loc[2024] and abs(d2.pad.loc[2023] - b.pad.loc[2023]) < 1.0
    # tambah vs ganti pada parameter sidebar
    d3 = _df(_with(a=[["a", 2027, None, "tpp_scale", "tambah", -10, ""]]), tpp_scale=0.8)
    assert abs(d3.tpp.loc[2027] / _df(inp).tpp.loc[2027] - 0.7) < 1e-9


def test_baris_salah_tidak_memecahkan_model():
    i2 = _with([["a", 2026, None, "foo", "persen", -1, ""], ["b", 2026, None, "modal", "xx", -1, ""], ["c", 2040, None, "modal", "persen", -1, ""],
                ["d", "abc", None, "modal", "persen", -1, ""], ["e", 2026, None, "silpa", "persen", 5, ""], ["f", 2026, None, "modal", "persen", None, "tanpa nilai"]])
    r = run(i2, Params(), all_scenarios(i2, Params())[KEBIJAKAN_LAMA])
    assert len(r.event_warnings) == 6 and not r.event_active
    assert np.allclose(r.df.values, _df(inp).values, rtol=1e-12, atol=1e-6)


def test_atribusi_dan_saran():
    i2 = _with([["Potong DAU", 2026, "akhir", "trf_pusat", "persen", -10, ""], ["Bencana", 2025, None, "btt", "rupiah", 15e9, ""]],
               [["Potong DAU", 2026, "akhir", "tpp_scale", "ganti", 90, ""]])
    p = Params()
    r, r0 = run_all(i2, p), run_all(ev.without_events(i2), p)
    adv = ad.advice_kejadian(i2, p, r, r0)
    assert any("membalik status" in a["judul"] for a in adv)
    tb = ad.dampak_per_kejadian(i2, p, KEBIJAKAN_LAMA)
    assert set(tb["Kejadian"]) == {"Potong DAU", "Bencana"} and tb.iloc[0]["Kejadian"] == "Potong DAU"
    assert (ad.dampak_kejadian(r[KEBIJAKAN_LAMA], r0[KEBIJAKAN_LAMA]).d_pendapatan.loc[2026:] < 0).all()


def test_snapshot_model_dasar_tidak_berubah():
    """Keluaran model dasar (tanpa kejadian) harus sama dengan snapshot sebelum modul kejadian ditambahkan."""
    snap = pathlib.Path(__file__).resolve().parent / "snapshot_baseline.csv"
    old = pd.read_csv(snap)
    for (a, k), g in old.groupby(["varian", "skenario"]):
        kw = dict(pendekatan=a) if a != "kw" else dict(delta_pad=.02, k_shift=.03, tpp_scale=.9, passthrough_dau=.5, pensiun_scale=1.25,
                                                      faktor_pensiun=.5, pppk_pusat_pct=.5, kredit_barjas_pct=.4, inflasi_tpp=.05)
        n = run_all(inp, Params(**kw))[k].df
        g = g.set_index("tahun")
        for c in n.columns:
            if c in g.columns:
                assert np.allclose(g[c].values, n.loc[g.index, c].values, rtol=1e-9, atol=1e-3), (a, k, c)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("OK", k)
