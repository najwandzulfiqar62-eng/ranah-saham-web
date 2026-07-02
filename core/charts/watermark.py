# =========================
# CHART WATERMARK
# =========================
# Utility untuk menambahkan watermark logo "Ranah Saham" ke semua chart
# yang dibuat bot ini.
#
# PENDEKATAN: PIL post-processing SETELAH plt.savefig(), BUKAN
# menambahkan matplotlib artist sebelum savefig seperti percobaan
# pertama. ALASAN GANTI PENDEKATAN (dicatat untuk konteks): percobaan
# pertama pakai AnnotationBbox dengan xycoords='figure fraction',
# ditambahkan ke fig.axes[0] atau fig langsung via add_artist() --
# TERNYATA tidak konsisten muncul di chart MULTI-PANEL (4 subplot
# dengan GridSpec) yang disimpan dengan bbox_inches='tight'. bbox_inches
# 'tight' menghitung ulang batas figure berdasarkan KONTEN AXES, dan
# artist figure-level yang posisinya di luar area axes manapun bisa
# ikut terpotong dari hasil akhir tergantung versi matplotlib & layout
# spesifik. PIL post-processing SEPENUHNYA MENGHINDARI masalah ini --
# bekerja di atas PIXEL FILE PNG YANG SUDAH JADI, jadi hasilnya selalu
# konsisten apapun struktur layout chart aslinya (1 panel atau 4 panel,
# GridSpec atau subplot biasa, bbox_inches apapun).

import os
from PIL import Image

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "logo_symbol_only.png")
_logo_cache = None


def _load_logo():
    """Load logo sekali saja, cache di memory sebagai PIL Image RGBA."""
    global _logo_cache
    if _logo_cache is None:
        try:
            _logo_cache = Image.open(_LOGO_PATH).convert("RGBA")
        except Exception as e:
            print(f"⚠️ Gagal load logo watermark: {e}")
            _logo_cache = False  # sentinel: sudah dicoba, gagal -- jangan coba lagi
    return _logo_cache if _logo_cache is not False else None


def apply_watermark_to_file(file_path: str, alpha: float = 0.16,
                              width_fraction: float = 0.10,
                              margin_fraction: float = 0.015) -> None:
    """Tempelkan watermark logo ke pojok kanan-bawah file PNG yang SUDAH
    TERSIMPAN di disk. Dipanggil SETELAH plt.savefig() dan plt.close(fig),
    bukan sebelumnya.

    file_path: path file PNG yang sudah disimpan chart generator.
    alpha: transparansi watermark, 0-1 (0.16 = halus, branding tapi
           tidak mengganggu pembacaan data).
    width_fraction: lebar logo sebagai fraksi dari lebar chart (0.10 =
                     10% lebar chart, otomatis menyesuaikan resolusi
                     berapapun chart-nya).
    margin_fraction: jarak logo dari tepi kanan & bawah, sebagai fraksi
                       lebar chart.

    AMAN dipanggil meski logo gagal di-load atau file_path tidak valid
    -- TIDAK raise exception, cuma print warning. Chart yang sudah
    tersimpan TETAP ADA & VALID meski watermark gagal ditempelkan
    (fail-safe: branding adalah bonus, bukan syarat chart berhasil)."""
    try:
        logo = _load_logo()
        if logo is None or not os.path.exists(file_path):
            return

        chart = Image.open(file_path).convert("RGBA")
        chart_w, chart_h = chart.size

        # Resize logo proporsional terhadap lebar chart (supaya watermark
        # selalu terlihat sebanding, baik di chart kecil maupun besar)
        logo_w = int(chart_w * width_fraction)
        logo_ratio = logo.height / logo.width
        logo_h = int(logo_w * logo_ratio)
        logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)

        # Terapkan alpha tambahan ke channel transparansi logo (logo
        # aslinya alpha=255 di area konten -- kalikan supaya jadi halus)
        r, g, b, a = logo_resized.split()
        a = a.point(lambda p: int(p * alpha))
        logo_final = Image.merge("RGBA", (r, g, b, a))

        margin_x = int(chart_w * margin_fraction)
        margin_y = int(chart_w * margin_fraction)
        pos_x = chart_w - logo_w - margin_x
        pos_y = chart_h - logo_h - margin_y

        chart.paste(logo_final, (pos_x, pos_y), logo_final)
        chart.convert("RGB").save(file_path)
    except Exception as e:
        print(f"⚠️ Gagal menambahkan watermark ke {file_path} (chart tetap dipakai apa adanya): {e}")


