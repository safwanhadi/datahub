# Spesifikasi data Profil Maternal & Perinatal

Status: rancangan integrasi v1.0 yang sudah didukung modul internal DataHub.
Definisi klinis, daftar kode diagnosis, dan sumber tabel harus disahkan bersama
obgyn, dokter anak, rekam medis, dan tim mutu sebelum penggunaan operasional.
Dokumen ini tidak menyatakan endpoint SIMRS sudah tersedia.

## Berkas untuk tim SIMRS

- [Contoh respons lengkap](maternal-perinatal.example.json): angka ilustratif, bukan data RS.
- [JSON Schema](maternal-perinatal.schema.json): validasi bentuk dan tipe respons.
  Validasi jumlah, periode permintaan, dan duplikasi diagnosis juga dijalankan DataHub.
- [Lembar pemetaan sumber](maternal-perinatal-mapping.csv): isi tabel, kolom, relasi,
  aturan seleksi, serta penanggung jawab. Nama tabel tidak diasumsikan.
- [Pencarian metadata MySQL/MariaDB](SIMRS_MATERNAL_DISCOVERY.sql): petunjuk
  menemukan kandidat tabel/kolom dan relasi, tanpa membaca baris pasien.
  Belum dijalankan ke database SIMRS; bila menggunakan DBMS lain perlu disesuaikan.
- Modul DataHub: **Profil Maternal & Perinatal**, terpisah dari API eksternal.

## Endpoint dan konfigurasi

Usulan: `GET /api/maternal-perinatal/?tgl_awal=2026-10-01&tgl_akhir=2026-10-31`.
Gunakan autentikasi Bearer SIMADU seperti endpoint SIMRS lainnya.
Di menu **API SIMRS**, daftarkan kode `maternal-perinatal` dengan URL sebenarnya.
Tidak ada URL bawaan atau akses langsung DataHub ke database SIMRS.

Penerapan DataHub: jalankan `python manage.py migrate` menggunakan virtual
environment server (migrasi 0030), daftarkan endpoint, lalu ambil data bulanan
melalui menu profil. Pemeriksa membuka **Periksa / verifikasi**, membandingkan
snapshot dengan register, mengisi catatan, lalu memilih **Setujui profil internal**.
Koreksi angka bisa disimpan sebagai draf. Jika kode/diagnosis harus ditambah atau
diperbaiki, tim SIMRS memperbaiki agregat sumber, petugas menarik ulang, kemudian
pemeriksa memilih **Muat snapshot terbaru sebagai draf**. Pengambilan dan
persetujuan tidak otomatis terjadi hanya dengan memasang migrasi.

DataHub mengambil **satu bulan kalender penuh**. Filter triwulan, semester,
dan tahunan menjumlahkan bulan yang telah disetujui; jangan memasukkan respons
tahunan bersama bulanan. `period.start/end` harus sama dengan permintaan.
Tanggal menggunakan waktu lokal rumah sakit, batas awal inklusif dan akhir
eksklusif pukul 00:00 hari setelah `tgl_akhir`. Untuk bulan berjalan, hanya
kejadian sampai waktu ekstraksi yang tersedia; tarik ulang setelah penutupan
bulan. Respons tetap berlabel bulan permintaan dan tidak mengklaim bulan final.

## Cara menelusuri database SIMRS

1. Identifikasi nomor episode registrasi/rawat inap dan relasi ke pasien.
   Gunakan ID ini hanya di SIMRS untuk deduplikasi; jangan kirim ke DataHub.
2. Telusuri modul kebidanan: kehamilan, persalinan, tanggal berakhir kehamilan,
   cara persalinan, kondisi ibu, dan pencatatan komplikasi.
3. Telusuri register kelahiran/bayi: satu baris per bayi, hubungan ke persalinan
   ibu, waktu lahir, tanda kehidupan, usia gestasi, berat lahir, dan tempat lahir.
   Jangan mengandalkan nomor rekam medis ibu sebagai ID bayi karena kembar.
