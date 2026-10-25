# PRD: Sinyal Historis Tahap 2

| Field | Isi |
|---|---|
| Status | Diimplementasikan dan diverifikasi |
| Tanggal | 26 Oktober 2026 |
| Produk | Dashboard Sinyal IDX |
| Dokumen terkait | `PLAN_tanggal_custom_dan_Tx.md`, `DESIGN.md`, `REPORT.md`, `AGENTS.md` |
| Pemilik | Belum ditetapkan |

## 1. Ringkasan

Fitur tanggal acuan sudah berjalan: pembaca bisa memilih satu sesi bursa, model menghitung ulang lima horizon dari harga sampai sesi itu, dan hasilnya tidak disimpan sebagai sinyal operasional. Tiga hal belum selesai.

Pertama, pemilih tanggal menawarkan tanggal yang dijamin gagal. Untuk ADRO, `min` adalah 21 Oktober 2021, sedangkan model membutuhkan 50 sesi sehingga tanggal pertama yang bisa dihitung adalah 29 Desember 2021. Memilih `min` selalu menghasilkan 422.

Kedua, halaman historis belum menjawab pertanyaan lanjutan pembaca: apakah prediksi itu benar. Tabel menampilkan harga perkiraan dan tanggal target, tetapi tidak menampilkan harga aktual, selisih, atau status target yang belum terjadi.

Ketiga, alur tanggal belum punya pengaman regresi. Perbaikan race dan state sudah di-commit bersama implementasi ini, sedangkan tes browser masih dijalankan manual.

PRD ini menetapkan urutan pekerjaan: menutup cacat rentang tanggal, mengamankan perbaikan yang sudah ada, menambahkan tes browser, lalu membuka state URL dan scorecard realisasi. Scorecard menjadi hasil utama tahap ini karena mengubah halaman dari "apa kata model" menjadi "apakah model itu benar".

## 2. Kondisi saat ini

| Area | Kondisi |
|---|---|
| Endpoint historis | `GET /api/v1/stocks/{symbol}/signals/historical?date=YYYY-MM-DD` mengembalikan lima horizon, harga acuan, tanggal target, peringatan OOD, dan artefak model |
| Rentang data | `StockOut.earliest_reference_date` adalah batas dari data tersimpan dan cap 10 tahun, bukan batas jendela 50 sesi |
| Pemilih tanggal | `min` memakai `earliest_reference_date`, `max` memakai `last_price_date` |
| Hasil historis | Tidak menulis baris `predictions`; perhitungan dilakukan di memori |
| Perbaikan | Backend dan frontend sudah diterapkan, diuji, dan di-commit |
| Suite | 93 tes lulus pada pemeriksaan terakhir |

Bukti probe pada database lokal:

| Tanggal | Hasil |
|---|---|
| 21 Oktober 2021 | 422, baru ada 1 sesi harga, tanggal yang cukup pertama 29 Desember 2021 |
| 29 Desember 2021 | 200, lima sinyal |
| 21 Oktober 2026 | 422, melewati harga terbaru 20 Oktober 2026 |
| 4 Mei 2024 | 422, tidak ada harga penutupan, sesi sebelumnya 3 Mei 2024 |

## 3. Masalah

### 3.1 Pemilih tanggal menawarkan jalan buntu

`min` dan batas model memakai dua definisi yang berbeda. `earliest_reference_date` hanya menjawab "seberapa lama data disimpan". Endpoint historis kemudian menolak tanggal yang belum punya 50 sesi. Akibatnya, tanggal paling awal di pemilih selalu ditolak.

Dampak: pembaca melihat kontrol yang terlihat valid, memilih tanggal paling awal, lalu mendapat error. Ini bukan kasus tepi. Ini tanggal pertama yang ditawarkan.

### 3.2 Pesan error membocorkan format internal

Pesan 422 memakai `YYYY-MM-DD`, misalnya `2024-05-04`, di tengah kalimat Indonesia. Pembaca harus menerjemahkan format tanggal yang tidak muncul di mana pun pada antarmuka.

### 3.3 Tanggal yang ditolak masih tersimpan sebagai state

