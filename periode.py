"""Setup (asumsi periode) yang digerakkan dari sidebar.

Satu objek `Setup` menjadi sumber kebenaran untuk:
  - rentang data historis (tahun_awal .. tahun_dasar), horizon proyeksi (tahun_dasar+1 .. tahun_akhir), tahun target kepatuhan
  - klasifikasi tahun: normal / abnormal / pemulihan / rujukan rata-rata
  - parameter pertumbuhan: jumlah tahun pemulihan, batas pencilan, lantai pemulihan
Template Excel dibuat dari Setup (struktur menyesuaikan), tabel lama bisa diselaraskan ke Setup baru, dan Setup -> Params mesin.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
import numpy as np
import pandas as pd
import events as ev

JENIS = ["Kabupaten", "Kota", "Provinsi"]

HIST_ROWS = [
    ("inflasi", "Laju inflasi (%) — hanya perlu bila inflasi TPP diambil dari data historis"),
    ("pajak", "4.1.01 Pajak Daerah"),
    ("retribusi", "4.1.02 Retribusi Daerah"),
    ("kekayaan", "4.1.03 Hasil Pengelolaan Kekayaan Daerah yang Dipisahkan"),
    ("lain_pad", "4.1.04 Lain-lain PAD yang Sah"),
    ("trf_pusat", "4.2.01 Pendapatan Transfer Pemerintah Pusat"),
    ("trf_antar", "4.2.02 Pendapatan Transfer Antar Daerah"),
    ("hibah", "4.3.01 Pendapatan Hibah"),
    ("pend_lain", "4.3.03 Lain-lain Pendapatan Sesuai Peraturan"),
    ("peg_total", "5.1.01 Belanja Pegawai (total, termasuk tunjangan guru)"),
    ("barjas", "5.1.02 Belanja Barang dan Jasa"),
    ("belanja_hibah", "5.1.05 Belanja Hibah"),
    ("bansos", "5.1.06 Belanja Bantuan Sosial"),
    ("modal", "5.2 Belanja Modal"),
    ("btt", "5.3 Belanja Tidak Terduga"),
    ("transfer", "5.4 Belanja Transfer (bagi hasil + bantuan keuangan ke bawahan)"),
    ("pemeliharaan", "Memo: Beban/Belanja Pemeliharaan (bagian dari Barang & Jasa)"),
]
DASAR_WAJIB = [
    ("gaji_pns", "Belanja gaji & tunjangan PNS (tahun dasar)"),
    ("gaji_pppk", "Belanja gaji & tunjangan PPPK (tahun dasar, sesuai APBD)"),
    ("tpp", "Belanja TPP ASN (tahun dasar)"),
    ("insentif_pajak", "Insentif ASN pemungutan pajak (tahun dasar)"),
    ("insentif_retribusi", "Insentif ASN pemungutan retribusi (tahun dasar)"),
    ("tunjangan_guru", "Tunjangan guru TPG+TKG+Tamsil (dikeluarkan dari rasio)"),
    ("asn_tpp_dasar", "Jumlah ASN penerima TPP (tahun dasar)"),
    ("silpa", "SiLPA tahun dasar (dianggap konstan)"),
    ("retribusi_kesehatan", "Retribusi pelayanan kesehatan (tetap, di luar basis insentif)"),
]
DASAR_OPSIONAL = [
    ("trf_dau", "OPSIONAL: DAU tahun dasar (Rp) — agar pemotongan DAU saja bisa dimodelkan"),
    ("trf_dbh", "OPSIONAL: DBH tahun dasar (Rp)"),
    ("trf_dak", "OPSIONAL: DAK fisik+nonfisik tahun dasar (Rp)"),
]
GOLONGAN = ["I/a", "I/b", "I/c", "I/d", "II/a", "II/b", "II/c", "II/d", "III/a", "III/b", "III/c", "III/d", "IV/a", "IV/b", "IV/c", "IV/d", "IV/e"]


def _tup(x) -> tuple:
    return tuple(sorted({int(v) for v in (x or [])}))


@dataclass
class Setup:
    jenis_pemda: str = "Kabupaten"
    tahun_awal: int = 2016          # tahun pertama data historis
    tahun_dasar: int = 2022         # APBD/realisasi terakhir yang dipakai sebagai dasar proyeksi
    tahun_akhir: int = 2027         # tahun terakhir proyeksi (horizon)
    tahun_target: int = 2027        # tahun kepatuhan yang dievaluasi
    tahun_normal: tuple = (2017, 2018, 2019)
    tahun_abnormal: tuple = (2020, 2021)
    tahun_pemulihan: tuple = (2022,)
    n_pemulihan: int = 2
    tahun_rata: tuple = (2016, 2017, 2018, 2019)
    outlier_cap: float = 5.0
    floor_pemulihan: bool = True

    def __post_init__(self):
        for k in ("tahun_awal", "tahun_dasar", "tahun_akhir", "tahun_target", "n_pemulihan"):
            setattr(self, k, int(getattr(self, k)))
        for k in ("tahun_normal", "tahun_abnormal", "tahun_pemulihan", "tahun_rata"):
            setattr(self, k, _tup(getattr(self, k)))
        self.outlier_cap = float(self.outlier_cap)
        self.floor_pemulihan = bool(self.floor_pemulihan)

    @property
    def hist_years(self) -> list:
        return list(range(self.tahun_awal, self.tahun_dasar + 1))

    @property
    def proj_years(self) -> list:
        return list(range(self.tahun_dasar + 1, self.tahun_akhir + 1))

    # ------------------------------------------------------------ validasi
    def errors(self) -> list:
        e = []
        if not (self.tahun_awal < self.tahun_dasar < self.tahun_akhir):
            e.append("Urutan tahun harus: tahun awal < tahun dasar < tahun akhir proyeksi.")
            return e
        lo, hi = self.tahun_awal + 1, self.tahun_dasar
        if not self.tahun_normal:
            e.append("Tahun normal wajib diisi (minimal satu tahun) — dipakai menghitung laju pertumbuhan normal.")
        bad = [y for y in self.tahun_normal if not lo <= y <= hi]
        if bad:
            e.append(f"Tahun normal {bad} di luar {lo}–{hi} (tahun normal butuh data tahun sebelumnya dan ≤ tahun dasar).")
        both = sorted(set(self.tahun_normal) & set(self.tahun_abnormal))
        if both:
            e.append(f"Tahun {both} dipilih sebagai normal sekaligus abnormal.")
        bad = [y for y in self.tahun_abnormal if not self.tahun_awal <= y <= self.tahun_dasar]
        if bad:
            e.append(f"Tahun abnormal {bad} di luar {self.tahun_awal}–{self.tahun_dasar}.")
        if self.n_pemulihan > 0:
            if not self.tahun_pemulihan:
                e.append("Tahun acuan laju pemulihan wajib diisi bila jumlah tahun pemulihan > 0.")
            bad = [y for y in self.tahun_pemulihan if not lo <= y <= hi]
            if bad:
                e.append(f"Tahun acuan pemulihan {bad} di luar {lo}–{hi}.")
        if not 0 <= self.n_pemulihan <= len(self.proj_years):
            e.append(f"Jumlah tahun pemulihan harus 0–{len(self.proj_years)} (panjang horizon).")
        if not self.tahun_rata:
            e.append("Tahun rujukan rata-rata (BTT, rasio belanja/pendapatan) wajib diisi.")
        bad = [y for y in self.tahun_rata if not self.tahun_awal <= y <= self.tahun_dasar]
        if bad:
            e.append(f"Tahun rujukan rata-rata {bad} di luar {self.tahun_awal}–{self.tahun_dasar}.")
        bad = sorted(set(self.tahun_rata) & set(self.tahun_abnormal))
        if bad:
            e.append(f"Tahun rujukan rata-rata {bad} adalah tahun abnormal — keluarkan salah satunya.")
        if self.tahun_target not in self.proj_years:
            e.append(f"Tahun target {self.tahun_target} harus berada di horizon {self.proj_years[0]}–{self.proj_years[-1]}.")
        if self.outlier_cap <= 1:
            e.append("Batas pencilan harus > 1 (kali).")
        return e

    def warnings(self) -> list:
        w = []
        abn = set(self.tahun_abnormal)
        dropped = [y for y in self.tahun_normal if (y - 1) in abn]
        if dropped:
            w.append(f"Laju tahun normal {dropped} dibuang dari rata-rata karena tahun sebelumnya abnormal.")
        if self.n_pemulihan == 0:
            w.append("Jumlah tahun pemulihan = 0: seluruh horizon memakai laju normal.")
        return w

    # ------------------------------------------------------------ konversi
    def to_params(self, **kw):
        from engine import Params
        return Params(n_pemulihan=self.n_pemulihan, tahun_normal=self.tahun_normal, tahun_rata=self.tahun_rata,
                      tahun_abnormal=self.tahun_abnormal, tahun_pemulihan=self.tahun_pemulihan or None,
                      outlier_cap=self.outlier_cap, floor_pemulihan=self.floor_pemulihan, tahun_target=self.tahun_target, **kw)

    def to_df(self) -> pd.DataFrame:
        j = lambda t: ",".join(str(y) for y in t)
        rows = [("jenis_pemda", self.jenis_pemda, "Provinsi / Kabupaten / Kota (mengubah label transfer ke bawahan)"),
                ("tahun_awal", self.tahun_awal, "Tahun pertama data historis"),
                ("tahun_dasar", self.tahun_dasar, "Tahun dasar proyeksi (APBD/realisasi terakhir)"),
                ("tahun_akhir", self.tahun_akhir, "Tahun terakhir proyeksi"),
                ("tahun_target", self.tahun_target, "Tahun kepatuhan yang dievaluasi"),
                ("tahun_normal", j(self.tahun_normal), "Tahun yang laju tumbuhnya dirata-rata sebagai laju normal"),
                ("tahun_abnormal", j(self.tahun_abnormal), "Tahun tak normal (mis. pandemi) — tidak dipakai"),
                ("tahun_pemulihan", j(self.tahun_pemulihan), "Tahun yang pertumbuhannya dipakai sebagai laju pemulihan"),
                ("n_pemulihan", self.n_pemulihan, "Jumlah tahun proyeksi memakai laju pemulihan"),
                ("tahun_rata", j(self.tahun_rata), "Tahun rujukan rata-rata level (BTT, rasio belanja/pendapatan)"),
                ("outlier_cap", self.outlier_cap, "Laju > batas ini (kali) dibuang sebagai pencilan"),
                ("floor_pemulihan", int(self.floor_pemulihan), "1 = laju pemulihan < 100% dianggap 100%")]
        return pd.DataFrame(rows, columns=["parameter", "nilai", "keterangan"])

    @staticmethod
    def from_df(df: pd.DataFrame) -> "Setup":
        d = {str(r["parameter"]).strip(): r["nilai"] for _, r in df.iterrows()}
        def tup(v):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return ()
            return tuple(int(float(x)) for x in str(v).replace(";", ",").split(",") if x.strip())
        base = Setup()
        return Setup(jenis_pemda=str(d.get("jenis_pemda", base.jenis_pemda)),
                     tahun_awal=int(float(d.get("tahun_awal", base.tahun_awal))), tahun_dasar=int(float(d.get("tahun_dasar", base.tahun_dasar))),
                     tahun_akhir=int(float(d.get("tahun_akhir", base.tahun_akhir))), tahun_target=int(float(d.get("tahun_target", base.tahun_akhir))),
                     tahun_normal=tup(d.get("tahun_normal")), tahun_abnormal=tup(d.get("tahun_abnormal")),
                     tahun_pemulihan=tup(d.get("tahun_pemulihan")), n_pemulihan=int(float(d.get("n_pemulihan", base.n_pemulihan))),
                     tahun_rata=tup(d.get("tahun_rata")), outlier_cap=float(d.get("outlier_cap", base.outlier_cap)),
                     floor_pemulihan=bool(int(float(d.get("floor_pemulihan", 1)))))


def pemda xxx() -> Setup:
    return Setup()


# ---------------------------------------------------------------- template adaptif
def template_tables(s: Setup) -> dict:
    """Tabel kosong dengan struktur mengikuti Setup (kolom tahun sebagai teks, siap untuk editor UI)."""
    hist = pd.DataFrame({"kode": [k for k, _ in HIST_ROWS], "uraian": [u for _, u in HIST_ROWS]})
    for y in s.hist_years:
        hist[str(y)] = np.nan
    rows = [("tahun_dasar", "Tahun dasar (otomatis dari setup sidebar)", float(s.tahun_dasar))]
    rows += [(k, u, np.nan) for k, u in DASAR_WAJIB + DASAR_OPSIONAL]
    dasar = pd.DataFrame(rows, columns=["kode", "uraian", "nilai"])
    pen = pd.DataFrame({"golongan": GOLONGAN, "gaji_tunjangan_per_tahun": np.nan})
    for y in range(s.tahun_dasar, s.tahun_akhir + 1):
        pen[str(y)] = np.nan
    jalur = pd.DataFrame({"tahun": s.proj_years, "asn_penerima_tpp": np.nan, "gaji_pppk": np.nan})
    skn = pd.DataFrame({"tahun": s.proj_years, "Skenario 1": np.nan})
    return {"Historis": hist, "Dasar": dasar, "Pensiun": pen, "Jalur": jalur, "Skenario_TPP": skn,
            "Kejadian": ev.empty_k(), "Asumsi_Kejadian": ev.empty_a()}


def _yint(cols) -> dict:
    out = {}
    for c in cols:
        try:
            f = float(str(c).strip())
            if f == int(f):
                out[int(f)] = c
        except ValueError:
            pass
    return out


def align_tables(s: Setup, tables: dict) -> dict:
    """Selaraskan tabel yang ada ke Setup baru: nilai pada (kode, tahun) yang sama dipertahankan, sel baru kosong.
    Pensiun: kolom tahun baru diisi sama dengan tahun terakhir yang ada (perilaku bawaan mesin); ubah bila ada data."""
    new = template_tables(s)
    old = {k: v for k, v in tables.items() if isinstance(v, pd.DataFrame)}
    if "Historis" in old and "kode" in old["Historis"].columns:
        oh = old["Historis"].set_index("kode")
        ymap = _yint(oh.columns)
        for i, code in enumerate(new["Historis"]["kode"]):
            if code in oh.index:
                for y in s.hist_years:
                    if y in ymap:
                        new["Historis"].loc[i, str(y)] = pd.to_numeric(oh.loc[code, ymap[y]], errors="coerce")
    if "Dasar" in old and "kode" in old["Dasar"].columns:
        od = old["Dasar"].set_index("kode")["nilai"]
        for i, code in enumerate(new["Dasar"]["kode"]):
            if code != "tahun_dasar" and code in od.index:
                new["Dasar"].loc[i, "nilai"] = pd.to_numeric(od[code], errors="coerce")
    if "Pensiun" in old and "golongan" in old["Pensiun"].columns:
        op = old["Pensiun"].copy()
        ymap = _yint(op.columns)
        extra = [g for g in op["golongan"] if g not in set(GOLONGAN) and not pd.isna(g)]
        pen = new["Pensiun"]
        if extra:
            pen = pd.concat([pen, pd.DataFrame({"golongan": extra})], ignore_index=True)
        op = op.set_index("golongan")
        last = max(ymap) if ymap else None
        for i, g in enumerate(pen["golongan"]):
            if g in op.index:
                pen.loc[i, "gaji_tunjangan_per_tahun"] = pd.to_numeric(op.loc[g, "gaji_tunjangan_per_tahun"], errors="coerce")
                for y in range(s.tahun_dasar, s.tahun_akhir + 1):
                    src = y if y in ymap else (last if last is not None and y > last else None)
                    if src is not None:
                        pen.loc[i, str(y)] = pd.to_numeric(op.loc[g, ymap[src]], errors="coerce")
        new["Pensiun"] = pen
    if "Jalur" in old and "tahun" in old["Jalur"].columns:
        oj = old["Jalur"].copy()
        oj["tahun"] = pd.to_numeric(oj["tahun"], errors="coerce")
        oj = oj.dropna(subset=["tahun"]).set_index(oj["tahun"].dropna().astype(int))
        for i, y in enumerate(new["Jalur"]["tahun"]):
            if y in oj.index:
                for c in ("asn_penerima_tpp", "gaji_pppk"):
                    if c in oj.columns:
                        new["Jalur"].loc[i, c] = pd.to_numeric(oj.loc[y, c], errors="coerce")
    if "Skenario_TPP" in old and "tahun" in old["Skenario_TPP"].columns:
        os_ = old["Skenario_TPP"].copy()
        os_["tahun"] = pd.to_numeric(os_["tahun"], errors="coerce")
        os_ = os_.dropna(subset=["tahun"])
        os_.index = os_["tahun"].astype(int)
        cols = [c for c in os_.columns if c != "tahun"]
        if cols:
            skn = pd.DataFrame({"tahun": s.proj_years})
            for c in cols:
                skn[str(c)] = [pd.to_numeric(os_.loc[y, c], errors="coerce") if y in os_.index else np.nan for y in s.proj_years]
            new["Skenario_TPP"] = skn
    for k in ("Kejadian", "Asumsi_Kejadian"):
        if k in old:
            new[k] = old[k].copy()
    return new


def structure_issues(s: Setup, tables: dict) -> list:
    """Ketidakcocokan struktur tabel dengan Setup (tahun kolom/baris)."""
    iss = []
    try:
        hy = set(_yint(tables["Historis"].columns))
        want = set(s.hist_years)
        if hy != want:
            iss.append(f"Sheet Historis berisi tahun {min(hy) if hy else '-'}–{max(hy) if hy else '-'} ({len(hy)} kolom), setup menuntut {s.tahun_awal}–{s.tahun_dasar} ({len(want)} kolom).")
        dz = tables["Dasar"].set_index("kode")["nilai"]
        if "tahun_dasar" in dz.index and int(float(dz["tahun_dasar"])) != s.tahun_dasar:
            iss.append(f"Sheet Dasar bertahun dasar {int(float(dz['tahun_dasar']))}, setup {s.tahun_dasar}.")
        jy = pd.to_numeric(tables["Jalur"]["tahun"], errors="coerce").dropna().astype(int).tolist()
        if sorted(jy) != s.proj_years:
            iss.append(f"Sheet Jalur bertahun {jy[:1] and min(jy)}–{jy[:1] and max(jy)} ({len(jy)} baris), setup menuntut {s.proj_years[0]}–{s.proj_years[-1]} ({len(s.proj_years)} baris).")
    except Exception as e:
        iss.append(f"Struktur tabel tidak terbaca: {e}")
    return iss


def infer_setup(tables: dict, fallback: Setup) -> Setup:
    """Setup dari file: sheet 'Setup' bila ada; jika tidak, tahun disimpulkan dari tabel dan sisanya dipinjam dari `fallback`."""
    if "Setup" in tables and isinstance(tables["Setup"], pd.DataFrame) and len(tables["Setup"]):
        return Setup.from_df(tables["Setup"])
    hy = sorted(_yint(tables["Historis"].columns))
    dz = tables["Dasar"].set_index("kode")["nilai"]
    by = int(float(dz["tahun_dasar"])) if "tahun_dasar" in dz.index else hy[-1]
    jy = pd.to_numeric(tables["Jalur"]["tahun"], errors="coerce").dropna().astype(int).tolist()
    aw, ak = hy[0], max(jy)
    keep = lambda t, lo, hi: tuple(y for y in t if lo <= y <= hi)
    return replace(fallback, tahun_awal=aw, tahun_dasar=by, tahun_akhir=ak, tahun_target=ak,
                   tahun_normal=keep(fallback.tahun_normal, aw + 1, by), tahun_abnormal=keep(fallback.tahun_abnormal, aw, by),
                   tahun_pemulihan=keep(fallback.tahun_pemulihan, aw + 1, by) or (by,), tahun_rata=keep(fallback.tahun_rata, aw, by),
                   n_pemulihan=min(fallback.n_pemulihan, ak - by))


def missing_required(s: Setup, hist: pd.DataFrame, need_inflasi: bool = False) -> list:
    """Sel Historis yang kosong padahal dibutuhkan model (hist: index=kode, kolom=tahun int, SEBELUM fillna)."""
    req = {s.tahun_dasar, s.tahun_dasar - 1}
    for y in s.tahun_normal:
        req |= {y, y - 1}
    if s.n_pemulihan > 0:
        for y in s.tahun_pemulihan:
            req |= {y, y - 1}
    req |= set(s.tahun_rata)
    req -= set(range(0, s.tahun_awal))         # tahun sebelum tahun awal tidak ada
    codes = [k for k, _ in HIST_ROWS if k != "inflasi" or need_inflasi]
    out = []
    for c in codes:
        for y in sorted(req):
            if y in hist.columns and c in hist.index and pd.isna(hist.loc[c, y]):
                out.append(f"{c} {y}")
    return out