4. Telusuri diagnosis keluar: kode ICD-10, penanda diagnosis utama, diagnosis
   sekunder, serta pembatalan/koreksi diagnosis. Pilih diagnosis final.
5. Telusuri kondisi keluar dan register kematian: waktu kematian, penyebab dasar,
   status konfirmasi maternal, umur bayi saat meninggal, dan tempat meninggal.
6. Telusuri asal rujukan dan riwayat transfer antarunit. Transfer ruang bukan
   episode baru; kunjungan ulang dengan registrasi baru adalah episode berbeda.
7. Isi lembar pemetaan dan rekonsiliasi hasil dengan register persalinan,
   register bayi, laporan kematian, dan sensus rawat inap.

Jangan memakai diagnosis saja untuk memastikan seorang ibu meninggal maternal.
Penetapan sebab kematian memerlukan verifikasi klinis, tidak sekadar kode keluar
"meninggal". Jangan menentukan lahir mati hanya dari tidak adanya registrasi bayi.

## Populasi, unit hitung, dan tanggal seleksi

| Kelompok | Unit | Tanggal penentu |
|---|---|---|
| Persalinan di RS | Satu ibu per kejadian persalinan | Tanggal/waktu persalinan |
| Kelahiran di RS | Satu bayi per kejadian kelahiran | Tanggal/waktu lahir |
| Kasus maternal | Episode rawat inap ibu pada masa hamil/persalinan/nifas ≤42 hari setelah akhir kehamilan, berdasarkan daftar populasi klinis yang disahkan | Tanggal keluar, hidup atau meninggal |
| Kasus neonatal | Episode rawat inap bayi yang masuk usia <28 hari, termasuk bayi lahir di RS dan rujukan; bisa keluar setelah 28 hari | Tanggal keluar |
| Kematian di RS | Satu kematian terkonfirmasi per orang | Tanggal/waktu kematian |
| Rujukan dan asal kelahiran | Episode masuk yang memenuhi populasi maternal/neonatal | Tanggal masuk |

Peringkat kasus hanya **diagnosis utama final**, maksimal satu diagnosis utama
per episode. Maternal/perinatal di sini tidak mencakup seluruh rawat jalan dan
IGD yang tidak menjadi rawat inap. Data kasus bukan jumlah pasien unik tahunan.
Kunjungan ulang dapat menghasilkan lebih dari satu episode.

Kematian bayi rujukan tetap dicatat sebagai kematian di RS, tetapi kelahirannya
tidak dimasukkan sebagai kelahiran di RS ini. Kematian di luar RS dan pasien
datang sudah meninggal tidak dimasukkan sebagai kematian yang terjadi di RS.
Tanpa tindak lanjut, modul tidak mengklaim mengetahui kematian setelah pulang.

## Kamus `metrics`

Semua kunci wajib dikirim. Nilai berupa integer ≥0 atau `null` bila sumber
belum tersedia/klasifikasi belum dapat dipastikan. **0 berarti sudah diperiksa
dan benar-benar tidak ada kejadian**. Ini pengecualian dari aturan nol pada
kontrak indikator lama. Jangan mengganti data hilang menjadi nol.

