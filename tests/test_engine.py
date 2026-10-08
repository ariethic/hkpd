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



# ---------------------------------------------------------------- setup adaptif (tahun/asumsi dari sidebar)
import io as _io
import periode as pr
import io_utils as iou
from engine import rec_factor, nor_factor, _derived_hist

T0 = iou.tables_from_excel(DATA)
MG = pr.magelang()


def _shift_tables(t, k):
    """Geser semua tahun +k (kolom/baris/tahun_dasar) -> data sama, kalender berbeda."""
    out = {n: d.copy() for n, d in iou.normalize_tables(t).items()}
    h = out["Historis"]; h.columns = [c + k if isinstance(c, (int, np.integer)) else c for c in h.columns]
    p_ = out["Pensiun"]; p_.columns = [c + k if isinstance(c, (int, np.integer)) else c for c in p_.columns]
    out["Jalur"]["tahun"] = out["Jalur"]["tahun"] + k
    out["Skenario_TPP"]["tahun"] = out["Skenario_TPP"]["tahun"] + k
    d = out["Dasar"]; d.loc[d["kode"] == "tahun_dasar", "nilai"] = d.loc[d["kode"] == "tahun_dasar", "nilai"] + k
    return out


def _shift_setup(s, k):
    sh = lambda t: tuple(y + k for y in t)
    return pr.Setup(jenis_pemda=s.jenis_pemda, tahun_awal=s.tahun_awal + k, tahun_dasar=s.tahun_dasar + k, tahun_akhir=s.tahun_akhir + k,
                    tahun_target=s.tahun_target + k, tahun_normal=sh(s.tahun_normal), tahun_abnormal=sh(s.tahun_abnormal),
                    tahun_pemulihan=sh(s.tahun_pemulihan), n_pemulihan=s.n_pemulihan, tahun_rata=sh(s.tahun_rata),
                    outlier_cap=s.outlier_cap, floor_pemulihan=s.floor_pemulihan)


def _runs(t, s, **kw):
    i = iou.inputs_from_tables(t, s)
    return run_all(i, s.to_params(**kw))


def test_setup_magelang_identik_dengan_params_default():
    a = run_all(inp, Params())
    b = _runs(T0, MG)
    for k in a:
        assert np.allclose(a[k].df.values, b[k].df.values, rtol=1e-12, atol=1e-6)


def test_invarian_geser_kalender():
    base = _runs(T0, MG)
    for k in (1, -3, 5):
        r = _runs(_shift_tables(T0, k), _shift_setup(MG, k))
        for n in base:
            assert np.allclose(base[n].df.values, r[n].df.values, rtol=1e-12, atol=1e-6), (k, n)
            assert list(r[n].df.index) == [y + k for y in base[n].df.index]


def test_tahun_abnormal_boleh_kosong_tetapi_normal_wajib():
    t = iou.normalize_tables(T0)
    h = t["Historis"].copy(); h[2020] = np.nan                      # 2020 abnormal -> tak dipakai
    t2 = dict(t, Historis=h)
    base = _runs(T0, MG)
    r = _runs(t2, MG)
    assert np.allclose(base["RPJMD"].df.values, r["RPJMD"].df.values, rtol=1e-12, atol=1e-6)
    h = t["Historis"].copy(); h[2018] = np.nan                       # 2018 normal -> wajib
    try:
        iou.inputs_from_tables(dict(t, Historis=h), MG)
        raise AssertionError("harus gagal")
    except ValueError as e:
        assert "sel kosong" in str(e) and "2018" in str(e)


def test_tahun_normal_dan_abnormal_mengubah_laju():
    i = iou.inputs_from_tables(T0, MG)
    h = _derived_hist(i.hist)
    p1 = MG.to_params()
    g = lambda y: float(h.loc["pajak", y] / h.loc["pajak", y - 1])
    assert abs(nor_factor(h.loc["pajak"], p1) - np.mean([g(2017), g(2018), g(2019)])) < 1e-12
    s2 = pr.Setup(**{**MG.__dict__, "tahun_normal": (2018, 2019)})
    assert abs(nor_factor(h.loc["pajak"], s2.to_params()) - np.mean([g(2018), g(2019)])) < 1e-12
    # laju yang menyentuh tahun abnormal dibuang otomatis (2022 dibanding 2021 abnormal)
    s3 = pr.Setup(**{**MG.__dict__, "tahun_normal": (2018, 2019, 2022)})
    assert abs(nor_factor(h.loc["pajak"], s3.to_params()) - np.mean([g(2018), g(2019)])) < 1e-12
    assert any("dibuang" in w for w in s3.warnings())


