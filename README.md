# Dashboard Prediksi Saham

Dashboard FastAPI untuk melihat riwayat harga IDX dan menjalankan artefak LSTM untuk horizon 1, 5, 10, 20, dan 50 hari yang tersedia di direktori penelitian. Hasil yang ditampilkan adalah keluaran model regresi harga beserta sinyal berbasis ambang, bukan probabilitas keyakinan dan bukan rekomendasi investasi.

## Pemilihan ERD dan PDM

`Prompt.md` menjadi dasar PDM karena skemanya menelusuri alur penelitian dari saham, data OHLCV, indikator, berita, sentimen, data gabungan, versi model sampai hasil prediksi. Itu membuat asal fitur dan keluaran model lebih mudah dijelaskan dalam skripsi daripada PDM `Prompt_Mermaid.md` yang berfokus pada akun, watchlist, permintaan pengguna, dan hasil prediksi generik.

Skema di aplikasi mempertahankan entitas penelitian tersebut, lalu menambahkan `prediction_requests` untuk mencatat keberhasilan atau kegagalan inferensi dan `model_versions` untuk menautkan prediksi dengan artefak yang dipakai. Tabel berita, sentimen, dan data gabungan disiapkan untuk pipeline penelitian, namun aplikasi tidak mengarang berita atau sentimen. ERD pengguna, admin, dan watchlist dari prompt Mermaid dapat ditambahkan ketika autentikasi dan pengelolaan banyak pengguna benar-benar menjadi kebutuhan.

Relasi utama PDM: `stocks` memiliki banyak `stock_prices`, `technical_indicators`, `news_articles`, `news_sentiment`, `fused_market_data`, dan `prediction_requests`; satu permintaan menghasilkan paling banyak satu `predictions`; satu `model_versions` dapat menghasilkan banyak `predictions`. Kunci unik ticker-tanggal mencegah duplikasi harga, indikator, sentimen, dan fitur gabungan.

GitHub Actions memeriksa dependensi, kompilasi Python, seluruh tes, smoke test engine ensemble sintetis, dan build Docker setiap push ke `main` serta pull request. Aplikasi berjalan sebagai layanan FastAPI dalam container. Untuk produksi, gunakan PostgreSQL terkelola; SQLite disiapkan untuk pengembangan lokal.

API ini membawa model H5 dan runtime inferensi Python, sehingga image Docker menjadi unit deployment yang sesuai. Deploy membutuhkan host container dan database PostgreSQL yang dikonfigurasi.

## Batas model yang tersedia

Artefak yang ditemukan di `CODE` mencakup model LSTM regresi harga `Target_1`, `Target_5`, `Target_10`, `Target_20`, dan `Target_50` untuk sepuluh ticker serta dataset hasil penelitian. Setiap model H5 menerima jumlah harga penutupan yang sesuai dengan horizon target sebagai satu fitur. Dataset latih yang tersedia berakhir pada 25 September 2023, sehingga performa model untuk data yang lebih baru belum tervalidasi. Skaler input dan target dibangun kembali dari dataset penelitian dengan pembagian acak `random_state=0`, mengikuti notebook asal karena artefak skaler tidak disimpan terpisah.

Kode `training_engine.py` memuat rancangan tiga jalur, tetapi tidak ditemukan artefak tersimpan untuk voter machine learning dan deep learning yang bisa dipakai oleh layanan ini. Oleh sebab itu, dashboard hanya menjalankan LSTM regresi yang tersedia. Indikator teknikal dihitung dan ditampilkan untuk konteks, tetapi tidak diklaim sebagai masukan model. Angka confidence dan sinyal ensemble tidak ditampilkan.

Engine ensemble eksperimental memakai dependensi opsional. Pasang `requirements-training.txt`, lalu jalankan `python training_engine.py` untuk smoke test dengan data sintetis; hasilnya bukan model produksi atau validasi performa investasi.

## Arah desain

Reading this as: dashboard penelitian saham untuk mahasiswa dan pembaca data pasar, dengan bahasa visual editorial yang tenang, dial ENERGY 1 / RHYTHM 2 / MOTION 1. Latar terang menjadi default untuk membaca angka dalam sesi panjang, sedangkan mode gelap tersedia sebagai pilihan. Tipografi sistem menghindari unduhan font eksternal dan angka memakai tabular figures. Komposisi memprioritaskan harga serta hasil inferensi; aksen hijau menandai data grafik, sementara warna sinyal hanya dipakai untuk makna BELI, JUAL, atau TAHAN. Jarak antarpanel memisahkan kelompok analisis, dan batas tipis mengelompokkan informasi tanpa membuatnya terlihat mengambang. Ticker, tanggal data, dan sumber harga menjadi motif identitas berulang karena keterlacakan data penting dalam penelitian. Tidak ada logo atau ilustrasi buatan.

## Menjalankan lokal

Gunakan Python 3.12 atau lebih baru dan pasang dependensi:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m uvicorn backend_api:app --reload
```

Bila memakai Neon, isi `DATABASE_URL` di `.env` dengan URL pooled untuk aplikasi. `DATABASE_URL_UNPOOLED` dapat disimpan untuk alat migrasi. Tanpa `.env`, aplikasi memakai SQLite lokal. Buka `http://127.0.0.1:8000`. Jika Yahoo Finance tidak dapat dijangkau, aplikasi mencoba cache lokal lalu dataset penelitian. UI menandai dataset penelitian sebagai historis dan bukan harga terkini.

## Endpoint

- `GET /api/v1/health`: status database dan jumlah artefak model.
- `GET /api/v1/stocks`: ticker yang memiliki artefak penelitian.
- `GET /api/v1/market-data/{symbol}?period=1y`: riwayat harga, indikator, sumber data, dan tanggal data.
- `POST /api/v1/predictions/{symbol}?horizon_days=50`: jalankan model untuk horizon 1, 5, 10, 20, atau 50 hari. Ambang sinyalnya 1,5%, 3%, 6%, 9%, dan 11%.
- `GET /api/v1/predictions/latest/{symbol}?horizon_days=50`: hasil terbaru per horizon, atau `404` bila belum ada.
- `GET /api/v1/predictions/history/{symbol}?horizon_days=50`: riwayat hasil inferensi per horizon.

## CI/CD

Workflow `.github/workflows/stock-signal.yml` menjalankan tes, smoke test engine training sintetis, dan build Docker standar maupun Vercel. Untuk deploy ke Vercel, hubungkan repository ini dengan project yang menggunakan root directory repository, lalu simpan URL pooled PostgreSQL sebagai environment variable `DATABASE_URL`. Vercel mendeteksi `Dockerfile.vercel` dan membangun container FastAPI.
