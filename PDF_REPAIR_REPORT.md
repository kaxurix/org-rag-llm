# Perbaikan PDF notulen S-TECH 2026

Berkas PDF dalam folder proyek diperbaiki pada 19 Oktober 2026 agar setiap berkas hanya memuat rapat sesuai nomornya. Isi pembahasan, nama, nominal, tanggal, dan keputusan pada rapat yang dipertahankan tidak disunting.

| Berkas | Sebelum | Sesudah | Perubahan |
| --- | ---: | ---: | --- |
| [NOTULA RABES STECH 2026 1.pdf](NOTULA%20RABES%20STECH%202026%201.pdf) | 37 halaman | 16 halaman | Mempertahankan rapat 1, menghapus tambahan rapat 2 dan 3. |
| [NOTULA RABES STECH 2026 2.pdf](NOTULA%20RABES%20STECH%202026%202.pdf) | 22 halaman | 12 halaman | Mempertahankan rapat 2, menghapus tambahan rapat 3. |
| [NOTULA RABES STECH 2026 3.pdf](NOTULA%20RABES%20STECH%202026%203.pdf) | 10 halaman | 10 halaman | Sudah benar; identik dengan berkas semula. |
| [NOTULA RABES STECH 2026 4.pdf](NOTULA%20RABES%20STECH%202026%204.pdf) | 19 halaman | 19 halaman | Sudah benar; identik dengan berkas semula. |

Batas antarrapat ada di tengah halaman 16 PDF 1 dan halaman 12 PDF 2. Karena itu, halaman terakhir tetap disertakan dan hanya bagian rapat berikutnya yang dihapus. Penutup `sekian, wassalam` pada PDF 1 dan persetujuan SOP pada PDF 2 tetap ada. Redaksi menghapus teks rapat berikutnya dari hasil ekstraksi PDF, bukan hanya menutupnya secara visual.

Verifikasi otomatis membandingkan seluruh teks halaman yang dipertahankan, teks penutup pada halaman batas, dan render bagian yang dipertahankan. Render PDF 2 identik; PDF 1 memiliki perbedaan kecil antialiasing font, rata-rata 0,345 dari skala kanal 0–255. Tampilan bagian penutup juga diperiksa secara visual. SHA-256 PDF 3 dan 4 tetap sama.

Salinan asli keempat PDF, snapshot database sebelum perbaikan, dan manifest SHA-256 tersimpan di:

`data/backups/pdf-originals-20261019-060101-364244/`

Manifest: [manifest.json](data/backups/pdf-originals-20261019-060101-364244/manifest.json).

Database aktif sudah disinkronkan dengan PDF baru dengan mempertahankan ID dokumen. Versi PDF lama tidak lagi menjadi sumber aktif. Arsip sekarang berisi **4 PDF, 57 halaman, 131 potongan teks**. Tautan `/documents/{id}/pdf` menyajikan PDF yang sudah diperbaiki.