def test_pemulihan_multi_tahun_dan_nol():
    i = iou.inputs_from_tables(T0, MG)
    h = _derived_hist(i.hist)
    g = lambda y: float(h.loc["pajak", y] / h.loc["pajak", y - 1])
    s2 = pr.Setup(**{**MG.__dict__, "tahun_pemulihan": (2021, 2022)})
    exp = max(np.mean([g(2021), g(2022)]), 1.0)
    assert abs(rec_factor(h.loc["pajak"], s2.to_params(), 2022) - exp) < 1e-12
    # lama pemulihan 0 -> semua tahun memakai laju normal
    s0 = pr.Setup(**{**MG.__dict__, "n_pemulihan": 0})
    d = run(i, s0.to_params(), all_scenarios(i, s0.to_params())[KEBIJAKAN_LAMA]).df
    exp = sum(h.loc[k, 2022] * nor_factor(h.loc[k], s0.to_params()) for k in ["pajak", "retribusi", "kekayaan", "lain_pad"])
    assert abs(d.pad.loc[2023] - exp) < 1.0
    # lantai pemulihan dimatikan memberi hasil berbeda bila ada laju < 1
    s_nf = pr.Setup(**{**MG.__dict__, "floor_pemulihan": False})
    f_on, f_off = rec_factor(h.loc["lain_pad"], MG.to_params(), 2022), rec_factor(h.loc["lain_pad"], s_nf.to_params(), 2022)
    assert g_ok(h, "lain_pad") == (f_on != f_off)


def g_ok(h, k):
    return float(h.loc[k, 2022] / h.loc[k, 2021]) < 1


def test_validasi_setup():
    bad = lambda **kw: pr.Setup(**{**MG.__dict__, **kw}).errors()
    assert bad() == []
    assert bad(tahun_normal=())                                   # wajib
    assert bad(tahun_normal=(2020, 2021, 2017))                   # normal & abnormal tumpang tindih
    assert bad(tahun_normal=(2016,))                              # normal tak punya data tahun sebelumnya
    assert bad(tahun_target=2030) and bad(tahun_akhir=2021) and bad(n_pemulihan=9)
    assert bad(tahun_rata=(2016, 2020))                           # rujukan memuat abnormal
    assert bad(tahun_pemulihan=(), n_pemulihan=2) and not bad(tahun_pemulihan=(), n_pemulihan=0)
    assert bad(outlier_cap=1.0)


def test_template_adaptif_dan_roundtrip():
    s = pr.Setup(tahun_awal=2015, tahun_dasar=2023, tahun_akhir=2029, tahun_target=2028, tahun_normal=(2018, 2019), tahun_abnormal=(2020, 2021),
                 tahun_pemulihan=(2022, 2023), n_pemulihan=1, tahun_rata=(2017, 2018, 2019))
    assert s.errors() == []
    t = iou.tables_from_excel(_io.BytesIO(iou.template_bytes(s)))
    assert pr.structure_issues(s, t) == [] and pr.infer_setup(t, MG) == s
    assert sorted(pr._yint(t["Historis"].columns)) == list(range(2015, 2024)) and t["Jalur"]["tahun"].tolist() == list(range(2024, 2030))
    assert sorted(pr._yint(t["Pensiun"].columns)) == list(range(2023, 2030))
    # data Magelang -> setup berbeda: struktur dilaporkan, align mempertahankan nilai yang cocok
    assert pr.structure_issues(s, T0)
    al = pr.align_tables(s, iou.tables_to_ui(T0))
    assert pr.structure_issues(s, iou.normalize_tables(al)) == []
    h = iou.normalize_tables(al)["Historis"].set_index("kode")
    assert h.loc["pajak", 2019] == iou.normalize_tables(T0)["Historis"].set_index("kode").loc["pajak", 2019] and np.isnan(h.loc["pajak", 2023])
    # template data Magelang kembali identik di hasil
    t1 = iou.tables_from_excel(_io.BytesIO(iou.template_bytes(MG, T0)))
    a, b = _runs(T0, MG), _runs(t1, MG)
    assert max(np.max(np.abs(a[k].df.values - b[k].df.values)) for k in a) == 0.0


