# =========================================================
# TARUH BLOK INI DI BAGIAN PALING ATAS FILE APP.PY ANDA
# =========================================================
import streamlit as st
import pandas as pd
import numpy as np
import streamlit_authenticator as stauth

credentials = {
    "usernames": {
        "admin123": {"name": "Administrator", "password": "PasswordMasuk123"},
        "user_tamu": {"name": "Tamu Spesial", "password": "PasswordTamu456"}
    }
}

authenticator = stauth.Authenticate(
    credentials,
    cookie_name="streamlit_login_cookie",
    key="kunci_rahasia_bebas_apa_saja",
    cookie_expiry_days=30
)

authenticator.login(fields={'Form name': 'Silakan Login'})

# JIKA BELUM LOGIN ATAU PASSWORD SALAH, STOP APLIKASI DI SINI
if st.session_state["authentication_status"] is False:
    st.error('Username atau password salah. Silakan coba lagi.')
    st.stop() # Menghentikan kode agar tidak lanjut ke bawah
elif st.session_state["authentication_status"] is None:
    st.warning('Harap masukkan username dan password Anda.')
    st.stop() # Menghentikan kode agar tidak lanjut ke bawah

# JIKA BERHASIL LOGIN, TAMPILKAN TOMBOL LOGOUT
authenticator.logout('Log out', 'sidebar')

# =========================================================
# DI BAWAH SINI: LANGSUNG TEMPEL SELURUH KODE ASLI CLAUDE
# TANPA PERLU DIUBAH ATAU DIGESER SPASINYA SAMA SEKALI
# =========================================================
st.success(f"Selamat datang, {st.session_state['name']}!")

#----------------------------------------------------------
import io, hashlib
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st


from engine import Params, run_all, all_scenarios, KEBIJAKAN_LAMA
from io_utils import tables_from_excel, tables_to_ui, inputs_from_tables, SHEETS, EVENT_SHEETS, coerce_event_table
import advisor as ad
import events as ev

st.set_page_config(page_title="Proyeksi Kepatuhan UU HKPD", page_icon="📊", layout="wide")
TEMPLATE = Path(__file__).parent / "data" / "template_input_hkpd.xlsx"
APPROACH = {"A3": "Pendekatan 3 — belanja = rasio tahun dasar × pendapatan (direkomendasikan kajian pemda xxx)",
            "A1": "Pendekatan 1 — rasio belanja/pendapatan naik ke rata-rata masa normal setelah masa pemulihan",
            "A2": "Pendekatan 2 — belanja dari penjumlahan tren tiap jenis belanja (bottom-up)"}
M = 1e9  # tampilkan dalam Rp miliar


def show(df, **kw):
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    st.dataframe(df, **kw)


# ------------------------------------------------------------------ state data
def load_demo():
    return tables_to_ui(tables_from_excel(TEMPLATE))

def set_tables(t, src):
    st.session_state.tables_src = {k: v.copy() for k, v in t.items()}   # yang ditampilkan editor
    st.session_state.tables = {k: v.copy() for k, v in t.items()}       # hasil edit -> dipakai hitung
    st.session_state.src = src
    st.session_state.ver = {k: st.session_state.get("ver", {}).get(k, 0) + 1 for k in t}