| Field | Penghitungan |
|---|---|
| `deliveries_total` | Jumlah kejadian ibu bersalin di RS; bayi kembar tetap satu persalinan |
| `deliveries_vaginal` | Persalinan pervaginam, termasuk tindakan berbantu bila disepakati |
| `deliveries_caesarean` | Persalinan seksio sesarea |
| `deliveries_other` | Cara persalinan tidak diketahui/belum terklasifikasi; jangan dihitung lagi pada dua cara lain |
| `live_births` | Bayi lahir di RS dengan tanda kehidupan, tanpa batas usia gestasi |
| `stillbirths_28w` | Bayi lahir di RS tanpa tanda kehidupan, gestasi ≥28 minggu lengkap |
| `stillbirths_22_27w` | Bayi lahir di RS tanpa tanda kehidupan, gestasi ≥22 dan <28 minggu |
| `stillbirths_unknown_ga` | Bayi tanpa tanda kehidupan dengan usia gestasi belum diketahui; tidak diasumsikan ≥28 minggu |
| `maternal_discharges` | Episode maternal keluar RS, hidup/meninggal |
| `perinatal_discharges` | Episode neonatal keluar RS, hidup/meninggal |
| `maternal_deaths` | Kematian saat hamil atau ≤42 hari setelah berakhirnya kehamilan, disebabkan/diperberat kehamilan atau penanganannya; tidak termasuk sebab kecelakaan/kebetulan; terkonfirmasi klinis |
| `pregnancy_related_deaths_unclassified` | Kematian saat hamil atau ≤42 hari setelah akhir kehamilan yang sebabnya belum selesai diklasifikasi; terpisah dari maternal terkonfirmasi dan sebab nonmaternal terkonfirmasi |
| `neonatal_deaths_early` | Lahir hidup dan meninggal di RS sebelum 7×24 jam usia (hari lengkap 0–6) |
| `neonatal_deaths_late` | Lahir hidup dan meninggal di RS pada usia ≥7×24 dan <28×24 jam (hari lengkap 7–27) |
| `newborn_deaths_age_unknown` | Kematian bayi yang dikenal sebagai pasien bayi tetapi waktu/umur lahir belum dapat dipastikan; tidak otomatis dianggap neonatal |
| `maternal_referral_admissions` | Episode masuk populasi maternal melalui rujukan; bukan jumlah instansi pengirim |
| `neonatal_inborn_admissions` | Episode masuk neonatal yang lahir di RS ini |
| `neonatal_outborn_admissions` | Episode masuk neonatal yang lahir di luar RS ini |

Jumlah tiga cara persalinan harus sama dengan `deliveries_total` bila seluruh
angka tersedia. Bayi kembar menyebabkan total bayi dapat melebihi total ibu.
Kematian neonatal dini dan lanjut saling eksklusif; lahir mati bukan kematian
neonatal. Kematian maternal terlambat (>42 hari), kematian usia ≥28 hari, dan
kematian anak lebih tua belum termasuk indikator kematian v1 ini.

## Daftar diagnosis

`maternal_diagnoses` dan `perinatal_diagnoses` adalah array objek:
`{"icd10_code":"KODE_FINAL","name":"Nama diagnosis","count":12}`.

- Kirim seluruh agregat diagnosis utama, **bukan hanya 10 besar** bulanan.
  DataHub menghitung 10 besar setelah penjumlahan periode agar peringkat tahunan
  tidak kehilangan kasus yang tidak masuk 10 besar tiap bulan.
- Satu kode hanya satu baris per daftar, maksimal 5000 baris.
- `count` integer nonnegatif; jumlah seluruh kode tidak melebihi total episode
  keluar terkait. Episode tanpa diagnosis final tetap masuk total keluar.
- `[]` berarti rincian tersedia tetapi tidak ada diagnosis; `null` berarti
  rincian belum tersedia. DataHub menandai cakupan yang belum lengkap.
- Kode dan label harus berasal dari kamus diagnosis SIMRS. Contoh JSON memakai
  kode ilustratif; daftar populasi/kode klinis jangan ditetapkan dari contoh.
- Diagnosis sekunder dan komplikasi tidak digabung ke ranking diagnosis utama.
  Pengelompokan klinis seperti perdarahan, hipertensi kehamilan, prematuritas,
  BBLR, asfiksia, dan sepsis memerlukan tabel pemetaan yang disahkan. V1 belum
  menyajikan komplikasi atau peringkat penyebab kematian sebagai diagnosis utama.

## Ketentuan teknis dan mutu

- Respons hanya memuat `schema_version`, `period`, `hospital`, `metrics`,
  `maternal_diagnoses`, `perinatal_diagnoses` seperti contoh. Field tambahan
  ditolak agar kontrak agregat tetap terkendali. Jangan kirim baris pasien,
  NIK, nomor RM, nama, alamat, nomor registrasi, atau ID ibu/bayi.