def test_setup_df_roundtrip():
    s = pr.Setup(tahun_awal=2014, tahun_dasar=2024, tahun_akhir=2030, tahun_target=2029, tahun_normal=(2016, 2018), tahun_abnormal=(2020,),
                 tahun_pemulihan=(2024,), n_pemulihan=3, tahun_rata=(2016, 2017), outlier_cap=3.5, floor_pemulihan=False, jenis_pemda="Provinsi")
    assert pr.Setup.from_df(s.to_df()) == s


# ---------------------------------------------------------------- jenis transfer (DAU/DBH/DAK, antar daerah, ke bawahan)
def _inp_tr(**dasar):
    d = dict(inp.dasar); d.update(dasar)
    return replace(inp, dasar=d)


def test_potong_dau_saja_dan_batas_nilai():
    tr0 = inp.hist.loc["trf_pusat", 2022]
    i1 = _inp_tr(trf_dau=0.6 * tr0, trf_dbh=0.1 * tr0, trf_dak=0.2 * tr0)
    b = _df(i1)
    K = [["DAU", 2026, "akhir", "trf_dau", "persen", -10, ""]]
    d = _df(replace(i1, kejadian=coerce_event_table("Kejadian", pd.DataFrame(K, columns=ev.COLS_K))))
    assert np.allclose((d.transfer_pusat / b.transfer_pusat - 1).loc[[2026, 2027]], -0.06)          # 10% x porsi DAU 60%
    K = [["DAK", 2026, None, "trf_dak", "rupiah", -9e15, ""]]                                    # tak bisa melebihi nilai DAK
    d = _df(replace(i1, kejadian=coerce_event_table("Kejadian", pd.DataFrame(K, columns=ev.COLS_K))))
    assert abs((d.transfer_pusat - b.transfer_pusat).loc[2026] + 0.2 * b.transfer_pusat.loc[2026]) < 1.0


def test_jenis_transfer_tanpa_data_porsi_diperingatkan():
    K = [["DAU", 2026, None, "trf_dau", "persen", -10, ""]]
    i2 = replace(inp, kejadian=coerce_event_table("Kejadian", pd.DataFrame(K, columns=ev.COLS_K)))
    r = run(i2, Params(), all_scenarios(i2, Params())[KEBIJAKAN_LAMA])
    assert any("Dasar" in w for w in r.event_warnings) and not r.event_active
    assert np.allclose(r.df.values, _df(inp).values, rtol=1e-12, atol=1e-6)


def test_transfer_total_antar_daerah_dan_belanja_transfer_total():
    b = _df(inp)
    d = _df(_with([["x", 2026, None, "transfer_total", "rupiah", -20e9, ""]]))
    assert abs(d.dampak_pendapatan.loc[2026] + 20e9) < 1.0
    d = _df(_with([["x", 2026, None, "trf_antar", "persen", -50, ""]]))
    assert abs(d.dampak_pendapatan.loc[2026] + 0.5 * inp.hist.loc["trf_antar", 2022]) < 1.0
    # transfer ke bawahan: _total mengubah total belanja, tanpa _total hanya menggeser komposisi
    tb = inp.hist.loc["transfer", 2022]
    d1 = _df(_with([["x", 2026, None, "belanja_transfer_total", "persen", -10, ""]]))
    assert abs((d1.belanja - b.belanja).loc[2026] + 0.1 * tb) < 1.0 and abs((d1.belanja_transfer - b.belanja_transfer).loc[2026] + 0.1 * tb) < 1.0
    assert abs((d1.pool_barjas_hibah_bansos - b.pool_barjas_hibah_bansos).loc[2026]) < 1.0
    d2 = _df(_with([["x", 2026, None, "belanja_transfer", "persen", -10, ""]]))
    assert abs((d2.belanja - b.belanja).loc[2026]) < 1.0 and abs((d2.pool_barjas_hibah_bansos - b.pool_barjas_hibah_bansos).loc[2026] - 0.1 * tb) < 1.0


def test_label_komponen_menurut_jenis_pemda():
    assert "desa" in ev.komponen_labels("Kabupaten")["belanja_transfer"] and "kabupaten/kota" in ev.komponen_labels("Provinsi")["belanja_transfer"]
    K, A = ev.contoh_tables([2030, 2031, 2032, 2033], "Provinsi")
    assert set(K["komponen"]) <= set(ev.KOMPONEN) and set(A["parameter"]) <= set(ev.PARAMETER)
    assert K["tahun_mulai"].between(2030, 2033).all()


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("OK", k)
