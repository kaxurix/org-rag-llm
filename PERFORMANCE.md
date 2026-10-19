# Verifikasi latensi dan jawaban

Pengujian lokal pada 19 Oktober 2026 melalui POST /ask, setelah model dimuat.

| Pertanyaan | Waktu klien | Mode |
| --- | ---: | --- |
| Siapa yang akan menjadi juri? | 0.068 detik | source_match |
| Jelaskan status juri pada rapat ke-4 secara singkat. | 21.182 detik | ollama |
| Apa perkembangan sponsor terbaru? | 10.324 detik | ollama |

Pertanyaan juri yang sebelumnya menunggu sekitar 90,9 detik kini mengambil pernyataan eksplisit rapat 7 Oktober, halaman 12: Pak Ihsan sudah fiks, sedangkan kehadiran Pak Irham belum pasti. Mode source_match menyatakan bahwa model tidak dipanggil; hasil ini tidak diklaim sebagai inferensi AI.

Dua pertanyaan penjelasan di atas berhasil menggunakan qwen2.5-coder:7b lewat Ollama, tanpa fallback. Layanan memakai Vulkan di RTX 4050; log pemuatan menunjukkan 29/29 layer pada GPU. Konteks 4096 token, batch 128, batas keluaran 256 token, dan keep-alive 30 menit. Pemuatan awal berjalan di latar belakang menggunakan opsi yang sama.

Batas total permintaan AI adalah 25 detik. Saat model gagal atau batas tercapai, metadata menjelaskan alasan fallback. Ini adalah hasil beberapa uji lokal, bukan jaminan latensi untuk semua pertanyaan atau semua perangkat.

Verifikasi lain: 63 pengujian otomatis lulus, 20/20 evaluasi pencarian lulus, serta browser smoke test desktop/ponsel lulus. Evaluasi pencarian memakai database sementara dari empat PDF yang sudah diperbaiki; data unggahan pengguna tetap dipertahankan.