- `hospital.code/name` wajib string. Kode RS harus konsisten antarbulan.
- Jangan join tabel diagnosis, bayi, dan tindakan langsung lalu `COUNT(*)`.
  Agregasikan masing-masing pada unit kejadian/episode terlebih dahulu agar
  satu ibu dengan beberapa diagnosis/bayi/tindakan tidak terhitung berulang.
- Gunakan `COUNT(DISTINCT episode_id)` untuk episode; ID kelahiran untuk bayi;
  ID persalinan untuk ibu bersalin. Penggabungan kolom nyata ditentukan tim SIMRS.
- Audit koreksi SIMRS tidak dihapus. Pembacaan sumber oleh integrasi tidak boleh
  melakukan UPDATE/DELETE pada data layanan.
- Snapshot DataHub selalu baru setiap tarikan. Tarikan berikutnya tidak menimpa
  snapshot lama atau koreksi salinan verifikasi. Muat ulang snapshot secara
  eksplisit, periksa, lalu setujui lagi. Perubahan draf tidak tampil di profil.
- Petugas pengambil, pemeriksa, dan pemberi persetujuan memakai izin indikator
  kesehatan yang sudah ada. Semua pengguna login dapat membaca profil terverifikasi.
- Tidak ada endpoint maternal baru pada API eksternal/internal publikasi yang lama.
- V1 menampilkan jumlah, tidak menghitung AKI/AKB penduduk, rasio perinatal, atau
  memberi penilaian mutu otomatis. Populasi rujukan dan bayi lahir luar RS tidak
  boleh dicampur ke penyebut kelahiran RS tanpa definisi indikator yang disahkan.

## Uji penerimaan bersama tim klinis

1. Ibu kembar: satu persalinan, dua kelahiran; tidak menjadi dua episode maternal.
2. Tiga diagnosis sekunder: tetap satu kasus diagnosis utama.
3. Transfer ruang/IGD ke rawat inap: tidak membuat episode rawat inap baru.
4. Bayi rujukan: masuk outborn, tidak menambah `live_births` RS ini.
5. Bayi meninggal tepat usia 7 hari: neonatal lanjut, bukan dini; tepat 28 hari
   tidak masuk kematian neonatal. Gunakan umur durasi, bukan selisih tanggal saja.
6. Ibu meninggal dengan sebab belum dipastikan: kelompok belum diklasifikasi,
   tidak otomatis `maternal_deaths`. Setelah konfirmasi, rekonsiliasi ulang.
7. Sumber hilang: `null`; tanpa kejadian yang telah dipastikan: `0`.
8. Tarikan berulang: snapshot lama tetap ada; hasil disetujui tidak berubah tanpa
   tindakan pemuatan ulang/verifikasi baru. Perubahan bersamaan ditolak bila revisi usang.
9. Total per bulan cocok dengan register; penjumlahan tahunan tidak memasukkan
   snapshot ganda dan tidak menjumlahkan hasil tahunan dengan bulanan.

## Rujukan definisi

- [WHO: kematian maternal](https://www.who.int/data/gho/indicator-metadata-registry/imr-details/26).
- [WHO: kematian neonatal usia 0–27 hari](https://www.who.int/data/gho/data/indicators/indicator-details/GHO/number-of-neonatal-deaths).
- [WHO: indikator mortalitas perinatal](https://www.who.int/data/gho/indicator-metadata-registry/imr-details/perinatal-mortality-rate).

Ambang lahir mati ≥28 minggu untuk perbandingan internasional dibedakan dari
cakupan periode perinatal mulai 22 minggu; karena itu data 22–27 minggu dan
usia gestasi tak diketahui disimpan terpisah. Definisi nasional dan pelaporan RS
yang berlaku perlu dikonfirmasi tim klinis/rekam medis sebelum finalisasi.