Saat server menolak tanggal, `state.referenceDate` masih berisi tanggal itu. Tabel sudah disembunyikan, tetapi aksi coba lagi dan refresh berikutnya masih membawa tanggal yang sama. Pembaca tidak punya jalan jelas untuk keluar dari state itu selain tombol kembali.

### 3.4 `api()` tidak menjaga respons non-JSON

`api()` memanggil `JSON.parse` pada setiap body. Jika server atau proxy mengembalikan halaman HTML dengan status 500, pembaca melihat `SyntaxError`, bukan pesan status. Ini belum terjadi pada build lokal, tetapi jalur error-nya nyata.

### 3.5 Halaman belum menunjukkan hasil prediksi

Pembaca bisa melihat prediksi pada tanggal lampau, tetapi tidak bisa melihat:

- harga penutupan aktual pada tanggal target;
- selisih antara harga perkiraan dan harga aktual;
- apakah arah sinyal tepat;
- apakah target masih di masa depan;
- apakah hasil tidak bisa dinilai karena aksi korporasi atau data harga tidak tersedia.

Tanpa bagian ini, fitur historis hanya menghitung ulang, belum mengevaluasi.

### 3.6 State tidak bisa dibagikan

Pilihan ticker, tanggal, dan horizon hilang saat halaman dimuat ulang. Dosen pembimbing atau rekan tidak bisa membuka tampilan yang sama lewat tautan.

### 3.7 Kelas bug race belum punya tes

Tiga race sudah diperbaiki secara manual: respons historis yang telat, respons harga ticker lama, dan inisialisasi kontrol yang berulang. Tidak ada tes otomatis yang akan menangkap regresi pada kelas bug ini.

## 4. Tujuan

1. Tidak ada tanggal yang ditawarkan pemilih yang dijamin menghasilkan 422 karena jendela 50 sesi.
2. Setiap baris historis menunjukkan hasil realisasi, status pending, atau alasan hasil tidak bisa dinilai.
3. Tampilan historis bisa dibuka ulang dan dibagikan lewat URL.
4. Perbaikan race dan state yang sudah ada dilindungi tes browser.
5. Jalur sinyal terbaru tidak berubah perilakunya.

## 5. Metrik keberhasilan

| Metrik | Target | Cara ukur |
|---|---|---|
| Tanggal `min` yang ditolak karena jendela 50 sesi | 0 | Tes API dan tes browser memilih `min` untuk ticker dengan data cukup |
| Baris historis dengan status hasil | 100% baris punya `realized`, `pending`, `no_price`, atau `corporate_action` | Tes unit dan pemeriksaan respons API |
| State URL valid yang bisa direproduksi | 100% kombinasi ticker, tanggal, horizon pada fixture | Tes browser memuat ulang URL |
| Skenario race yang tercakup tes browser | 4 skenario | Suite browser |
| Regresi suite Python | 0 tes gagal, tidak ada warning baru dari kode aplikasi | `python -m pytest -q` |

Metrik keterlibatan pengguna belum ditetapkan karena belum ada instrumentasi. PRD ini tidak mengarang angka penggunaan.

## 6. Non-goals

- Input nilai X bebas. Horizon tetap 1, 5, 10, 20, dan 50 sesi.
- Melatih ulang model atau mengubah artefak.
- Menyimpan hasil historis sebagai sinyal operasional.
- Menampilkan track record dari sinyal yang benar-benar tersimpan pada tanggal itu. Itu fitur terpisah yang dijelaskan di bagian 16.
- Autentikasi, akun, atau penyimpanan preferensi pengguna.
- Perubahan deployment, database, atau model bisnis.
- Redesain visual dashboard. Arah visual tetap mengikuti `DESIGN.md`.
- Dukungan tombol back dan forward browser untuk state URL. Tahap ini memakai `replaceState`.

## 7. Pengguna dan pekerjaan

| Pengguna | Pekerjaan | Setelah tahap ini |
|---|---|---|
| Investor ritel | Melihat apa kata model pada tanggal lampau dan apakah hasilnya tepat | Melihat harga aktual, selisih, dan arah yang tepat atau meleset |
| Penguji tesis | Memeriksa bukti, versi model, dan peringatan | Membuka tautan yang sama dan melihat artefak model serta status hasil |
| Operator data | Memastikan pencarian historis tidak menulis data operasional | Mendapat tes yang memastikan jumlah `predictions` tidak berubah |

