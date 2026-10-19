# Evaluasi pencarian arsip

Hasil: **20/20 kasus lulus**.

Dataset: 4 PDF, 57 halaman, 131 chunks.

Mode: BM25, top 8. Data evaluasi diimpor ulang ke database sementara; database pengguna tidak diubah.

| Pertanyaan | Hasil | Catatan |
| --- | --- | --- |
| Siapa penanggung jawab pembicara pada rapat ke-4? | Lulus | Bukti dan filter sesuai |
| Siapa penanggung jawab medpart pada rapat ke-4? | Lulus | Bukti dan filter sesuai |
| Apa kendala divisi ATP pada rapat ke-2? | Lulus | Bukti dan filter sesuai |
| Apa vendor cocard dan lanyard pada rapat ke-2? | Lulus | Bukti dan filter sesuai |
| Apa vendor proyektor dan HT pada rapat ke-2? | Lulus | Bukti dan filter sesuai |
| Kapan rapat ke-4 dilaksanakan? | Lulus | Bukti dan filter sesuai |
| Kapan rapat ke-1 dilaksanakan? | Lulus | Bukti dan filter sesuai |
| Apa progress Sekbend pada rapat ke-4? | Lulus | Bukti dan filter sesuai |
| Berapa harga rice box konsumsi pada rapat ke-4? | Lulus | Bukti dan filter sesuai |
| Apa perkembangan sponsor terbaru? | Lulus | Bukti dan filter sesuai |
| Bandingkan perkembangan sponsorship pada semua rapat. | Lulus | Bukti dan filter sesuai |
| Apa rencana divisi Usdan pada rapat ke-4? | Lulus | Bukti dan filter sesuai |
| Siapa presiden Indonesia? | Lulus | Bukti dan filter sesuai |
| Berapa harga bitcoin hari ini? | Lulus | Bukti dan filter sesuai |
| Apa resep nasi goreng? | Lulus | Bukti dan filter sesuai |
| Apa pembahasan sponsor pada rapat ke-9? | Lulus | Bukti dan filter sesuai |
| Apa perkembangan sponsor tahun 2025? | Lulus | Bukti dan filter sesuai |
| Siapa yang akan menjadi juri? | Lulus | Bukti dan filter sesuai |
| Siapa yang menjadi juri pada rapat ke-1? | Lulus | Bukti dan filter sesuai |
| Siapa saja juri pada semua rapat? | Lulus | Bukti dan filter sesuai |

Evaluasi ini mengukur keberadaan bukti di hasil pencarian dan kepatuhan filter, bukan akurasi semua jawaban AI.
Kasus mencakup fakta, tanggal, divisi, rapat terbaru, perbandingan empat rapat, dan penolakan pertanyaan di luar arsip.
Cakupan terbatas pada kasus yang dicantumkan di eval_cases.json; tambahkan kasus baru sesuai penggunaan nyata.
