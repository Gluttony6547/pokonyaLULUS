# Laporan QA Prog5

**Tanggal pengujian:** 8 Oktober 2026  
**Situs:** https://pokonya-lulus.vercel.app/  
**Lingkungan:** deployment Vercel, browser Chromium, waktu pemeriksaan sekitar 12.00 WIB  
**Status:** layak untuk demo dan eksplorasi data dengan catatan. Jangan anggap sinyal sebagai data penutupan final sebelum temuan P1 di bawah ditangani.

## Ringkasan

Dashboard dan API produksi dapat diakses. Saya memeriksa pemilihan saham dan horizon, grafik, indikator, riwayat prediksi, tema, responsivitas, status kosong dan gagal, endpoint API, serta pengujian proyek lokal. Seluruh 50 kombinasi dari 10 ticker dan 5 horizon yang dicoba menghasilkan prediksi dengan ticker, horizon, grafik, dan riwayat yang sesuai. Tidak ada kesalahan JavaScript pada alur normal.

Temuan utama menyangkut waktu data, bukan kegagalan halaman. Pada 8 Oktober, run #18 menyimpan baris ADRO bertanggal 8 Oktober pada 10.15 WIB. Halaman menyebut harga Yahoo Finance sebagai data akhir hari dan menandai prediksi tersebut Fresh, padahal baris itu dibuat sebelum sesi perdagangan hari tersebut selesai. Pengunjung dapat salah mengira bahwa harga, indikator, dan prediksi memakai data penutupan final.

| Prioritas | Temuan | Dampak |
|---|---|---|
| P1, tinggi | Baris bertanggal hari berjalan ditampilkan sebagai data penutupan final dan Fresh sebelum sesi berakhir | Harga, indikator, sinyal, dan tanggal horizon dapat menyesatkan |
| P2, sedang | Perhitungan tanggal target melewati akhir pekan, tetapi tidak memakai kalender hari libur IDX | Tanggal target bisa bukan hari bursa |
| P2, sedang | Sinyal Buy tetap menjadi elemen paling menonjol saat model berada di luar rentang latih | Pengunjung bisa lebih memperhatikan sinyal daripada peringatan keandalan |

Saya tidak mengubah kode aplikasi atau deployment. Berkas ini adalah satu-satunya keluaran yang dibuat untuk permintaan QA.

## Cakupan dan bukti pengujian

### Antarmuka dan alur pengguna

- Halaman utama dibuka dengan query `?symbol=ADRO&horizon=1`; kartu prediksi, harga, grafik, indikator, riwayat, dan daftar refresh tampil.
- Saya memilih setiap ticker yang tersedia: ADRO, ANTM, BMRI, BNGA, EXCL, INCO, INKP, MEDC, PGAS, dan TLKM.
- Saya menguji tombol T+1, T+5, T+10, T+20, dan T+50 pada setiap ticker. Semua 50 kombinasi berpindah ke ticker dan horizon yang dipilih, menampilkan harga prediksi, grafik, serta lima baris riwayat.
- Pemilihan ticker dan horizon memperbarui URL sehingga tampilan dapat dibagikan. Query tidak dikenal kembali ke ADRO T+1, bukan menampilkan halaman rusak.
- Arah OOD terlihat pada data langsung. Contoh TLKM T+50 menunjukkan prediksi +51,37%, sinyal Buy, OOD z-score -3,17, dan peringatan rentang latih.
- Keadaan kosong diuji dengan respons API kosong yang disimulasikan. Kartu, grafik, indikator, dan riwayat masing-masing menjelaskan data yang tidak tersedia; halaman tetap berfungsi.
- Keadaan gagal diuji dengan respons 503 yang disimulasikan. Halaman menampilkan pesan dan tombol Try again. Setelah request berikutnya diizinkan, retry berhasil menampilkan kartu ADRO dan menghapus pesan gagal.
- Halaman normal tidak menghasilkan `pageerror` atau kesalahan konsol JavaScript. Catatan 404 dan 422 dalam log berasal dari uji input API yang sengaja tidak valid; 503 berasal dari simulasi gangguan.
- Endpoint dokumentasi `/docs`, skema `/openapi.json`, dan `/api/v1/health` masing-masing merespons 200.

### API, data, dan validasi

