# Laporan Proyek: Asisten Cerdas Berbasis Graph Retrieval-Augmented Generation (GraphRAG) untuk Manajemen Arsip Organisasi

**Kelompok 5**

**Disusun Oleh:**
- Timotius Willy Narendra (H1D025052)
- Adridinan Najmi Faza (H1D025059)
- Fardizza Finda Rahman (H1D025067)
- Kautsar Rifqi Aditya (H1D025084)
- Haiban Nur Irvanof (H1D025085)

---

## 1. Pendahuluan

Setiap pergantian kepengurusan di lingkungan organisasi mahasiswa atau kampus, sering kali terjadi fenomena hilangnya “memori institusi” (*institutional memory*). Dokumen-dokumen kesejarahan dan operasional penting—seperti notula rapat, Standar Operasional Prosedur (SOP), Laporan Pertanggungjawaban (LPJ), hingga proposal program kerja—sering kali tercecer di berbagai platform penyimpanan terpisah.

Dampak utama dari masalah ini adalah pengurus yang baru menjabat kesulitan mencari data historis secara spesifik ketika dibutuhkan. Metode pencarian kata kunci tradisional (*keyword search*) yang biasa digunakan tidak mampu menangkap konteks kalimat dan sering kali gagal menjawab pertanyaan yang kompleks. Ketiadaan sistem pengarsipan cerdas yang mampu menjawab pertanyaan analitis secara instan membuat proses regenerasi organisasi menjadi tidak efisien. Mempertahankan *institutional memory* dan menghindari data “silo” merupakan tantangan krusial yang saat ini banyak dipecahkan melalui teknologi *Large Language Models* (LLM) dan graf pengetahuan (Sun et al., 2024; Shirzad et al., 2024). Namun, mengingat RAG berbasis vektor sering berhalusinasi saat dihadapkan pada penalaran lintas dokumen (Edge et al., 2024), proyek ini mengusulkan pengembangan Asisten Cerdas berbasis *Graph Retrieval-Augmented Generation* (GraphRAG) untuk mengatasi masalah manajemen arsip di tingkat organisasi.

## 2. Related Work

### 2.1. Retrieval-Augmented Generation (RAG) Tradisional vs. GraphRAG

Dalam lima tahun terakhir, adopsi *Large Language Models* (LLM) untuk tugas pencarian informasi sangat didorong oleh arsitektur *Retrieval-Augmented Generation* (RAG) (Gao et al., 2023; Wang et al., 2023). RAG tradisional mengandalkan pencarian kemiripan vektor (vektor semantik) untuk mengambil teks yang relevan. Namun, penelitian terbaru menunjukkan bahwa RAG berbasis vektor sering gagal dalam menjawab pertanyaan multi-lompatan (*multi-hop reasoning*) dan memahami relasi antar entitas yang terdistribusi di banyak dokumen (Edge et al., 2024; Zhao et al., 2024). Untuk mengatasi kelemahan ini, *Graph Retrieval-Augmented Generation* (GraphRAG) diperkenalkan dengan mengintegrasikan *Knowledge Graph* (KG) ke dalam sistem RAG. Pendekatan ini terbukti secara signifikan meningkatkan pemahaman teks berbasis graf dan penalaran dokumen yang kompleks dengan mempertahankan hierarki struktur informasi (He et al., 2024; Pan et al., 2024; Li et al., 2024; Agrawal et al., 2024).

### 2.2. Manajemen Arsip dan Institutional Memory

Masalah kehilangan memori institusi (*institutional memory loss*) pada sistem informasi telah menjadi subjek penelitian intensif, khususnya dalam manajemen pengetahuan organisasi. Arsitektur hibrida yang menggabungkan basis data vektor dengan graf terbukti mampu mencegah informasi agar tidak terisolasi (Shirzad et al., 2024; Sun et al., 2024; Baek et al., 2023). Pendekatan *Knowledge Graph-Augmented Language Models* telah diadopsi untuk menavigasi arsip internal yang kaya akan data relasional sehingga menghasilkan jawaban yang lebih faktual dan menekan risiko halusinasi (Kang et al., 2023; Luo et al., 2023; Yasunaga et al., 2022).

