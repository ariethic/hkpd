"""Modul kejadian tak terduga (shock) untuk mesin proyeksi HKPD.

Dua tabel opsional (boleh kosong; bila kosong hasil IDENTIK dengan model tanpa kejadian):

1) Kejadian        : dampak langsung ke pendapatan / belanja / SiLPA per tahun.
2) Asumsi_Kejadian : perubahan asumsi model (laju PAD, pass-through DAU, skala TPP, dst.) per periode.

Aturan baca:
- tahun_selesai kosong  -> kejadian hanya di tahun_mulai; "akhir" -> sampai akhir horizon proyeksi.
- mode "persen"  : nilai dalam % terhadap proyeksi dasar komponen itu pada tahun tsb (negatif = pemotongan).
- mode "rupiah"  : nilai dalam Rupiah per tahun (negatif = pengurangan).
- Semua baris bersifat aditif terhadap proyeksi dasar (tidak saling berlipat).
- Total belanja ditentukan metode proyeksi. Kejadian TIDAK mengubahnya kecuali (a) lewat pendapatan
  (A1/A3 via rasio belanja/pendapatan; A2 via parameter respon belanja) atau (b) baris komponen 'belanja_total'.
  Baris modal/pemeliharaan/tpp/peg_lain/btt/belanja_transfer menggeser komposisi di dalam total belanja
  (selisihnya diserap pagu barang-jasa/hibah/bansos).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

COLS_K = ["kejadian", "tahun_mulai", "tahun_selesai", "komponen", "mode", "nilai", "keterangan"]
COLS_A = ["kejadian", "tahun_mulai", "tahun_selesai", "parameter", "mode", "nilai", "keterangan"]

PAD_KEYS = ["pajak", "retribusi", "kekayaan", "lain_pad"]
REV_ALL = ["pajak", "retribusi", "kekayaan", "lain_pad", "trf_pusat", "trf_antar", "hibah", "pend_lain"]

KOMPONEN = {
    # --- pendapatan
    "trf_pusat": "Pendapatan: transfer pusat (DAU/DBH/DAK)",
    "trf_dau": "Pendapatan: DAU saja (bagian dari transfer pusat; perlu Dasar.trf_dau)",
    "trf_dbh": "Pendapatan: DBH saja (bagian dari transfer pusat; perlu Dasar.trf_dbh)",
    "trf_dak": "Pendapatan: DAK saja (fisik+nonfisik; bagian dari transfer pusat; perlu Dasar.trf_dak)",
    "trf_antar": "Pendapatan: transfer antar daerah (mis. bantuan keuangan/bagi hasil dari pemda tingkat atas)",
    "transfer_total": "Pendapatan: seluruh transfer (pusat + antar daerah) satu angka",
    "pajak": "Pendapatan: pajak daerah",
    "retribusi": "Pendapatan: retribusi",
    "kekayaan": "Pendapatan: hasil kekayaan daerah dipisahkan",
    "lain_pad": "Pendapatan: lain-lain PAD",
    "hibah": "Pendapatan: hibah",
    "pend_lain": "Pendapatan: lain-lain pendapatan",
    "pad": "Pendapatan: seluruh PAD (pajak+retribusi+kekayaan+lain PAD)",
    "pendapatan_total": "Pendapatan: seluruh pendapatan",
    # --- belanja
    "belanja_total": "Belanja: total belanja (menambah/mengurangi pagu total)",
    "modal": "Belanja: belanja modal",
    "pemeliharaan": "Belanja: pemeliharaan",
    "tpp": "Belanja: TPP",
    "peg_lain": "Belanja: pegawai lainnya (di luar gaji, TPP, guru)",
    "btt": "Belanja: belanja tidak terduga (BTT)",
    "belanja_transfer": "Belanja: belanja transfer ke bawahan — hanya menggeser komposisi (total belanja tetap)",
    "belanja_transfer_total": "Belanja: belanja transfer ke bawahan — total belanja ikut berubah (pemda benar-benar memotong/menambah)",
    # --- pembiayaan
    "silpa": "SiLPA: tambahan/pengurangan SiLPA tahun tsb (hanya mode rupiah)",
}
AGG_REV = {"pad": PAD_KEYS, "pendapatan_total": REV_ALL, "transfer_total": ["trf_pusat", "trf_antar"]}
SUB_TRF = ["trf_dau", "trf_dbh", "trf_dak"]   # bagian dari trf_pusat; porsi = nilai Dasar tahun dasar / transfer pusat tahun dasar


def komponen_labels(jenis: str = "Kabupaten") -> dict:
    """Label komponen menyesuaikan jenis pemda (provinsi: bawahan = kab/kota; kab/kota: bawahan = desa)."""
    bawah = "kabupaten/kota" if jenis == "Provinsi" else "desa"
    asal = "pemerintah provinsi" if jenis != "Provinsi" else "provinsi lain/pusat"
    lab = dict(KOMPONEN)
    lab["belanja_transfer"] = f"Belanja: transfer ke {bawah} (bagi hasil, bankeu) — hanya menggeser komposisi, total belanja tetap"
    lab["belanja_transfer_total"] = f"Belanja: transfer ke {bawah} — total belanja ikut berubah (pemda benar-benar memotong/menambah)"
    lab["trf_antar"] = f"Pendapatan: transfer antar daerah (mis. bantuan keuangan dari {asal})"
    return lab

# parameter: (label, satuan) -- nilai diisi dalam persen (100 = 100%), kecuali delta_pad (poin %/thn)
PARAMETER = {
    "delta_pad": "Tambahan laju tumbuh pendapatan sendiri (poin %/tahun)",
    "k_shift": "Pergeseran rasio belanja/pendapatan (%)",
    "tpp_scale": "Skala semua skenario TPP (% ; 100 = normal)",
    "passthrough_dau": "Transfer pusat mengikuti perubahan gaji ASN (%)",
    "pensiun_scale": "Skala jumlah pensiun (% ; 100 = sesuai data)",
    "pppk_pusat_pct": "Gaji PPPK yang ditanggung pusat (%)",
    "kredit_barjas_pct": "Barang-jasa non-pemeliharaan diakui infrastruktur (%)",
    "inflasi_tpp": "Inflasi TPP kebijakan lama (%/tahun)",
    "r_insentif_pajak": "Insentif pemungutan pajak (% dari pajak)",
    "r_insentif_retribusi": "Insentif pemungutan retribusi (% dari retribusi)",
}
MODE_K = {"persen": "persen", "%": "persen", "rupiah": "rupiah", "rp": "rupiah"}
MODE_A = {"ganti": "ganti", "tambah": "tambah"}


def empty_k() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object) for c in COLS_K})


def empty_a() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object) for c in COLS_A})


def _prep(df, cols) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame({c: pd.Series(dtype=object) for c in cols})
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df[cols].reset_index(drop=True)


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == "" or str(v).strip().lower() == "nan"


def _span(mulai, selesai, years):
    """-> list tahun dalam horizon, atau None bila tahun tak terbaca."""
    m = pd.to_numeric(mulai, errors="coerce")
    if pd.isna(m):
        return None
    if _blank(selesai):
        e = m
    elif str(selesai).strip().lower() in ("akhir", "sd akhir", "s/d akhir", "seterusnya"):
        e = years[-1]
    else:
        e = pd.to_numeric(selesai, errors="coerce")
        if pd.isna(e):
            return None
    return [y for y in years if m <= y <= e]


def _parse(df, cols, name_col, valid_names, valid_modes, years, jenis):
    """Normalisasi satu tabel -> (records, warnings). Baris tanpa nilai diabaikan; baris salah dilewati + peringatan."""
    t = _prep(df, cols)
    recs, warns = [], []
    for i, r in t.iterrows():
        row_no = i + 1
        if _blank(r["nilai"]):
            if not all(_blank(r[c]) for c in cols if c != "nilai"):
                warns.append(f"{jenis} baris {row_no}: kolom 'nilai' kosong, baris diabaikan.")
            continue
        nilai = pd.to_numeric(r["nilai"], errors="coerce")
        if pd.isna(nilai):
            warns.append(f"{jenis} baris {row_no}: nilai '{r['nilai']}' bukan angka, baris dilewati.")
            continue
        nm = str(r[name_col]).strip().lower()
        if nm not in valid_names:
            warns.append(f"{jenis} baris {row_no}: '{r[name_col]}' tidak dikenal (pilihan: {', '.join(valid_names)}), baris dilewati.")
            continue
        md = valid_modes.get(str(r["mode"]).strip().lower())
        if md is None:
            warns.append(f"{jenis} baris {row_no}: mode '{r['mode']}' harus salah satu dari {sorted(set(valid_modes))}, baris dilewati.")
            continue
        ys = _span(r["tahun_mulai"], r["tahun_selesai"], years)
        if ys is None:
            warns.append(f"{jenis} baris {row_no}: tahun_mulai/tahun_selesai tidak terbaca, baris dilewati.")
            continue
        if not ys:
            warns.append(f"{jenis} baris {row_no}: periode di luar horizon proyeksi ({years[0]}–{years[-1]}), tidak berpengaruh.")
            continue
        label = "(tanpa nama)" if _blank(r["kejadian"]) else str(r["kejadian"]).strip()
        recs.append(dict(kejadian=label, years=ys, key=nm, mode=md, nilai=float(nilai)))
    return recs, warns


class Shocks:
    """Hasil kompilasi tabel kejadian untuk satu horizon proyeksi."""

    def __init__(self, inp, years):
        self.years = [int(y) for y in years]
        self.n = len(self.years)
        self.rec_k, w1 = _parse(getattr(inp, "kejadian", None), COLS_K, "komponen", list(KOMPONEN), MODE_K, self.years, "Kejadian")
        keep = []
        for r in self.rec_k:
            if r["key"] == "silpa" and r["mode"] != "rupiah":
                w1.append(f"Kejadian '{r['kejadian']}': komponen silpa hanya boleh mode rupiah, baris dilewati.")
            else:
                keep.append(r)
        self.rec_k = keep
        # porsi jenis transfer pusat (DAU/DBH/DAK) terhadap transfer pusat tahun dasar
        self.share = {}
        d = getattr(inp, "dasar", {}) or {}
        try:
            by = int(d.get("tahun_dasar"))
            tr0 = float(inp.hist.loc["trf_pusat", by])
        except Exception:
            tr0 = 0.0
        for k in SUB_TRF:
            v = d.get(k)
            if v is not None and np.isfinite(v) and tr0 > 0:
                self.share[k] = float(v) / tr0
        keep = []
        for r in self.rec_k:
            if r["key"] in SUB_TRF and r["key"] not in self.share:
                w1.append(f"Kejadian '{r['kejadian']}': komponen {r['key']} butuh nilai '{r['key']}' tahun dasar di sheet Dasar "
                          f"(Rp, kolom nilai) agar porsinya terhadap transfer pusat diketahui; baris dilewati.")
            else:
                keep.append(r)
        self.rec_k = keep
        if any(v > 1.0 + 1e-9 for v in self.share.values()) or sum(self.share.values()) > 1.0 + 1e-9:
            w1.append("Dasar: jumlah DAU+DBH+DAK tahun dasar melebihi transfer pusat tahun dasar (Historis) — periksa isian.")
        self.rec_a, w2 = _parse(getattr(inp, "asumsi_kejadian", None), COLS_A, "parameter", list(PARAMETER), MODE_A, self.years, "Asumsi_Kejadian")
        self.warnings = w1 + w2

    @property
    def aktif(self) -> bool:
        return bool(self.rec_k or self.rec_a)

    # ---- asumsi bervariasi menurut tahun
    def param(self, p, name) -> np.ndarray:
        arr = np.full(self.n, float(getattr(p, name)))
        for r in self.rec_a:
            if r["key"] != name:
                continue
            v = r["nilai"] / 100.0
            for y in r["years"]:
                i = self.years.index(y)
                arr[i] = v if r["mode"] == "ganti" else arr[i] + v
        return arr

    # ---- dampak langsung
    def _delta_key(self, key, base) -> np.ndarray:
        d = np.zeros(self.n)
        for r in self.rec_k:
            if r["key"] != key:
                continue
            for y in r["years"]:
                i = self.years.index(y)
                d[i] += base[i] * r["nilai"] / 100.0 if r["mode"] == "persen" else r["nilai"]
        return d

    def delta(self, key, base) -> np.ndarray:
        return self._delta_key(key, np.asarray(base, dtype=float))

    def apply_rev(self, rev: dict) -> dict:
        """rev: key -> array/list (baseline). Mengembalikan dict baru (tak boleh < 0) setelah dampak kejadian."""
        base = {k: np.asarray(v, dtype=float) for k, v in rev.items()}
        delta = {k: self._delta_key(k, base[k]) for k in REV_ALL}
        for r in self.rec_k:
            if r["key"] not in SUB_TRF:
                continue
            sh = self.share[r["key"]]
            for y in r["years"]:
                i = self.years.index(y)
                cap = base["trf_pusat"][i] * sh                       # jenis transfer tak bisa dipotong melebihi nilainya
                dv = cap * r["nilai"] / 100.0 if r["mode"] == "persen" else r["nilai"]
                delta["trf_pusat"][i] += max(dv, -cap)
        for agg, members in AGG_REV.items():
            for r in self.rec_k:
                if r["key"] != agg:
                    continue
                for y in r["years"]:
                    i = self.years.index(y)
                    tot = sum(base[m][i] for m in members)
                    for m in members:
                        share = base[m][i] / tot if tot > 0 else 1.0 / len(members)
                        delta[m][i] += base[m][i] * r["nilai"] / 100.0 if r["mode"] == "persen" else r["nilai"] * share
        return {k: np.maximum(base[k] + delta[k], 0.0) for k in REV_ALL}

    def names(self) -> list:
        out = []
        for r in self.rec_k + self.rec_a:
            if r["kejadian"] not in out:
                out.append(r["kejadian"])
        return out


def only_event(inp, name):
    """Salinan Inputs yang hanya memuat baris milik kejadian `name` (untuk atribusi dampak per kejadian)."""
    from dataclasses import replace
    def sel(df, cols):
        t = _prep(df, cols)
        lab = t["kejadian"].map(lambda v: "(tanpa nama)" if _blank(v) else str(v).strip())
        return t[lab == name]
    return replace(inp, kejadian=sel(inp.kejadian, COLS_K), asumsi_kejadian=sel(inp.asumsi_kejadian, COLS_A))


def without_events(inp):
    from dataclasses import replace
    return replace(inp, kejadian=empty_k(), asumsi_kejadian=empty_a())


# ---------------------------------------------------------------- template bantuan
CONTOH_K = pd.DataFrame([
    ["Pemotongan transfer pusat 2026", 2026, "akhir", "trf_pusat", "persen", -10, "DAU/DBH dipangkas 10% mulai 2026"],
    ["Pemotongan transfer pusat 2026", 2026, "akhir", "belanja_total", "rupiah", -20e9, "pagu belanja dipangkas tambahan Rp20 M/tahun"],
    ["Bencana alam 2025", 2025, None, "btt", "rupiah", 15e9, "BTT tanggap darurat, sekali"],
    ["Bencana alam 2025", 2025, None, "modal", "persen", -8, "modal digeser ke penanganan bencana"],
    ["Resesi daerah", 2025, 2026, "pad", "persen", -6, "PAD turun 6% selama 2 tahun"],
    ["Penerimaan hibah luar biasa", 2026, None, "silpa", "rupiah", 12e9, "SiLPA tambahan sekali"],
], columns=COLS_K)
CONTOH_A = pd.DataFrame([
    ["Pemotongan transfer pusat 2026", 2026, "akhir", "passthrough_dau", "ganti", 50, "DAU tak lagi sepenuhnya mengikuti gaji ASN"],
    ["Resesi daerah", 2025, 2026, "delta_pad", "tambah", -3, "laju PAD turun 3 poin/tahun"],
    ["Pemotongan transfer pusat 2026", 2026, "akhir", "tpp_scale", "ganti", 90, "TPP diturunkan 10% sebagai respons"],
], columns=COLS_A)


def contoh_tables(years, jenis: str = "Kabupaten"):
    """Contoh pengisian yang tahunnya mengikuti horizon proyeksi (hanya contoh; tidak dibaca aplikasi)."""
    ys = list(years)
    n = len(ys)
    y = lambda i: ys[min(i, n - 1)]
    bawah = "kab/kota" if jenis == "Provinsi" else "desa"
    K = pd.DataFrame([
        [f"Pemotongan transfer pusat {y(2)}", y(2), "akhir", "trf_pusat", "persen", -10, "seluruh transfer pusat dipangkas 10% (satu angka)"],
        [f"Pemotongan DAU & DAK {y(1)}", y(1), "akhir", "trf_dau", "persen", -15, "hanya DAU turun 15% (butuh Dasar.trf_dau)"],
        [f"Pemotongan DAU & DAK {y(1)}", y(1), "akhir", "trf_dak", "rupiah", -5e9, "DAK turun Rp5 M per tahun (butuh Dasar.trf_dak)"],
        [f"Pemotongan transfer pusat {y(2)}", y(2), "akhir", "belanja_total", "rupiah", -20e9, "pagu belanja dipangkas tambahan Rp20 M/tahun"],
        [f"Pemda memangkas transfer ke {bawah}", y(2), "akhir", "belanja_transfer_total", "persen", -10, f"transfer ke {bawah} dikurangi 10%; total belanja ikut turun"],
        ["Penurunan transfer antar daerah", y(1), y(2), "trf_antar", "persen", -20, "bantuan keuangan antar daerah turun 20%"],
        ["Bencana alam", y(1), None, "btt", "rupiah", 15e9, "BTT tanggap darurat, sekali"],
        ["Bencana alam", y(1), None, "modal", "persen", -8, "modal digeser ke penanganan bencana"],
        ["Resesi daerah", y(1), y(2), "pad", "persen", -6, "PAD turun 6% selama 2 tahun"],
        ["Penerimaan luar biasa", y(2), None, "silpa", "rupiah", 12e9, "SiLPA tambahan sekali"],
    ], columns=COLS_K)
    A = pd.DataFrame([
        [f"Pemotongan transfer pusat {y(2)}", y(2), "akhir", "passthrough_dau", "ganti", 50, "DAU tak lagi sepenuhnya mengikuti gaji ASN"],
        ["Resesi daerah", y(1), y(2), "delta_pad", "tambah", -3, "laju PAD turun 3 poin/tahun"],
        [f"Pemotongan transfer pusat {y(2)}", y(2), "akhir", "tpp_scale", "ganti", 90, "TPP diturunkan 10% sebagai respons"],
    ], columns=COLS_A)
    return K, A
