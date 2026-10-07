# Proyeksi Kepatuhan Pemda terhadap UU HKPD (Pasal 146 & 147)

Aplikasi Streamlit untuk memproyeksikan rasio **belanja pegawai (≤ 30%)** dan **belanja infrastruktur (≥ 40%)**
dan menghasilkan **saran preskriptif** (plafon TPP, jalur penyesuaian, kebutuhan realokasi, sensitivitas, simulasi).
(`tests/`).

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
| `io_utils.py` | baca/tulis template Excel (termasuk sheet kejadian opsional) |
| `app.py` | antarmuka Streamlit |
| `data/template_input_hkpd.xlsx` | template sekaligus data contoh Magelang |
| `tests/test_engine.py` | tes regresi terhadap angka narasi kajian + modul kejadian + snapshot model dasar (`snapshot_baseline.csv`) |

Jalankan tes: `python tests/test_engine.py` (atau `pytest`).

## Catatan penting
Hasil adalah informasi pendukung keputusan, bukan opini hukum. Periksa selalu status regulasi terbaru
(UU APBN 2027 memuat penundaan mandatory spending menurut pemberitaan 29/9/2026; naskah belum diverifikasi).