if "tables" not in st.session_state:
    set_tables(load_demo(), "demo")

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("📊 Proyeksi UU HKPD")
    st.caption("Pasal 146 (belanja pegawai ≤ 30%) & Pasal 147 (belanja infrastruktur ≥ 40%)")
    st.download_button("⬇️ Unduh template Excel", TEMPLATE.read_bytes(), "template_input_hkpd.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    up = st.file_uploader("Unggah template terisi (.xlsx)", type=["xlsx"])
    if up is not None:
        sig_up = hashlib.md5(up.getvalue()).hexdigest()
        if st.session_state.get("src") != sig_up:
            try:
                set_tables(tables_to_ui(tables_from_excel(io.BytesIO(up.getvalue()))), sig_up)
                st.success("Data dimuat dari file Anda.")
            except Exception as e:
                st.error(f"Gagal membaca file: {e}")
    if st.button("↩️ Kembali ke data contoh (Kab. pemda xxx)"):
        set_tables(load_demo(), "demo"); st.rerun()
    use_ev = st.checkbox("Terapkan kejadian tak terduga (tab Kejadian)", True,
                         help="Kosongkan tabel kejadian bila tidak ada. Matikan centang ini untuk melihat model dasar tanpa kejadian.")
    st.divider()
    st.subheader("Parameter regulasi")
    pend = st.selectbox("Metode proyeksi total belanja", list(APPROACH), index=0, format_func=lambda k: APPROACH[k])
    batas_peg = st.number_input("Batas maksimum belanja pegawai (%)", 10.0, 60.0, 30.0, 0.5) / 100
    batas_inf = st.number_input("Batas minimum belanja infrastruktur (%)", 5.0, 80.0, 40.0, 0.5) / 100
    infl = st.number_input("Inflasi untuk TPP kebijakan lama (%/thn)", 0.0, 15.0, 2.78, 0.01) / 100

# data tab dikerjakan lebih dulu agar hasil edit langsung dipakai
TAB_NAMES = ["Ringkasan & Saran", "Proyeksi APBD", "Skenario TPP", "Batas TPP", "Infrastruktur", "Risiko", "Kejadian Tak Terduga", "Data & Asumsi", "Metodologi"]
tabs = st.tabs(TAB_NAMES)

CFG_K = {"komponen": st.column_config.SelectboxColumn("komponen", options=list(ev.KOMPONEN), help="Akun yang terdampak (lihat daftar di bawah)."),
         "mode": st.column_config.SelectboxColumn("mode", options=["persen", "rupiah"], help="persen = % dari proyeksi dasar; rupiah = Rp per tahun"),
         "tahun_mulai": st.column_config.NumberColumn("tahun_mulai", format="%d", step=1),
         "tahun_selesai": st.column_config.TextColumn("tahun_selesai", help="Kosong = hanya tahun mulai. Isi tahun, atau tulis 'akhir' = sampai akhir horizon."),
         "nilai": st.column_config.NumberColumn("nilai", format="%.2f", help="Negatif = pemotongan/pengurangan. Persen ditulis apa adanya (−10 = turun 10%).")}
CFG_A = {"parameter": st.column_config.SelectboxColumn("parameter", options=list(ev.PARAMETER)),
         "mode": st.column_config.SelectboxColumn("mode", options=["ganti", "tambah"], help="ganti = pakai nilai ini; tambah = ditambahkan ke nilai dasar"),
         "tahun_mulai": CFG_K["tahun_mulai"], "tahun_selesai": CFG_K["tahun_selesai"],
         "nilai": st.column_config.NumberColumn("nilai", format="%.2f", help="Dalam persen (100 = 100%); delta_pad dalam poin %/tahun.")}


def table_editor(s, cfg=None):
    st.session_state.tables[s] = st.data_editor(st.session_state.tables_src[s], num_rows="dynamic",
                                                key=f"ed_{s}_{st.session_state.ver[s]}", column_config=cfg)
    txt = st.text_area("Atau tempel tabel lengkap dari Excel (dengan baris judul kolom)", key=f"paste_{s}", height=80)
    if st.button("Terapkan tempelan", key=f"btn_{s}") and txt.strip():
        try:
            new = pd.read_csv(io.StringIO(txt), sep="\t", thousands=",")
            new.columns = [str(c).strip() for c in new.columns]
            if s in EVENT_SHEETS:
                new = coerce_event_table(s, new)
            st.session_state.tables_src[s] = new
            st.session_state.tables[s] = new.copy()
            st.session_state.ver[s] += 1
            st.rerun()
        except Exception as e:
            st.error(f"Format tempelan tidak terbaca: {e}")


def append_row(s, row):
    cur = coerce_event_table(s, st.session_state.tables[s])
    new = coerce_event_table(s, pd.DataFrame([row], columns=list(cur.columns)))
    out = pd.concat([cur, new], ignore_index=True)
    st.session_state.tables_src[s] = out
    st.session_state.tables[s] = out.copy()
    st.session_state.ver[s] += 1
    st.rerun()


def _years_ui():
    try:
        ys = pd.to_numeric(st.session_state.tables["Jalur"]["tahun"], errors="coerce").dropna().astype(int).tolist()
        return ys or list(range(2023, 2028))
    except Exception:
        return list(range(2023, 2028))


with tabs[7]:
    st.subheader("Data & Asumsi")
    st.caption("Edit langsung, atau **salin sel dari Excel lalu tempel (Ctrl+V)** ke tabel. Angka dalam Rupiah penuh. "
               "Tambah baris/kolom tahun bila perlu. Hasil di tab lain otomatis menyesuaikan.")
    helps = {"Historis": "Kolom `kode` jangan diubah. Kolom tahun boleh ditambah (mis. 2023 bila sudah ada).",
             "Dasar": "Rincian belanja pegawai tahun dasar, SiLPA, dan jumlah penerima TPP tahun dasar.",
             "Pensiun": "Jumlah pegawai pensiun per golongan dan rata-rata gaji+tunjangan per tahun. Tahun di luar data = tahun terakhir.",
             "Jalur": "Horizon proyeksi = jumlah baris. Tambah baris untuk memperpanjang horizon (mis. bila batas waktu diundur).",
             "Skenario_TPP": "Total belanja TPP per tahun per skenario. Tambah kolom untuk skenario baru."}
    for s_ in SHEETS:
        with st.expander(f"{s_}", expanded=(s_ == "Dasar")):
            st.caption(helps[s_])
            table_editor(s_)
    st.caption("Tabel kejadian tak terduga (opsional) diisi di tab **Kejadian Tak Terduga**.")

# ------------------------------------------------------------------ tab Kejadian: bagian input (sebelum hitung)
with tabs[6]:
    st.subheader("Kejadian tak terduga (opsional)")
    st.markdown(
        "Isi bila ada guncangan di luar proyeksi dasar, misalnya **pemotongan transfer ke daerah**, penurunan PAD, bencana, atau perubahan kebijakan pusat. "
        "**Kosongkan kedua tabel bila tidak ada kejadian** — hasil akan sama persis dengan model dasar.\n\n"
        "1. **Tabel Kejadian** — dampak langsung ke pendapatan, belanja, atau SiLPA per tahun.\n"
        "2. **Tabel Asumsi Kejadian** — bagaimana kejadian itu mengubah asumsi model (mis. laju PAD, TPP, kaitan transfer pusat dengan gaji ASN).\n\n"
        "Satu kejadian biasanya butuh beberapa baris dengan nama yang sama (mis. *Pemotongan transfer 2026*: baris pendapatan, baris pagu belanja, baris asumsi).")
    with st.expander("Aturan pengisian & daftar komponen/parameter", expanded=False):
        st.markdown("- `tahun_selesai` kosong = hanya `tahun_mulai`; isi `akhir` = sampai akhir horizon.\n"
                    "- `mode` **persen**: % terhadap proyeksi dasar komponen itu (−10 = turun 10%). **rupiah**: Rp per tahun (negatif = berkurang).\n"
                    "- Semua baris bersifat **aditif** terhadap proyeksi dasar (tidak berlipat).\n"
                    "- **Total belanja** mengikuti pendapatan menurut metode proyeksi (rasio belanja/pendapatan). Untuk mengubah pagu belanja langsung, pakai komponen `belanja_total`.\n"
                    "- Baris `modal`, `pemeliharaan`, `tpp`, `peg_lain`, `btt`, `belanja_transfer` **menggeser komposisi** di dalam total belanja; selisihnya diserap pagu barang-jasa/hibah/bansos.\n"
                    "- Asumsi: mode **ganti** memakai nilai baru pada periode itu; **tambah** menambahkannya ke nilai dasar (sidebar).")
        c1, c2 = st.columns(2)
        c1.dataframe(pd.DataFrame({"komponen": list(ev.KOMPONEN), "arti": list(ev.KOMPONEN.values())}), hide_index=True)
        c2.dataframe(pd.DataFrame({"parameter": list(ev.PARAMETER), "arti": list(ev.PARAMETER.values())}), hide_index=True)
        st.caption("Contoh pengisian (tidak dipakai kecuali Anda salin ke tabel):")
        st.dataframe(ev.CONTOH_K, hide_index=True)
        st.dataframe(ev.CONTOH_A, hide_index=True)
    st.markdown("**Tabel Kejadian** — dampak langsung")
    table_editor("Kejadian", CFG_K)
    with st.expander("➕ Tambah satu baris kejadian lewat formulir"):
        with st.form("form_kejadian"):
            ysf = _years_ui()
            f1, f2, f3 = st.columns(3)
            nm_k = f1.text_input("Nama kejadian", "")
            kp = f2.selectbox("Komponen", list(ev.KOMPONEN), format_func=lambda k: f"{k} — {ev.KOMPONEN[k]}")
            md = f3.selectbox("Mode", ["persen", "rupiah"])
            g1, g2, g3 = st.columns(3)
            vl = g1.number_input("Nilai (negatif = pengurangan)", value=0.0, step=1.0, format="%.2f")
            ym = g2.selectbox("Tahun mulai", ysf)
            ys_ = g3.selectbox("Tahun selesai", ["(hanya tahun mulai)"] + ysf + ["akhir"])
            ket = st.text_input("Keterangan", "")
            if st.form_submit_button("Tambahkan ke tabel Kejadian") and vl != 0:
                append_row("Kejadian", [nm_k, ym, "" if ys_.startswith("(") else ys_, kp, md, vl, ket])
    st.markdown("**Tabel Asumsi Kejadian** — perubahan asumsi model akibat kejadian")
    table_editor("Asumsi_Kejadian", CFG_A)
    with st.expander("➕ Tambah satu baris asumsi lewat formulir"):
        with st.form("form_asumsi"):
            ysf = _years_ui()
            f1, f2, f3 = st.columns(3)
            nm_a = f1.text_input("Nama kejadian ", "")
            pr = f2.selectbox("Parameter", list(ev.PARAMETER), format_func=lambda k: f"{k} — {ev.PARAMETER[k]}")
            ma = f3.selectbox("Mode ", ["ganti", "tambah"])
            g1, g2, g3 = st.columns(3)
            va = g1.number_input("Nilai (persen; delta_pad dalam poin %)", value=0.0, step=1.0, format="%.2f")
            ym2 = g2.selectbox("Tahun mulai ", ysf)
            ys2 = g3.selectbox("Tahun selesai ", ["(hanya tahun mulai)"] + ysf + ["akhir"])
            ket2 = st.text_input("Keterangan ", "")
            if st.form_submit_button("Tambahkan ke tabel Asumsi") and (va != 0 or ma == "ganti"):
                append_row("Asumsi_Kejadian", [nm_a, ym2, "" if ys2.startswith("(") else ys2, pr, ma, va, ket2])

# ------------------------------------------------------------------ hitung
try:
    inp_raw = inputs_from_tables(st.session_state.tables)
    inp = inp_raw if use_ev else ev.without_events(inp_raw)
except Exception as e:
    for i in (0, 1, 2, 3, 4, 5):
        with tabs[i]:
            st.error(f"Data input belum lengkap/valid: {e}")
    st.stop()

years = list(inp.jalur.index)
with st.sidebar:
    T = st.selectbox("Tahun target kepatuhan", years, index=min(len(years) - 1, years.index(2027) if 2027 in years else len(years) - 1))
    with st.expander("Tuas skenario lanjutan"):
        fp = st.slider("Efek pensiun di tahun pensiun", 0.0, 1.0, 1.0, 0.05, help="1 = penuh (asumsi kertas kerja). 0,5 = pensiun rata-rata di tengah tahun.")
        pt = st.slider("Transfer pusat mengikuti perubahan gaji ASN", 0.0, 1.0, 1.0, 0.05)
        pc = st.slider("Dukungan pusat atas gaji PPPK (%)", 0, 100, 0, 5) / 100
        pm = st.radio("Bentuk dukungan pusat", ["keluar", "tambah_dau"], format_func=lambda k: {"keluar": "Gaji PPPK keluar dari APBD", "tambah_dau": "Tambahan DAU (belanja tetap)"}[k],
                      help="Ilustratif — mekanisme resmi belum diverifikasi.")
        kb = st.slider("Barang-jasa non-pemeliharaan yang diakui infrastruktur (%)", 0, 100, 0, 5) / 100
        dp = st.slider("Tambahan laju tumbuh pendapatan sendiri (poin/thn)", -5.0, 10.0, 0.0, 0.5) / 100
        ks = st.slider("Pergeseran rasio belanja/pendapatan (%)", -10.0, 10.0, 0.0, 0.5) / 100
        ts = st.slider("Skala semua skenario TPP (%)", 50, 150, 100, 5) / 100
p = Params(pendekatan=pend, batas_pegawai=batas_peg, batas_infra=batas_inf, inflasi_tpp=infl, tahun_target=T,
           faktor_pensiun=fp, passthrough_dau=pt, pppk_pusat_pct=pc, pppk_pusat_mode=pm, kredit_barjas_pct=kb,
           delta_pad=dp, k_shift=ks, tpp_scale=ts)
try:
    results = run_all(inp, p)
except Exception as e:
    st.error(f"Perhitungan gagal: {e}")
    st.stop()
names = list(results)
ev_active = bool(results and results[names[0]].event_active)
results0 = run_all(ev.without_events(inp), p) if ev_active else None
_all = all_scenarios(inp, p)
skipped = [c for c in _all.columns if c not in results]
sig = hashlib.md5((repr(p) + str(use_ev) + "".join(df.to_csv() for df in st.session_state.tables.values())).encode()).hexdigest()

def status(ok): return "✅ Patuh" if ok else "❌ Tidak patuh"
def pct_fmt(x): return "n/a" if not np.isfinite(x) else f"{x*100:.2f}%"

# ------------------------------------------------------------------ tab 0
with tabs[0]:
    st.info(ad.CATATAN_REGULASI)
    if ev_active:
        st.warning("⚠️ Hasil di semua tab **sudah memuat dampak kejadian tak terduga** yang Anda isi. Rincian dan perbandingan dengan model dasar ada di tab *Kejadian Tak Terduga*.")
    if skipped:
        st.warning("Skenario dilewati karena nilai TPP belum lengkap untuk semua tahun proyeksi (sheet Skenario_TPP): " + ", ".join(skipped))
    st.subheader(f"Status kepatuhan tahun {T}")
    rows = []
    for n, r in results.items():
        d = r.df.loc[T]
        rows.append({"Skenario TPP": n, "Rasio belanja pegawai": pct_fmt(d.rasio_pegawai), f"Pasal 146 (≤{batas_peg*100:.0f}%)": status(d.rasio_pegawai <= batas_peg),
                     "TPP skenario (Rp M)": round(d.tpp / M, 1), "Plafon TPP (Rp M)": round(ad.tpp_headroom(r).loc[T, "tpp_maks"] / M, 1),
                     "Rasio infrastruktur": pct_fmt(d.rasio_infra), f"Pasal 147 (≥{batas_inf*100:.0f}%)": status(d.rasio_infra >= batas_inf)})
    show(pd.DataFrame(rows), hide_index=True)
    b = results[names[0]].base
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Rasio pegawai {b['tahun']} (dasar)", pct_fmt(b["rasio_pegawai"]))
    c2.metric(f"Rasio infrastruktur {b['tahun']} (dasar)", pct_fmt(b["rasio_infra"]))
    c3.metric("Realokasi infrastruktur dibutuhkan", ad.rp(ad.infra_kebutuhan(results[names[0]]).loc[T, "realokasi_penuh_40"]))
    c4.metric("TPP/pegawai tahun dasar", ad.rp(b["tpp_per_pegawai"], "jt"))
    st.subheader("Saran preskriptif")
    scen_t = st.selectbox("Skenario untuk analisis tuas", names, index=min(1, len(names) - 1))
    torn = ad.tornado(inp, p, scen_t)
    advice = ad.build_advice(inp, p, results, torn)
    if ev_active:
        advice = ad.advice_kejadian(inp, p, results, results0) + advice
    for a in advice:
        box = {"ok": st.success, "bad": st.error, "warn": st.warning, "info": st.info}[a["level"]]
        box(f"**{a['judul']}** — {a['isi']}")
    checks = ad.data_checks(inp, results[names[0]])
    if checks:
        st.subheader("Pemeriksaan data & asumsi")
        for lv, msg in checks:
            (st.warning if lv == "warning" else st.info)(msg)
    # ekspor
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Ringkasan", index=False)
        pd.DataFrame([{"Tingkat": a["level"], "Judul": a["judul"], "Saran": a["isi"]} for a in advice]).to_excel(xw, sheet_name="Saran", index=False)
        for i, (n, r) in enumerate(results.items(), 1):
            r.df.to_excel(xw, sheet_name=f"Proyeksi{i}")
            ad.tpp_headroom(r).to_excel(xw, sheet_name=f"BatasTPP{i}")
        ad.infra_kebutuhan(results[names[0]]).to_excel(xw, sheet_name="Infrastruktur")
        torn.to_excel(xw, sheet_name="Sensitivitas", index=False)
        if ev_active:
            ad.dampak_kejadian(results[names[0]], results0[names[0]]).to_excel(xw, sheet_name="Dampak_Kejadian")
            ad.dampak_per_kejadian(inp, p, names[0]).to_excel(xw, sheet_name="Dampak_per_Kejadian", index=False)
            coerce_event_table("Kejadian", inp.kejadian).to_excel(xw, sheet_name="Input_Kejadian", index=False)
            coerce_event_table("Asumsi_Kejadian", inp.asumsi_kejadian).to_excel(xw, sheet_name="Input_Asumsi_Kejadian", index=False)
        pd.DataFrame({"Sheet": [f"Proyeksi{i}/BatasTPP{i}" for i in range(1, len(names) + 1)], "Skenario TPP": names}).to_excel(xw, sheet_name="Peta_Sheet", index=False)
    st.download_button("⬇️ Unduh laporan (Excel)", buf.getvalue(), "laporan_proyeksi_hkpd.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------------------------------------------------------ tab 1
with tabs[1]:
    n1 = st.selectbox("Skenario TPP", names, key="n1")
    d = results[n1].df
    tbl = d[["pendapatan", "pad", "transfer_pusat", "belanja", "belanja_pegawai_total", "gaji_pns", "gaji_pppk", "tpp", "pegawai_lain",
              "tunjangan_guru", "modal", "pemeliharaan", "infra", "pool_barjas_hibah_bansos", "surplus", "sisa_silpa"]] / M
    tbl.columns = ["Pendapatan", "  PAD", "  Transfer pusat", "Belanja", "Belanja pegawai (termasuk guru)", "  Gaji PNS", "  Gaji PPPK", "  TPP",
                    "  Pegawai lainnya", "  Tunjangan guru (di luar rasio)", "Belanja modal", "Pemeliharaan", "Belanja infrastruktur",
                    "Barjas+hibah+bansos", "Surplus/(defisit)", "Surplus + SiLPA tahun dasar"]
    st.caption("Rp miliar")
    show(tbl.T.round(1))
    ch = pd.DataFrame({"Rasio belanja pegawai": d.rasio_pegawai * 100, f"Batas {batas_peg*100:.0f}%": batas_peg * 100}, index=d.index.astype(str))
    st.line_chart(ch)

# ------------------------------------------------------------------ tab 2
with tabs[2]:
    cmp_ = pd.DataFrame({n: r.df.rasio_pegawai * 100 for n, r in results.items()})
    cmp_.index = cmp_.index.astype(str)
    cmp_[f"Batas {batas_peg*100:.0f}%"] = batas_peg * 100
    st.subheader("Rasio belanja pegawai per skenario (%)")
    st.line_chart(cmp_)
    show(cmp_.round(2).T)
    st.subheader("Total belanja TPP per skenario (Rp miliar)")
    tp = pd.DataFrame({n: r.df.tpp / M for n, r in results.items()}); tp.index = tp.index.astype(str)
    st.bar_chart(tp)
    pcap = pd.DataFrame({n: r.df.tpp / r.df.asn_tpp / 12 / 1e6 for n, r in results.items()})
    st.subheader("TPP per pegawai per bulan (Rp juta)")
    show(pcap.round(2).T)

# ------------------------------------------------------------------ tab 3
with tabs[3]:
    n3 = st.selectbox("Skenario TPP", names, key="n3")
    r3 = results[n3]
    hr, jp = ad.tpp_headroom(r3), ad.jalur_pegawai(r3)
    st.markdown(f"**Plafon TPP** = {batas_peg*100:.0f}% × total belanja − belanja pegawai lain (di luar guru). Komponen lain dianggap tetap sesuai proyeksi.")
    t1 = pd.DataFrame({"TPP skenario (Rp M)": hr.tpp_skenario / M, "Plafon TPP (Rp M)": hr.tpp_maks / M,
                       "Perlu dipotong": (hr.perlu_dipotong_pct * 100).round(1).astype(str) + "%",
                       "Plafon per pegawai/bulan (Rp jt)": hr.maks_per_bulan / 1e6,
                       "TPP/pegawai/bulan tahun dasar + inflasi (Rp jt)": hr.tpp_per_pegawai_terlindungi / 12 / 1e6,
                       "Take home pay terlindungi?": np.where(hr.melindungi_thp, "Ya", "Tidak")}).round(2)
    show(t1.T)
    st.markdown(f"**Jalur penyesuaian bertahap** — rasio diturunkan linear dari {pct_fmt(r3.base['rasio_pegawai'])} ({r3.base['tahun']}) ke {batas_peg*100:.0f}% pada {T}:")
    t2 = pd.DataFrame({"Rasio target": (jp.rasio_target * 100).round(2), "Rasio proyeksi skenario": (jp.rasio_proyeksi * 100).round(2),
                       "TPP maks mengikuti jalur (Rp M)": (jp.tpp_maks_jalur / M).round(1), "TPP skenario (Rp M)": (jp.tpp_skenario / M).round(1),
                       "Per pegawai/bulan (Rp jt)": (jp.tpp_per_pegawai_jalur / 12 / 1e6).round(2)})
    show(t2.T)
    ch = pd.DataFrame({"TPP skenario": jp.tpp_skenario / M, "Plafon jalur bertahap": jp.tpp_maks_jalur / M, "Plafon bila patuh tiap tahun": hr.tpp_maks / M})
    ch.index = ch.index.astype(str)
    st.line_chart(ch)
    st.caption("Plafon 'patuh tiap tahun' lebih ketat dari ketentuan bila UU hanya mensyaratkan kepatuhan pada tahun target.")

# ------------------------------------------------------------------ tab 4
with tabs[4]:
    n4 = st.selectbox("Skenario TPP", names, key="n4")
    ik = ad.infra_kebutuhan(results[n4])
    st.markdown("**Rasio infrastruktur** = (belanja modal + pemeliharaan) ÷ (total belanja − belanja transfer). "
                "Kekurangan harus digeser dari belanja barang-jasa, hibah, dan bansos.")
    t = pd.DataFrame({"Rasio target (jalur linear)": (ik.rasio_target * 100).round(2), "Rasio proyeksi": (ik.rasio_proyeksi * 100).round(2),
                      "Realokasi sesuai jalur (Rp M)": (ik.realokasi_jalur / M).round(1), "Realokasi bila langsung 40% (Rp M)": (ik.realokasi_penuh_40 / M).round(1),
                      "Pagu barjas/hibah/bansos tersedia (Rp M)": (ik.pool_tersedia / M).round(1),
                      "Porsi pagu yang harus digeser": [f"{x*100:.0f}%" if np.isfinite(x) else ">100%" for x in ik.porsi_pool], "Keterangan": ik.status})
    show(t.T)
    ch = pd.DataFrame({"Rasio proyeksi": ik.rasio_proyeksi * 100, "Target jalur": ik.rasio_target * 100}); ch.index = ch.index.astype(str)
    st.line_chart(ch)
    st.info("Tuas definisi: pada tab sidebar 'Tuas skenario lanjutan' Anda dapat mengakui sebagian belanja barang-jasa sebagai infrastruktur pelayanan publik "
            "untuk melihat sensitivitas terhadap tafsir definisi.")

# ------------------------------------------------------------------ tab 5
with tabs[5]:
    st.subheader("Sensitivitas (tornado)")
    n5 = st.selectbox("Skenario TPP", names, key="n5", index=min(1, len(names) - 1))
    tr = ad.tornado(inp, p, n5)
    show(tr.round(2), hide_index=True)
    st.caption(f"Perubahan rasio pada tahun {T} dibanding asumsi dasar (poin persentase). Negatif = lebih baik untuk rasio pegawai.")
    if ev_active:
        st.caption("Catatan: pada tahun yang punya asumsi kejadian mode 'ganti' untuk parameter yang sama, perubahan tuas di sini tidak berlaku.")
    st.subheader("Simulasi ketidakpastian (Monte Carlo)")
    c1, c2, c3 = st.columns(3)
    sd_pad = c1.number_input("Sebaran tambahan laju PAD (poin/thn)", 0.0, 20.0, 5.0, 0.5) / 100
    sd_k = c2.number_input("Sebaran rasio belanja/pendapatan (%)", 0.0, 10.0, 2.0, 0.5) / 100
    nsim = c3.number_input("Jumlah simulasi", 100, 2000, 300, 100)
    if st.button("Jalankan simulasi"):
        st.session_state.mc = (sig + n5, ad.monte_carlo(inp, p, n5, int(nsim), sd_pad, sd_k))
    if st.session_state.get("mc") and st.session_state.mc[0] == sig + n5:
        mc = st.session_state.mc[1]
        a, b = st.columns(2)
        a.metric(f"Peluang patuh Pasal 146 ({T})", f"{mc['p_peg']*100:.0f}%")
        b.metric(f"Peluang patuh Pasal 147 ({T})", f"{mc['p_infra']*100:.0f}%")
        st.write(f"Rasio pegawai {T}: P5 {mc['peg_q'][0]*100:.1f}% · median {mc['peg_q'][1]*100:.1f}% · P95 {mc['peg_q'][2]*100:.1f}%. "
                 f"Rasio infrastruktur: P5 {mc['infra_q'][0]*100:.1f}% · median {mc['infra_q'][1]*100:.1f}% · P95 {mc['infra_q'][2]*100:.1f}%.")
        st.bar_chart(pd.Series(np.histogram(mc["draws"] * 100, bins=20)[0], index=np.round(np.histogram(mc["draws"] * 100, bins=20)[1][:-1], 1)))
        st.caption("Sebaran bersifat ilustratif (guncangan persisten pada laju pendapatan sendiri dan rasio belanja), bukan hasil estimasi statistik formal.")

# ------------------------------------------------------------------ tab Kejadian: bagian dampak (setelah hitung)
with tabs[6]:
    st.divider()
    st.subheader("Dampak kejadian terhadap kepatuhan")
    ew = results[names[0]].event_warnings
    for w in ew:
        st.warning(w)
    if not use_ev:
        st.info("Centang 'Terapkan kejadian tak terduga' di sidebar dimatikan: hasil = model dasar.")
    elif not ev_active:
        st.info("Belum ada kejadian yang valid pada kedua tabel, sehingga hasil sama dengan model dasar. Isi tabel di atas untuk melihat dampaknya.")
    else:
        n6 = st.selectbox("Skenario TPP", names, key="n6")
        cmp_e = ad.dampak_kejadian(results[n6], results0[n6])
        st.markdown(f"**Perbandingan dengan vs tanpa kejadian — {n6}**")
        tb = pd.DataFrame({
            "Pendapatan: Δ (Rp M)": cmp_e.d_pendapatan / M, "Total belanja: Δ (Rp M)": cmp_e.d_belanja / M,
            "Pagu barjas/hibah/bansos dasar (Rp M)": cmp_e.pagu_barjas_dasar / M, "Pagu barjas/hibah/bansos kejadian (Rp M)": cmp_e.pagu_barjas_kejadian / M,
            "Rasio pegawai dasar": cmp_e.rasio_pegawai_dasar * 100, "Rasio pegawai kejadian": cmp_e.rasio_pegawai_kejadian * 100,
            "Rasio infra dasar": cmp_e.rasio_infra_dasar * 100, "Rasio infra kejadian": cmp_e.rasio_infra_kejadian * 100,
            "Plafon TPP dasar (Rp M)": cmp_e.tpp_maks_dasar / M, "Plafon TPP kejadian (Rp M)": cmp_e.tpp_maks_kejadian / M,
            "Surplus/defisit dasar (Rp M)": cmp_e.surplus_dasar / M, "Surplus/defisit kejadian (Rp M)": cmp_e.surplus_kejadian / M,
        }).round(2)
        show(tb.T)
        chp = pd.DataFrame({"Tanpa kejadian": cmp_e.rasio_pegawai_dasar * 100, "Dengan kejadian": cmp_e.rasio_pegawai_kejadian * 100,
                            f"Batas {batas_peg*100:.0f}%": batas_peg * 100})
        chp.index = chp.index.astype(str)
        st.caption("Rasio belanja pegawai (%)")
        st.line_chart(chp)
        chi = pd.DataFrame({"Tanpa kejadian": cmp_e.rasio_infra_dasar * 100, "Dengan kejadian": cmp_e.rasio_infra_kejadian * 100,
                            f"Batas {batas_inf*100:.0f}%": batas_inf * 100})
        chi.index = chi.index.astype(str)
        st.caption("Rasio belanja infrastruktur (%)")
        st.line_chart(chi)
        st.markdown(f"**Atribusi per kejadian** (satu kejadian pada satu waktu, tahun target {T})")
        show(ad.dampak_per_kejadian(inp, p, n6).round(2), hide_index=True)
        st.markdown("**Saran adaptif**")
        for a in ad.advice_kejadian(inp, p, results, results0):
            box = {"ok": st.success, "bad": st.error, "warn": st.warning, "info": st.info}[a["level"]]
            box(f"**{a['judul']}** — {a['isi']}")

# ------------------------------------------------------------------ tab 8
with tabs[8]:
    st.markdown("""
### Alur model (mengikuti kertas kerja Kab. pemda xxx, divalidasi hingga rupiah)
1. **Periode data**: laju tumbuh *normal* = rata-rata 2017–2019; laju *pemulihan* = pertumbuhan tahun dasar vs tahun sebelumnya (dipakai 2 tahun pertama); 2020–2021 dianggap tidak normal dan tidak dipakai. Laju pemulihan < 100% dianggap 100%; laju > 5× dibuang sebagai pencilan (mis. hibah 2018).
2. **Pendapatan**: PAD & hibah tumbuh dua fase; transfer antar daerah tetap; transfer pusat = tahun lalu − gaji PNS pensiun + perubahan gaji PPPK (karena DAU memuat komponen gaji).
3. **Total belanja** (Pendekatan 3): rasio belanja/pendapatan tahun dasar × pendapatan. Belanja transfer tetap, BTT = rata-rata 2016–2019, belanja modal & pemeliharaan tumbuh dengan laju normal.
4. **Belanja pegawai**: gaji PNS = tahun lalu − gaji pegawai pensiun; gaji PPPK dari jalur input; TPP dari skenario; insentif pajak/retribusi 5% dari target; komponen lain tetap. **Tunjangan guru dikeluarkan dari rasio** (Pasal 146).
5. **Rasio** — Pasal 146: (belanja pegawai − tunjangan guru) ÷ total belanja ≤ 30%. Pasal 147: (belanja modal + pemeliharaan) ÷ (total belanja − belanja transfer) ≥ 40%.
6. **Lapisan preskriptif** (tambahan di aplikasi): plafon TPP, jalur penyesuaian linear, kebutuhan realokasi infrastruktur dan tingkat kelayakannya, sensitivitas, simulasi, dan pemeriksaan data.

### Keterbatasan yang perlu dipahami
- Tidak ada kenaikan gaji berkala/umum dan tidak ada rekrutmen PNS baru kecuali tercermin dalam jalur PPPK/TPP yang Anda isi.
- Belanja pegawai yang dikeluarkan dari rasio mengikuti kertas kerja (hanya tunjangan guru); sesuaikan bila ada petunjuk teknis yang berbeda.
- Definisi 'belanja infrastruktur pelayanan publik' di sini = belanja modal + pemeliharaan (seperti kertas kerja). Tafsir yang lebih luas dapat mengubah hasil secara drastis.
- SiLPA dianggap konstan (diisi ulang tiap tahun); lihat pemeriksaan defisit kumulatif.
- Hasil adalah **informasi untuk pengambilan keputusan**, bukan rekomendasi hukum.

### Modul kejadian tak terduga
- Dua tabel opsional (*Kejadian* dan *Asumsi Kejadian*). Kosong = hasil identik dengan model dasar (diuji).
- Dampak langsung bersifat aditif terhadap proyeksi dasar. Pemotongan transfer pusat mengurangi pendapatan; total belanja ikut turun lewat rasio belanja/pendapatan (Pendekatan 1 dan 3) atau lewat parameter respon belanja (Pendekatan 2), sedangkan belanja pegawai relatif kaku sehingga rasio pegawai naik.
- Belanja modal/pemeliharaan **tidak otomatis dipangkas**; isi barisnya bila pemda memotongnya.
- Asumsi yang dapat diubah per periode: laju PAD, rasio belanja/pendapatan, skala TPP, pass-through DAU, skala pensiun, dukungan pusat atas PPPK, pengakuan barjas, inflasi TPP, insentif pungut.
- Atribusi per kejadian dihitung dengan menjalankan model satu kejadian pada satu waktu; efek gabungan tidak harus sama dengan jumlah efek individual.
""")

    