| Request | Hasil |
|---|---|
| `GET /api/v1/health` | 200; PostgreSQL; 10 ticker; 12.078 baris harga; 12.078 baris indikator; 250 prediksi |
| `GET /api/v1/stocks` | 200; 10 ticker tersimpan |
| `GET /api/v1/prices/ADRO?limit=180` | 200; 180 baris berurutan dari 12 Jan sampai 8 Okt 2026 |
| `GET /api/v1/predictions/ADRO?horizon_days=1&limit=50` | 200; memuat prediksi terbaru dan metadata model |
| `GET /api/v1/runs?limit=10` | 200; run terbaru #18 berstatus completed |
| Harga ticker tidak dikenal | 404, dengan detail bahwa artefak ticker tidak tersedia |
| Horizon `999` | 422, dengan daftar horizon yang didukung |
| Batas harga `limit=1001` | 422, sesuai batas parameter API |

Nilai kartu ADRO T+1 cocok dengan respons API: harga terakhir 2.590 IDR, prediksi 2.635,43 IDR, perubahan +1,75%, ambang 1,5%, dan model `LSTM_ADRO_Target_1.h5`. SHA-256 tampil sebagai awalan di halaman dan tersedia penuh pada API.

### Tampilan, aksesibilitas, dan perangkat

- Ukuran viewport 320, 375, 768, dan 1280 piksel tidak menyebabkan halaman melebar melebihi viewport. Pada 320 piksel, `scrollWidth` dokumen 305 piksel, jadi tidak ada overflow horizontal.
- Tombol horizon, pemilih saham, tombol tema, tautan footer, dan tautan lewati konten memiliki tinggi target 44 piksel pada tampilan 320 piksel.
- Sampel teks dan kontrol yang diperiksa memenuhi WCAG AA pada tema terang dan gelap. Rasio kontras terendah pada sampel: 5,97:1 pada tema terang dan 7,55:1 pada tema gelap.
- Tema gelap aktif pada kunjungan awal sesi ini; kedua tema dapat dirender dan mempertahankan kontras pada elemen yang disampel.
- Tombol merupakan elemen HTML asli dengan status `aria-pressed`; CSS menyediakan indikator `:focus-visible`. Pemeriksaan keyboard manual di browser bersama tidak konsisten, sehingga siklus Tab dan aktivasi Enter tidak saya nyatakan lulus dalam pengujian ini.

### Tes proyek

Perintah `python -m pytest -q` dijalankan dari `Prog5/`: **82 passed, 3 warnings**. Peringatan yang muncul adalah deprecation Starlette TestClient/httpx dan Keras/Torch dengan NumPy. Tidak ada tes yang gagal.

## Temuan terperinci

### P1: Baris hari berjalan dianggap penutupan final

**Bukti:** halaman menyatakan harga berasal dari baris harian akhir sesi Yahoo Finance. API mengembalikan harga ADRO bertanggal `2026-10-08`; run #18 dimulai pukul 03.15 UTC dan selesai 03.16 UTC, setara sekitar 10.15 sampai 10.16 WIB. Pemeriksaan berlangsung sekitar 12.00 WIB pada hari yang sama, sebelum sesi bursa berakhir. Kartu tetap menampilkan Fresh dan memakai harga tersebut untuk indikator serta prediksi. Baris ADRO bertanggal sama mencatat open 2.600, high 2.620, low 2.580, dan close 2.590 IDR.

**Dampak:** nilai close pada candle harian yang belum selesai dapat berubah sampai penutupan. Prediksi bisa berubah berdasarkan input yang belum final, sedangkan pengguna melihat tanggal data, label Fresh, dan uraian akhir hari seolah sesi telah selesai.

**Saran:** jangan menyimpan atau memprediksi dari candle tanggal hari ini sebelum waktu penutupan dan jeda publikasi yang dipilih operator, misalnya 17.30 WIB sesuai pemeriksaan freshness proyek. Alternatifnya, tampilkan status intraday dengan jelas dan jangan menyebutnya data akhir hari. Hitung Fresh terhadap sesi terakhir yang benar-benar selesai, bukan hanya umur kalender tanggal.

**Keyakinan:** 10/10. Waktu run, tanggal baris, waktu pemeriksaan, dan label halaman terlihat langsung pada situs/API.

### P2: Kalender target tidak mengetahui hari libur bursa

**Bukti:** [trading_calendar.py](./prog5/trading_calendar.py) menghitung hari perdagangan sebagai Senin sampai Jumat dan menyatakan hari libur bursa tidak dimodelkan. Halaman menampilkan tanggal target dengan keterangan akhir pekan dilewati. Contoh langsung: T+50 dari 8 Oktober 2026 ditampilkan sebagai 17 Desember 2026.

**Dampak:** bila jendela horizon melewati hari libur IDX, tanggal target yang terlihat dapat jatuh pada hari tanpa sesi perdagangan. Jumlah sesi model dan tanggal kalender yang dipahami pengguna lalu berbeda.

