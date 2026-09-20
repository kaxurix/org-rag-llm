import fitz  # PyMuPDF

def buat_pdf_dummy():
    doc = fitz.open()
    page = doc.new_page()
    
    teks_laporan = """
PEDOMAN WAWANCARA — WARUNG JAJAN & FROZEN FOOD
Divisi: Acara / Operasional
Tahun: 2025

B. Pertanyaan Operasional Harian
1. Siapa yang menjaga warung? Menjaga warung sendirian atau berdua? 
Jawaban: Berdua dengan sistem jam kerja flexible.
2. Siapa yang bertugas menyimpan dan merekap catatan toko saat ini?
Jawaban: Tante.
3. Seberapa sering Bapak/Ibu melakukan belanja/kulakan?
Jawaban: Untuk frozen hampir setiap hari, sembako 2 minggu sekali.
4. Kendala utama operasional?
Jawaban: Salah dalam penjumlahan manual dan stok sering menumpuk waktu awal usaha.
    """.strip()
    
    # Masukkan teks ke halaman PDF
    page.insert_text((50, 50), teks_laporan, fontsize=11, fontname="Helvetica")
    
    nama_file = "Pedoman_Wawancara_Warung_Gabungan.pdf"
    doc.save(nama_file)
    doc.close()
    print(f"File {nama_file} berhasil dibuat!")

if __name__ == "__main__":
    buat_pdf_dummy()