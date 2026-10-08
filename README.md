# Proyeksi Kepatuhan Pemda terhadap UU HKPD (Pasal 146 & 147)

Aplikasi Streamlit untuk memproyeksikan rasio **belanja pegawai (≤ 30%)** dan **belanja infrastruktur (≥ 40%)**
dan menghasilkan **saran preskriptif** (plafon TPP, jalur penyesuaian, kebutuhan realokasi, sensitivitas, simulasi).
Logika inti mereplikasi kertas kerja Kab. Magelang (F1/F2/F3) dan **divalidasi sampai rupiah** (`tests/`).

## Menjalankan lokal
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy gratis
- **Streamlit Community Cloud**: push folder ini ke GitHub → share.streamlit.io → pilih repo, file utama `app.py`.
- **Hugging Face Spaces** (SDK Streamlit): unggah semua file; `requirements.txt` sudah siap.

## Cara pakai pemda
1. Unduh template Excel dari sidebar, isi (atau langsung edit/tempel di tab *Data & Asumsi*).
2. Unggah file / tempel data → semua tab dan saran otomatis diperbarui.
3. Unduh laporan Excel dari tab *Ringkasan & Saran*.

## Setup periode & asumsi dari sidebar (wajib)
Semua asumsi periode digerakkan dari sidebar, bukan dikunci di kode (`periode.py` → `Setup` → `Params`):
- tahun awal data historis (tidak harus 2016), tahun dasar, tahun akhir proyeksi, tahun target kepatuhan;
- tahun **normal** (laju tumbuh dirata-rata), **abnormal** (dibuang), acuan laju **pemulihan** (boleh lebih dari satu tahun, dirata-rata) dan **lama pemulihan**;
- tahun rujukan rata-rata (BTT, rasio belanja/pendapatan, inflasi), batas pencilan, lantai pemulihan, sumber inflasi TPP, insentif pungut, jenis pemda.
Pilihan awal: **Kab. Magelang** (setup + data contoh) atau **Isi sendiri**.

Template Excel dibuat dari setup: kolom tahun Historis, kolom tahun Pensiun, baris Jalur dan Skenario_TPP mengikuti setup, dan sheet `Setup` ikut tersimpan.
- **Unduh template kosong** sesuai setup, atau **unduh data saat ini** (nilai yang cocok dipertahankan).
- **Unggah**: bila file berisi sheet `Setup`, sidebar otomatis mengikuti file.
- Bila setup diubah sehingga struktur tabel tidak cocok, aplikasi menolak menghitung dengan pesan jelas; tombol **Sesuaikan struktur** mempertahankan nilai yang cocok.
- Sel Historis yang dibutuhkan model (tahun normal, pemulihan, rujukan, dasar, dan tahun sebelumnya) **tidak boleh kosong**; tahun abnormal boleh kosong.
- Regresi adaptif: tes menggeser seluruh kalender Magelang (+1, −3, +5 tahun) dan hasilnya harus identik.

## Pemotongan transfer yang fleksibel
Komponen kejadian (tabel `Kejadian`): `trf_pusat` (satu angka), `trf_dau`/`trf_dbh`/`trf_dak` (satu jenis saja; isi nilai tahun dasarnya di sheet Dasar),
`trf_antar` (antar daerah), `transfer_total` (pusat + antar daerah), `belanja_transfer` (transfer ke kab/kota bagi provinsi atau ke desa bagi kab/kota; menggeser komposisi),
`belanja_transfer_total` (sama, tetapi total belanja ikut berubah). Persen atau rupiah per tahun; jenis transfer tak bisa dipotong melebihi nilainya.

## Kejadian tak terduga (opsional)
Tab **Kejadian Tak Terduga** menerima dua tabel yang boleh dikosongkan (kosong = hasil identik dengan model dasar, diuji):
1. **Kejadian** — dampak langsung per tahun: `kejadian | tahun_mulai | tahun_selesai | komponen | mode | nilai | keterangan`.
   `komponen` mis. `trf_pusat`, `pad`, `pendapatan_total`, `belanja_total`, `modal`, `pemeliharaan`, `tpp`, `peg_lain`, `btt`, `belanja_transfer`, `silpa`.
   `mode` = `persen` (−10 = turun 10% dari proyeksi dasar) atau `rupiah` (per tahun). `tahun_selesai` kosong = 1 tahun; `akhir` = sampai akhir horizon.
2. **Asumsi_Kejadian** — perubahan asumsi per periode: `parameter` (`delta_pad`, `k_shift`, `tpp_scale`, `passthrough_dau`, `pensiun_scale`,
   `pppk_pusat_pct`, `kredit_barjas_pct`, `inflasi_tpp`, `r_insentif_pajak`, `r_insentif_retribusi`), `mode` = `ganti`/`tambah`, nilai dalam persen.

Keluaran: perbandingan dengan vs tanpa kejadian, atribusi per kejadian, saran adaptif (status kepatuhan berbalik, penyerap guncangan, plafon TPP baru,
kebutuhan realokasi, kondisi kas). Contoh pengisian ada di sheet `Contoh_Kejadian` template (diabaikan aplikasi) dan di tab itu sendiri.
Catatan: belanja modal/pemeliharaan tidak otomatis dipangkas saat pendapatan turun; isi barisnya bila pemda memotongnya.

## Struktur
| File | Isi |
|---|---|
| `engine.py` | mesin proyeksi APBD & rasio (murni Python, tanpa Streamlit) |
| `advisor.py` | plafon TPP, jalur, kebutuhan infrastruktur, tornado, Monte Carlo, saran, pemeriksaan data |
| `events.py` | modul kejadian tak terduga: baca/validasi tabel Kejadian & Asumsi_Kejadian, terapkan ke mesin |
| `periode.py` | Setup periode & asumsi (sidebar), validasi, template adaptif, penyelarasan tabel |
| `io_utils.py` | baca/tulis template Excel (termasuk sheet kejadian opsional) |
| `app.py` | antarmuka Streamlit |
| `data/template_input_hkpd.xlsx` | template sekaligus data contoh Magelang |
| `tests/test_engine.py` | tes regresi terhadap angka narasi kajian + modul kejadian + snapshot model dasar (`snapshot_baseline.csv`) |

Jalankan tes: `python tests/test_engine.py` (atau `pytest`).

## Catatan penting
Hasil adalah informasi pendukung keputusan, bukan opini hukum. Periksa selalu status regulasi terbaru
(UU APBN 2027 memuat penundaan mandatory spending menurut pemberitaan 29/9/2026; naskah belum diverifikasi).