**Saran:** gunakan kalender libur IDX yang dipelihara dan uji batas tahun serta rangkaian libur. Jika kalender tersebut belum tersedia, beri label eksplisit bahwa tanggal hanyalah perkiraan berbasis hari kerja, bukan tanggal sesi IDX yang terverifikasi.

**Keyakinan:** 10/10 untuk keterbatasan kode; dampak terjadi pada horizon yang melintasi hari libur.

### P2: Sinyal tetap dominan saat OOD

**Bukti:** TLKM T+50 langsung menampilkan Buy dan perubahan +51,37% pada bagian atas kartu. OOD z-score -3,17, keterangan di luar rentang, peringatan, dan catatan pipeline muncul lebih bawah.

**Dampak:** hierarki visual memberi perhatian pertama pada sinyal Buy, meski aplikasi sendiri menyebut keluaran tersebut paling tidak dapat dipercaya. Untuk pengunjung yang memindai halaman, peringatan di bagian bawah bisa terlewat.

**Saran:** saat `ood_flag` aktif, tampilkan status “di luar rentang latih” setara atau lebih menonjol daripada sinyal, dan jelaskan bahwa label Buy/Sell tidak layak ditafsirkan sebagai rekomendasi pada kasus tersebut. Evaluasi apakah sinyal perlu diganti dengan status “tidak andal” ketika melewati batas OOD.

**Keyakinan:** 9/10. Tampilan dan payload TLKM T+50 diamati langsung; potensi salah tafsir bergantung pada perilaku pembaca.

## SWOT

| | Catatan |
|---|---|
| **Strengths** | Halaman menghubungkan sinyal ke data yang dapat diperiksa: harga terakhir, perubahan, ambang, model, awalan hash, OOD, tanggal, dan riwayat refresh. API menyediakan health, harga, prediksi, dan riwayat proses tanpa menulis dari browser. Seluruh 50 kombinasi yang dicoba berhasil. Keadaan kosong dan gagal memiliki pesan, grafik diberi nama aksesibel, dan tampilan responsif diuji sampai 320 piksel. |
| **Weaknesses** | Data bertanggal hari ini dapat terlihat sebagai close final sebelum sesi selesai. Tanggal target hanya melewati akhir pekan. Sinyal OOD yang ekstrem tetap mendapat posisi paling menonjol. Antarmuka berbahasa Inggris; bila pengunjung utamanya berbahasa Indonesia, beberapa istilah keuangan dan status perlu dilokalkan. |
| **Opportunities** | Terapkan cutoff sesi final sebelum menghitung Fresh dan membuat prediksi. Tambahkan kalender bursa resmi untuk tanggal target. Jadikan status OOD bagian dari keputusan visual, bukan hanya catatan. Jika sasaran utamanya pengguna lokal, sediakan istilah Indonesia yang konsisten untuk sinyal, indikator, OOD, dan status data. Perlihatkan rincian peringatan pada run, bukan hanya jumlah `warnings` di ringkasan. |
| **Threats** | Ketergantungan pada Yahoo Finance dapat membawa keterlambatan, perubahan format, throttling, atau baris sesi yang masih berjalan. Model dilatih pada rentang 2018-2023, sementara contoh data situs bertanggal 2026; peringatan OOD membantu, tetapi tidak membuktikan bahwa performa periode baru sudah tervalidasi. Angka prediksi besar dapat mendorong keputusan finansial meskipun footer menyebut hasil bukan saran investasi. Ketersediaan jangka panjang Vercel, PostgreSQL, dan penyedia data tidak dapat disimpulkan dari satu sesi pemeriksaan. |

## Batas pengujian

- Pengujian browser dilakukan pada situs produksi dengan interaksi baca saja. Saya tidak menjalankan refresh yang menulis database, mengubah konfigurasi deployment, atau melakukan pengujian beban.
- Respons kosong, 503, dan data invalid disimulasikan dari browser/API. Ini memeriksa reaksi antarmuka, bukan ketahanan semua kegagalan penyedia eksternal.
- Saya tidak memvalidasi akurasi prediksi terhadap hasil harga sesudah target, menghitung ulang seluruh indikator secara independen, atau melakukan audit keamanan penetrasi.
- Jalur keyboard dan persistensi tema setelah reload tidak dinyatakan lulus berdasarkan bukti sesi ini.

## Kesimpulan QA

Fungsi utama situs berjalan dan halaman menangani data yang tersedia dengan baik. Hasil ini mendukung demo riset, bukan penggunaan sebagai alat keputusan investasi. Perbaiki pemisahan data intraday dan penutupan final terlebih dahulu. Setelah itu, tambahkan kalender sesi IDX dan ubah hierarki sinyal untuk input OOD sebelum menganggap label prediksi cukup aman untuk dibaca tanpa konteks.