def apply_centered_watermark_to_file(file_path: str, alpha: float = 0.10,
                                        width_fraction: float = 0.32,
                                        center_xy: tuple = (0.5, 0.5),
                                        brand_text: str = "RANAH INVEST",
                                        brand_color: tuple = (0, 200, 120)) -> None:
    """Versi BESAR di TENGAH dari watermark -- dipakai SEMUA chart di
    bot ini (konsistensi visual, permintaan eksplisit user setelah
    awalnya cuma dipakai /ta). Logo besar transparan di tengah AREA
    KONTEN chart, PLUS strip footer terpisah berisi teks brand di
    PALING BAWAH file gambar.

    PERBAIKAN PENTING (ditemukan via testing visual): versi awal
    menempatkan teks brand di "chart_h - margin_kecil", yang BEKERJA
    untuk chart 1-panel (mis. AI Gauge) tapi MENABRAK konten data di
    chart MULTI-PANEL (mis. compare_chart dengan 2 panel -- teks jadi
    tertindih di tengah bar chart panel bawah). Solusi: EXTEND CANVAS
    ke bawah dengan strip solid baru KHUSUS untuk teks brand, supaya
    tidak pernah menabrak konten APAPUN, terlepas dari berapa banyak
    panel chart aslinya.

    file_path: path file PNG yang sudah disimpan chart generator.
    alpha: transparansi logo (0.10 -- halus, tidak mengganggu pembacaan
           data di belakangnya).
    width_fraction: lebar logo sebagai fraksi LEBAR CHART (0.32 = besar,
                     dominan tapi tidak menutup seluruh chart).
    center_xy: posisi pusat logo dalam fraksi (x, y) dari AREA KONTEN
               ASLI chart (SEBELUM strip footer ditambahkan) -- (0.5,
               0.5) = benar-benar di tengah.
    brand_text: teks yang ditempel di strip footer.
    brand_color: warna teks brand dalam RGB, default hijau.

    AMAN dipanggil meski logo/font gagal load -- fail-safe try/except,
    chart yang sudah tersimpan tetap valid meski watermark gagal."""
    try:
        logo = _load_logo()
        if logo is None or not os.path.exists(file_path):
            return

        chart = Image.open(file_path).convert("RGBA")
        chart_w, chart_h = chart.size

        # ===== Logo besar di tengah AREA KONTEN ASLI (sebelum extend) =====
        logo_w = int(chart_w * width_fraction)
        logo_ratio = logo.height / logo.width
        logo_h = int(logo_w * logo_ratio)
        logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)

        r, g, b, a = logo_resized.split()
        a = a.point(lambda p: int(p * alpha))
        logo_final = Image.merge("RGBA", (r, g, b, a))

        center_x = int(chart_w * center_xy[0])
        center_y = int(chart_h * center_xy[1])
        pos_x = center_x - logo_w // 2
        pos_y = center_y - logo_h // 2
        chart.paste(logo_final, (pos_x, pos_y), logo_final)

        # ===== Strip footer BARU (extend canvas) untuk teks brand =====
        # Cari warna background chart dari pixel pojok kiri-atas (semua
        # chart di bot ini dark theme solid, jadi pojok = warna background
        # asli) -- dipakai supaya strip baru MENYATU mulus, bukan terlihat
        # sebagai "tempelan" kotak warna lain.
        bg_color = chart.getpixel((2, 2))

        footer_h = max(int(chart_h * 0.055), 40)
        new_chart = Image.new("RGBA", (chart_w, chart_h + footer_h), bg_color)
        new_chart.paste(chart, (0, 0))

        try:
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(new_chart)
            font_size = max(int(chart_w * 0.022), 14)
            font = None
            for font_path in (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ):
                try:
                    font = ImageFont.truetype(font_path, font_size)
                    break
                except Exception:
                    continue
            if font is None:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), brand_text, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            text_x = (chart_w - text_w) // 2
            text_y = chart_h + (footer_h - text_h) // 2 - text_bbox[1]
            draw.text((text_x, text_y), brand_text, font=font,
                       fill=(*brand_color, 230))
        except Exception as e:
            print(f"⚠️ Gagal menambahkan teks brand (logo tetap ditempel): {e}")

        new_chart.convert("RGB").save(file_path)
    except Exception as e:
        print(f"⚠️ Gagal menambahkan watermark besar ke {file_path} (chart tetap dipakai apa adanya): {e}")