## 8. Prioritas

| Urutan | Pekerjaan | Prioritas | Alasan |
|---|---|---|---|
| 0 | Commit perbaikan frontend yang sudah diverifikasi | Gate rilis | Mencegah pekerjaan baru bercampur dengan 64 baris perubahan yang belum diamankan |
| 1 | Rentang tanggal yang benar | P0 | Menghapus dead-end yang dijamin terjadi |
| 2 | Copy error, guard `api()`, rollback state tanggal | P1 | Menutup cacat kecil di alur yang sama |
| 3 | Tes browser | P1 | Mengunci perbaikan race sebelum fitur baru masuk |
| 4 | State URL | P2 | Nilai berbagi yang murah, setelah alur stabil |
| 5 | Scorecard realisasi | P2, hasil utama | Nilai produk terbesar, usaha paling besar |

## 9. Kebutuhan fungsional

### 9.1 Rentang tanggal yang bisa dipakai

FR-1. `GET /api/v1/stocks` menambahkan field `first_usable_reference_date` bertipe `date | null`.

Nilai ini adalah sesi tersimpan pertama yang memenuhi dua syarat: tidak lebih awal dari `earliest_reference_date`, dan sudah punya minimal 50 sesi harga sampai tanggal itu. Jika ticker punya kurang dari 50 sesi, nilainya `null`.

FR-2. `GET /api/v1/stocks/{symbol}/signals/historical` juga mengembalikan `first_usable_reference_date` agar klien bisa menjelaskan batas tanpa permintaan tambahan.

FR-3. Dashboard memakai `first_usable_reference_date` sebagai `min` dan `last_price_date` sebagai `max`.

FR-4. Jika `first_usable_reference_date` bernilai `null`, input tanggal dinonaktifkan dan hint menyebut jumlah sesi yang tersedia serta tindakan berikutnya.

FR-5. API tetap memakai `earliest_reference_date` sebagai batas validasi pertama. Pemanggil langsung yang memilih tanggal setelah batas itu tetapi sebelum `first_usable_reference_date` mendapat 422 dengan pesan yang menyebut tanggal pertama yang cukup. Kontrak ini tidak dihapus karena pemanggil API langsung masih membutuhkannya.

Kriteria penerimaan:

- Pada data lokal ADRO, `min` adalah 29 Desember 2021, bukan 21 Oktober 2021.
- Memilih `min` dari pemilih menghasilkan 200 dan lima baris.
- Memanggil API dengan 21 Oktober 2021 tetap menghasilkan 422 yang menyebut 29 Desember 2021.
- Ticker dengan 49 sesi memiliki `first_usable_reference_date = null` dan input nonaktif.

### 9.2 Copy error dan pemulihan state

FR-6. Pesan 422 memformat tanggal sebagai `d Mmm yyyy` dengan nama bulan Indonesia, misalnya `4 Mei 2024`, bukan `2024-05-04`.

FR-7. Saat server menolak tanggal, input tetap menyimpan nilai yang diketik agar pembaca bisa memperbaikinya, tetapi `state.referenceDate` dikosongkan. Tabel historis disembunyikan, harga acuan menjadi "Harga acuan belum tersedia", dan aksi coba lagi memuat sinyal terbaru, bukan tanggal yang ditolak.

FR-8. `api()` membaca body sebagai teks, mencoba `JSON.parse` di dalam penjagaan, dan menghasilkan pesan yang bisa dibaca saat body bukan JSON. Error membawa `status` HTTP.

FR-9. `api()` menerima `detail` berupa string atau objek. Jika objek, ia memakai `detail.message` bila ada, lalu jatuh ke pesan status.

Kriteria penerimaan:

- Respons 500 berisi HTML tidak memunculkan `SyntaxError` di konsol atau banner.
- Memilih tanggal Sabtu 4 Mei 2024 menampilkan pesan yang menyebut 3 Mei 2024 dan tidak meninggalkan state tanggal aktif.
- Tombol "Kembali ke sinyal terbaru" memulihkan tampilan tanpa memanggil endpoint historis.

### 9.3 Scorecard realisasi

FR-10. `HistoricalSignalOut` menambahkan field hasil:

| Field | Tipe | Arti |
|---|---|---|
| `actual_close` | `float \| null` | Harga penutupan aktual pada atau setelah tanggal target |
| `actual_date` | `date \| null` | Tanggal sesi yang dipakai sebagai aktual |
| `actual_return_pct` | `float \| null` | Perubahan dari harga acuan ke harga aktual |
| `actual_signal` | `str \| null` | Label yang dihasilkan aturan yang sama pada hasil aktual |
| `prediction_error_pct` | `float \| null` | `(actual_close - predicted_price) / predicted_price * 100` |
| `direction_correct` | `bool \| null` | `actual_signal == signal` |
| `outcome_status` | `str` | `realized`, `pending`, `no_price`, atau `corporate_action` |
| `outcome_approximate` | `bool` | `true` saat harga aktual diambil dari sesi setelah tanggal target |

FR-11. Status hasil ditentukan dengan urutan berikut:

1. Jika `target_date` lebih besar dari `last_price_date`, status `pending`.
2. Jika ada baris harga tepat pada `target_date`, status `realized` dengan `outcome_approximate = false`.
3. Jika tidak ada baris tepat, cari sesi tersimpan pertama setelah `target_date` dalam 7 hari kalender. Jika ada, status `realized` dengan `outcome_approximate = true`. Jika tidak ada, status `no_price`.
4. Setelah harga aktual ditemukan, cek aksi korporasi di antara tanggal acuan dan tanggal aktual. Jika ada, ganti status menjadi `corporate_action`. Baris ini tidak dihitung sebagai tepat atau meleset.

FR-12. `actual_signal` dihitung dengan `classify_return(actual_close, reference_close, horizon)`, aturan yang sama dengan sinyal. HOLD dianggap tepat hanya jika return aktual berada di dalam ambang horizon.

FR-13. `HistoricalSignalsOut` menambahkan ringkasan `scorecard`:

| Field | Tipe | Arti |
|---|---|---|
| `realized` | `int` | Jumlah baris berstatus `realized` |
| `pending` | `int` | Jumlah baris berstatus `pending` |
| `no_price` | `int` | Jumlah baris berstatus `no_price` |
| `corporate_action` | `int` | Jumlah baris berstatus `corporate_action` |
| `direction_correct` | `int` | Jumlah baris realized dengan arah tepat |
| `direction_total` | `int` | Jumlah baris realized yang bisa dinilai arahnya |
| `mean_abs_error_pct` | `float \| null` | Rata-rata nilai absolut `prediction_error_pct` pada baris realized |

FR-14. Tabel historis menambahkan kolom `Aktual`, `Selisih`, dan `Arah`.

- `Aktual` menampilkan harga dan tanggal. Jika `outcome_approximate`, tambahkan catatan "sesi terdekat".
- `Selisih` menampilkan persentase bertanda. Warna netral, bukan hijau atau merah, karena selisih bukan sinyal beli atau jual.
- `Arah` menampilkan `tepat`, `meleset`, `belum terjadi`, `tidak ada harga`, atau `aksi korporasi`.
- Baris `pending` menampilkan tanggal target dan teks "Belum terjadi".
- Baris `no_price` menampilkan "Harga target belum tersedia".
- Baris `corporate_action` menampilkan "Aksi korporasi di jendela target. Hasil tidak dinilai."

FR-15. Di atas tabel, ringkasan hanya muncul jika ada baris realized. Formatnya: `{realized} dari {total} horizon sudah terealisasi. Arah tepat {correct} dari {graded}. Rata-rata selisih absolut {mean}%.`

FR-16. Halaman menampilkan catatan: "Dihitung ulang dengan model yang aktif sekarang, bukan sinyal yang tersimpan pada tanggal itu." Catatan ini wajib ada di samping ringkasan, bukan di footer.

FR-17. Pencarian historis tetap tidak menulis baris `predictions`, termasuk saat scorecard dihitung.

FR-18. Harga setelah tanggal target hanya dipakai untuk menilai hasil, tidak pernah masuk ke jendela input model. Tes harus membuktikan bahwa mengubah harga setelah tanggal target tidak mengubah `predicted_price`.

Kriteria penerimaan:

- Fixture dengan target yang sudah lewat menampilkan `realized`, harga aktual, selisih, dan arah.
- Fixture dengan target di masa depan menampilkan `pending` dan tidak menghitung arah.
- Fixture tanpa baris harga target menampilkan `no_price`.
- Fixture dengan aksi korporasi menampilkan `corporate_action` dan tidak masuk `direction_total`.
- Jumlah baris `predictions` sebelum dan sesudah lookup sama.

### 9.4 State URL

FR-19. URL menyimpan `symbol`, `date`, dan `horizon`, misalnya `/?symbol=ADRO&date=2024-05-03&horizon=5`.

FR-20. Saat boot, dashboard membaca ketiga parameter. Symbol divalidasi terhadap daftar saham. Tanggal divalidasi terhadap `first_usable_reference_date` dan `last_price_date`. Horizon divalidasi terhadap `HORIZONS`.

FR-21. Parameter tanggal yang tidak valid dibuang, tampilan jatuh ke sinyal terbaru, dan pesan menjelaskan bahwa tanggal di tautan tidak bisa dipakai. Dashboard tidak mengirim permintaan historis untuk tanggal yang tidak valid.

FR-22. Perubahan pengguna memperbarui URL dengan `history.replaceState`. Tombol back dan forward tidak menjadi bagian tahap ini.

FR-23. Memuat ulang URL yang valid menghasilkan tampilan yang sama: ticker, tanggal acuan, horizon riwayat, dan tabel sinyal.

Kriteria penerimaan:

- `?symbol=TLKM&date=2024-05-03&horizon=5` setelah reload menampilkan TLKM, tanggal 3 Mei 2024, dan riwayat T+5.
- `?symbol=TLKM&date=2019-01-02` tidak memanggil endpoint historis dan menampilkan pesan.
- `?symbol=XXXX` jatuh ke ticker pertama tanpa error.
- `?horizon=7` jatuh ke T+1.

### 9.5 Tes browser

FR-24. Tambahkan suite browser memakai Playwright. Pilihan pertama adalah `pytest-playwright` agar tetap satu runner dengan suite Python. Jika CI tidak bisa memasang Chromium, suite boleh berupa skrip Node dengan dokumentasi instalasi, tetapi keputusan itu harus dicatat.

FR-25. Skenario minimum:

| Skenario | Yang dibuktikan |
|---|---|
| Tanggal 2 Januari 2019 | Pesan error, tabel tersembunyi, tombol kembali memulihkan |
| Respons historis ditahan lalu tanggal diganti | Respons lama tidak pernah merender tabel |
| Respons harga ADRO ditahan lalu pindah ke TLKM | Grafik dan caption tetap milik TLKM |
| Tanggal Sabtu 4 Mei 2024 | 422, harga acuan "belum tersedia", tidak ada state tanggal aktif |
| `boot()` dipanggil dua kali | Opsi horizon tetap lima dan listener tidak berlipat |
| URL valid dimuat ulang | Ticker, tanggal, dan horizon sama |

FR-26. Tes berjalan terhadap server uvicorn dengan SQLite sementara dan fixture harga. Tidak ada panggilan jaringan ke provider.

FR-27. Tes menunggu state yang terlihat, bukan `sleep` dengan durasi tetap.

## 10. Perubahan API

| Endpoint | Perubahan | Kompatibilitas |
|---|---|---|
| `GET /api/v1/stocks` | Tambah `first_usable_reference_date` | Aditif, klien lama mengabaikan |
| `GET /api/v1/stocks/{symbol}/signals/historical` | Tambah `first_usable_reference_date`, field hasil per horizon, dan `scorecard` | Aditif |
| `GET /api/v1/stocks/{symbol}/signals` | Tidak berubah | Tidak ada |
| `GET /api/v1/predictions/{symbol}` | Tidak berubah | Tidak ada |

Field `earliest_reference_date` tetap ada dengan arti lama: batas data tersimpan dan cap 10 tahun. `first_usable_reference_date` adalah batas yang lebih ketat dan menjadi sumber kebijakan pemilih tanggal.

Error historis tetap memakai 422 dengan `detail` berupa string. Perubahan ke `detail` terstruktur tidak termasuk tahap ini.

## 11. Aturan perhitungan

`first_usable_reference_date` dihitung sebagai sesi tersimpan pertama yang memenuhi:

```
floor = max(reference_bounds(first_price_date, last_price_date)[0],
            nth_price_date(session, symbol, max(HORIZONS)))
first_usable = sesi tersimpan pertama pada atau setelah floor
```

Jika `nth_price_date` bernilai `None`, hasilnya `None`. Jika `floor` melewati `last_price_date`, hasilnya `None`.

Scorecard memakai data yang sudah ada:

- Harga acuan: `reference_close` dari respons historis.
- Harga aktual: penutupan pada `target_date`, atau sesi berikutnya dalam 7 hari.
- Return aktual: `(actual_close - reference_close) / reference_close * 100`.
- Arah aktual: `classify_return(actual_close, reference_close, horizon)`.
- Selisih harga: `(actual_close - predicted_price) / predicted_price * 100`. Nilai positif berarti harga aktual di atas perkiraan.
- Rata-rata selisih absolut hanya dari baris `realized`, bukan dari `pending`, `no_price`, atau `corporate_action`.

Tidak ada perhitungan baru yang menggandakan rumus sinyal. Klasifikasi tetap di `signals.py`, tanggal target tetap di `trading_calendar.py`.

## 12. Perubahan UI

### 12.1 Pemilih tanggal

Hint memakai batas yang bisa dipakai, bukan batas data mentah. Contoh untuk ADRO:

> Model memakai 50 sesi terakhir. Tanggal paling awal yang bisa dihitung: 29 Des 2021. Data tersedia sampai 20 Okt 2026.

Jika data kurang dari 50 sesi:

> `{symbol}` baru punya `{n}` sesi harga. Model membutuhkan 50 sesi. Perbarui harga untuk mengisi rentang tanggal.

Jika belum ada harga sama sekali:

> Belum ada harga tersimpan untuk `{symbol}`. Perbarui harga untuk mengisi rentang tanggal.

### 12.2 Tabel historis

Kolom baru ditempatkan setelah `Harga perkiraan` dan sebelum `Perkiraan tanggal`:

| Kolom | Isi |
|---|---|
| Aktual | Harga penutupan dan tanggal, atau status |
| Selisih | Persentase bertanda, netral |
| Arah | `tepat`, `meleset`, atau status |

Di layar sempit, kolom mengikuti pola `data-label` yang sudah ada. Tidak ada tabel baru dan tidak ada kartu baru.

### 12.3 Copy status

| State | Copy |
|---|---|
| Pending | `Belum terjadi. Target {tanggal target}.` |
| No price | `Harga target belum tersedia.` |
| Corporate action | `Aksi korporasi di jendela target. Hasil tidak dinilai.` |
| Approximate | `Sesi terdekat: {tanggal aktual}.` |
| Summary | `{realized} dari {total} horizon sudah terealisasi. Arah tepat {correct} dari {graded}.` |
| Disclaimer | `Dihitung ulang dengan model yang aktif sekarang, bukan sinyal yang tersimpan pada tanggal itu.` |
| URL invalid | `Tanggal di tautan tidak bisa dipakai. Menampilkan sinyal terbaru.` |

Tidak ada emoji, tidak ada spinner tanpa label, dan tidak ada warna hijau atau merah untuk akurasi. Warna sinyal tetap hanya untuk chip BUY, HOLD, dan SELL.

## 13. Rencana tes

| Lapisan | Kasus | Alat |
|---|---|---|
| Unit | `first_usable_reference_date` untuk 50 sesi, 49 sesi, dan cap 10 tahun | pytest |
| Unit | Status hasil realized, pending, no_price, approximate, corporate_action | pytest |
| Unit | Arah tepat dan meleset memakai aturan `classify_return` | pytest |
| Unit | Format tanggal Indonesia pada pesan error | pytest |
| API | Field baru pada `/stocks` dan endpoint historis | pytest + TestClient |
| API | Lookup historis tidak menambah `predictions` | pytest |
| API | Mengubah harga setelah target tidak mengubah prediksi | pytest |
| Browser | Enam skenario di FR-25 | Playwright |
| Regresi | Jalur sinyal terbaru tidak berubah | pytest yang sudah ada |
| Manual | Keyboard, fokus, dark mode, dan lebar 375 px pada kolom baru | Pemeriksaan rilis |

Kriteria rilis:

- `python -m pytest -q` lulus tanpa kegagalan baru.
- Suite browser lulus di mesin lokal dan CI.
- Memilih `min` pada ticker dengan data cukup tidak menghasilkan 422.
- URL valid bertahan setelah reload.
- Tidak ada error konsol pada alur yang diuji.
- Jumlah baris `predictions` tidak berubah setelah lookup historis.

## 14. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Hasil backtest dibaca sebagai track record | Pembaca mengira model lama menghasilkan sinyal itu | Tampilkan disclaimer, artefak model, dan versi model di setiap baris |
| Aksi korporasi mendistorsi selisih harga | Arah dan selisih terlihat salah | Tandai `corporate_action` dan keluarkan dari `direction_total` |
| Kalender libur belum mencakup tahun target | Tanggal aktual bergeser | Tandai `outcome_approximate` dan tampilkan tanggal aktual |
| Model aktif berubah | Hasil historis berubah antar waktu | Tampilkan `model_artifact` dan `model_version_id`; jelaskan bahwa perhitungan memakai model aktif |
| Query 50 sesi per ticker di `/stocks` menambah beban | Waktu muat daftar saham naik | Satu query window untuk semua ticker bila memungkinkan; ukur sebelum merilis |
| Tes browser flaky | Suite tidak dipercaya | Fixture SQLite, tanpa jaringan, tunggu state yang terlihat |
| Perubahan lokal tercampur pekerjaan baru | Perbaikan yang sudah terbukti hilang atau sulit ditinjau | Commit gate sebelum pekerjaan tahap 2 dimulai |

## 15. Rollout dan gate

1. Commit perbaikan frontend yang sudah diverifikasi. Jalankan `python -m pytest -q` dan `node --check idx_signal/static/app.js` sebelum commit. Stage hanya `app.js` dan `index.html`.
2. Rilis rentang tanggal dan copy error. Tidak ada migrasi database.
3. Rilis guard `api()`, rollback state tanggal, dan tes browser.
4. Rilis state URL.
5. Rilis scorecard. Field baru bersifat aditif; tidak ada perubahan pada jalur refresh atau tabel `predictions`.

Tidak ada feature flag. Endpoint historis adalah satu-satunya konsumen scorecard, dan field baru tidak mengubah perilaku klien lama. Rollback cukup dengan mengembalikan deploy sebelumnya karena tidak ada data baru yang ditulis.

## 16. Pertanyaan terbuka

1. Nama field `first_usable_reference_date` cukup panjang. Alternatifnya `earliest_signal_date`. Saya memilih yang pertama karena menyebut "usable" dan tidak menyiratkan sinyal tersimpan. Perlu keputusan sebelum implementasi.
2. Scorecard tahap ini menilai model aktif pada data historis, bukan sinyal yang tersimpan saat itu. Apakah label "backtest model aktif" cukup, atau kita perlu menunda sampai track record sinyal tersimpan siap?
3. Aksi korporasi: keluarkan dari akurasi, atau tampilkan sebagai baris terpisah dengan peringatan? Rekomendasi saya keluarkan dari `direction_total` dan tetap tampilkan harganya.
4. Playwright Python menambah dependensi Chromium di CI. Apakah itu diterima, atau tes browser dijalankan sebagai skrip lokal dulu?
5. State URL memakai `replaceState` tanpa dukungan back button. Apakah berbagi tautan saja cukup untuk tahap ini?

## 17. Lampiran: bukti dan batasan

- Suite Python terakhir: 99 lulus, 541 warning dari Keras dan Starlette, 25,83 detik.
- Pemeriksaan sintaks `node --check idx_signal/static/app.js` lulus.
- UI diuji di browser pada server lokal: tanggal valid 3 Mei 2024, tanggal di luar rentang, Sabtu 4 Mei 2024, respons historis tertunda, perpindahan ticker, dan `boot()` ganda.
- Database lokal hanya berisi harga ADRO dan TLKM. Delapan ticker lain menampilkan state kosong dan pemilih tanggal nonaktif. Ini kondisi data, bukan cacat UI.
- Belum ada tes browser otomatis di repo. Verifikasi UI dilakukan manual di browser pada implementasi ini.
- Perubahan sudah di-commit dan didorong ke GitHub. PRD ini tidak mengubah kode.