### 2.3. Pendekatan Hybrid Search dan Penelusuran Dokumen

Selain integrasi graf, metode pencarian ganda (*Hybrid Search*) yang menggabungkan pencarian semantik lokal dan pencarian global lintas dokumen mulai diimplementasikan (Trivedi et al., 2022). Kerangka kerja terbaru mengeksplorasi cara-cara efisien bagi LLM untuk memilah entitas graf secara deterministik namun tetap mempertahankan kemampuan bahasa natural (Hu et al., 2023; Wen et al., 2023; Zhang et al., 2024). Hal ini sejalan dengan tujuan pengembangan asisten cerdas untuk arsip, di mana presisi dan kemampuan menelusuri sejarah keputusan sangat krusial (Jiang et al., 2023; Asai et al., 2023).

## 3. Metode Penelitian

Penelitian dan pengembangan proyek ini dirancang dengan pendekatan *Graph Retrieval-Augmented Generation* (GraphRAG) yang dipadukan dengan *Hybrid Search*. Rencana metode dibagi menjadi beberapa tahapan utama:

### A. Persiapan Dataset

Dataset difokuskan pada arsip-arsip internal organisasi kampus dengan perlakuan pra-pemrosesan (anonimisasi informasi sensitif / PII).
- **Jenis Data**: LPJ, Proposal Program Kerja, Notula Rapat, serta dokumen SOP divisi.
- **Format**: Teks tidak terstruktur berupa PDF, Markdown, atau teks polos.
- **Karakteristik**: Data kaya akan informasi kronologis, daftar panitia, anggaran historis, dan justifikasi keputusan strategis.

### B. Data Ingestion & Indexing Pipeline

- **Parsing & Chunking**: Dokumen mentah diekstraksi menjadi teks, lalu dipecah menggunakan *semantic chunking* agar batasan potongan teks didasarkan pada makna paragraf.
- **Vector & Graph Construction**: Setiap teks dikonversi menjadi representasi matematis (*vector embeddings*) dan disimpan dalam *Vector Database* (menggunakan PostgreSQL dengan pgvector). Bersamaan dengan itu, LLM digunakan untuk mengekstrak entitas dan relasi untuk membangun *Knowledge Graph* (dengan *engine* SQLite dan pustaka NetworkX).

### C. Proses Pencarian (Retrieval Phase)

Menggunakan *Hybrid Search* ketika memproses pertanyaan dari pengguna:
- **Vector Search**: Mengukur jarak kemiripan kosinin/semantik antara kueri dengan dokumen di *vector database*.
- **Graph Retrieval**: Menelusuri *Knowledge Graph* untuk menghubungkan informasi yang secara teks berjauhan namun secara logika sangat berkaitan.
- **Re-ranking**: Menggabungkan hasil Vektor dan Graf, menghilangkan duplikat, lalu diurutkan ulang (*re-ranking*) berdasarkan tingkat relevansi tertinggi.

### D. Pembuatan Jawaban (Generation & Source Citation)

Dokumen yang berhasil diambil dirangkai ke dalam *prompt template* lalu dikirim ke mesin LLM (misal: Ollama / Groq). Algoritma diinstruksikan dengan *guardrails* agar mematuhi konteks dan wajib menyertakan sitasi yang merujuk ke dokumen sumber.

### E. Evaluasi Kinerja (Evaluation Framework)

Akurasi arsitektur algoritma diukur secara kuantitatif otomatis menggunakan kerangka Ragas (*Retrieval Augmented Generation Assessment*) dengan fokus pada dua metrik:
- **Faithfulness**: Memastikan klaim dalam jawaban logis dan dideduksi dari dokumen sumber.
- **Answer Relevancy**: Memastikan jawaban presisi, singkat, dan relevan dengan pertanyaan pengguna.

## 4. Hasil dan Diskusi

*(Bagian ini masih dalam proses pengerjaan, karena proyek sedang berada pada tahap perancangan metodologi. Hasil ekstraksi graf, performa pencarian hybrid, serta hasil evaluasi akurasi RAGAS akan dilaporkan setelah tahap implementasi selesai).*

## 5. Kesimpulan

*(Kesimpulan akhir terkait efektivitas GraphRAG dalam menekan hilangnya “institutional memory” pada arsip organisasi kampus akan disimpulkan setelah pengujian pada tahap Hasil dan Diskusi rampung dilakukan).*

## 6. Daftar Pustaka

1. Agrawal, G., et al. (2024). [GraphRAG: A Systematic Literature Review](https://scholar.google.com/scholar?q=Agrawal%20GraphRAG%20A%20Systematic%20Literature%20Review).
2. Asai, A., et al. (2023). [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511).
3. Baek, J., et al. (2023). [Knowledge-Augmented Language Model and its Application to Unsupervised Named-Entity Recognition](https://arxiv.org/abs/1904.04458).
4. Edge, D., et al. (2024). [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130).
5. Gao, Y., et al. (2023). [Retrieval-Augmented Generation for Large Language Models: A Survey](https://arxiv.org/abs/2312.10997).
6. He, J., et al. (2024). [G-Retriever: Retrieval-Augmented Generation for Textual Graph Understanding and Question Answering](https://arxiv.org/abs/2402.07630).
7. Hu, Y., et al. (2023). [ChatKBQA: A Generate-then-Retrieve Framework for Knowledge Base Question Answering with LLMs](https://arxiv.org/abs/2310.08975).
8. Jiang, J., et al. (2023). [Active Retrieval Augmented Generation](https://arxiv.org/abs/2305.06983).
9. Kang, M., et al. (2023). [Knowledge Graph-Augmented Language Models for Complex Question Answering](https://aclanthology.org/2023.nlrse-1.1).
10. Li, Y., et al. (2024). [A Survey of Graph Meets Large Language Model: Progress and Future Directions](https://arxiv.org/abs/2311.12399).
11. Luo, L., et al. (2023). [Reasoning on Graphs: Faithful and Interpretable Large Language Model Reasoning](https://arxiv.org/abs/2310.01061).
12. Pan, S., et al. (2024). [Unifying Large Language Models and Knowledge Graphs: A Roadmap](https://arxiv.org/abs/2306.08302).
13. Shirzad, A., et al. (2024). [GraphRAG: Unlocking LLM Discovery on Narrative Private Data](https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/).
14. Sun, K., et al. (2024). [Head-to-Tail: How Knowledgeable are Large Language Models (LLM)? A.K.A. Will LLMs Replace Knowledge Graphs?](https://arxiv.org/abs/2308.10168).
15. Trivedi, H., et al. (2022). [Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions](https://arxiv.org/abs/2212.10509).
16. Wang, Y., et al. (2023). [A Survey on Retrieval-Augmented Text Generation](https://arxiv.org/abs/2202.01110).
17. Wen, J., et al. (2023). [MindMap: Knowledge Graph Prompting Sparks Graph of Thoughts in Large Language Models](https://arxiv.org/abs/2308.09729).
18. Yasunaga, M., et al. (2022). [Deep Bidirectional Language-Knowledge Graph Pretraining](https://arxiv.org/abs/2210.09338).
19. Zhang, R., et al. (2024). [Graph-ToolFormer: To Empower LLMs with Graph Reasoning Ability via Tool Use](https://arxiv.org/abs/2304.11116).
20. Zhao, W., et al. (2024). [Graph Retrieval-Augmented Generation: A Survey](https://arxiv.org/abs/2408.08921).
