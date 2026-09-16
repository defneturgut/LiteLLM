"""
Gercek Postgres verisi (LiteLLM_SpendLogs) uzerinden mini bir metrik dashboard'u.

NEDEN VAR: "hangi model ne kadar surede cevap veriyor, mode'a gore nasil,
gecen hafta/bu ay nasil, saatlik dagilim nasil" gibi sorular icin LiteLLM'in
kendi Admin UI'sinda hazir bir grafik yok -- biz de mini_log_ui.py'nin
mantigini (server-side render, Chart.js) grafiklere tasidik.

VERI KAYNAGI: docker exec ile Postgres container'ina SQL sorgulari -- pip
kutuphanesi (psycopg2 vs.) gerekmiyor, zaten kurulu olan `docker` CLI'yi
subprocess ile cagiriyoruz. Bagimlilik yok.

NOT: Asagidaki PG_CONTAINER/PG_USER/PG_DB degerleri bu depodaki
docker-compose.yml'in "db" servisiyle eslesecek sekilde ayarli. Farkli bir
docker-compose.yml kullaniyorsan (ornegin kendi container_name/POSTGRES_USER
degerlerin varsa) bu 3 satiri kendi ortamina gore guncelle.

Bu sayfa Admin UI'nin "Metrics" sekmesine iframe olarak gomulu (bkz.
litellm-ui-fork/.../perf-stats/page.tsx). Sayfa iki ayri sekmeye bolunmus
("Model Based" / "All Models") -- ikisi ayni anda gorunmuyor, her birinin
kendi periyot secici butonlari var, birbirini etkilemiyor.

Kullanim:
    python scripts/dashboard.py
    Sonra tarayicida ac: http://localhost:8093
    Sekme + periyot: http://localhost:8093/?view=model&model_days=30&model=...
                     http://localhost:8093/?view=all&days=30
"""

import html
import json
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8093
PG_CONTAINER = "litellm-postgres"
PG_USER = "litellm"
PG_DB = "litellm"

MODE_ADLARI = {
    "acompletion": "Chat",
    "atext_completion": "Text Completion (Base Model)",
    "aimage_generation": "Image Generation",
    "aembedding": "Embedding",
}

# dataviz skill'inin dogrulanmis varsayilan kategorik paleti (ilk 4 slot:
# blue/orange/aqua/yellow) -- sabit sira renk-korlugu-guvenli (node
# scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a,#eda100" --mode light
# -> ALL CHECKS PASS). Eski seaborn "deep" paleti (mavi/turuncu/YESIL/kirmizi)
# CVD kontrolunde basarisiz oluyordu (yesil<->turuncu ayirt edilemiyor).
MODE_RENKLERI = {
    "acompletion": "#2a78d6",       # blue
    "atext_completion": "#eb6834",  # orange
    "aimage_generation": "#1baf7a", # aqua
    "aembedding": "#eda100",        # yellow
}


def psql_sorgu(sql: str) -> list[list[str]]:
    """docker exec ile psql calistirir, satirlari '|' ile ayrilmis dondurur."""
    komut = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DB,
        "-t", "-A", "-F", "|",
        "-c", sql,
    ]
    sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=15)
    if sonuc.returncode != 0:
        raise RuntimeError(f"psql hatasi: {sonuc.stderr}")
    satirlar = []
    for satir in sonuc.stdout.strip().split("\n"):
        if satir.strip():
            satirlar.append(satir.split("|"))
    return satirlar


def sql_kacir(deger: str) -> str:
    """Tek tirnagi ikiye katlayarak SQL string literaline gomulmeye hazirlar."""
    return deger.replace("'", "''")


def model_mode_ozet(days: int) -> list[dict]:
    """Model + call_type basina ortalama sure ve istek sayisi."""
    sql = f"""
    SELECT model, call_type,
           ROUND(AVG(request_duration_ms)::numeric, 1) AS ortalama_ms,
           COUNT(*) AS adet
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= NOW() - INTERVAL '{days} days'
      AND request_duration_ms IS NOT NULL AND request_duration_ms > 0
    GROUP BY model, call_type
    ORDER BY call_type, ortalama_ms DESC;
    """
    satirlar = psql_sorgu(sql)
    return [
        {"model": s[0], "call_type": s[1], "ortalama_ms": float(s[2]), "adet": int(s[3])}
        for s in satirlar
    ]


def gunluk_trend(days: int) -> list[dict]:
    """Gun basina istek sayisi + ortalama sure."""
    sql = f"""
    SELECT TO_CHAR(DATE("startTime"), 'YYYY-MM-DD') AS gun,
           COUNT(*) AS adet,
           ROUND(AVG(request_duration_ms)::numeric, 1) AS ortalama_ms
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= NOW() - INTERVAL '{days} days'
    GROUP BY DATE("startTime")
    ORDER BY gun;
    """
    satirlar = psql_sorgu(sql)
    return [
        {"gun": s[0], "adet": int(s[1]), "ortalama_ms": float(s[2]) if s[2] else 0}
        for s in satirlar
    ]


def saatlik_dagilim(days: int, model: str | None = None) -> list[dict]:
    """Gunun hangi saatinde ne kadar trafik/sure var (tum periyot toplanarak).
    `model` verilirse tek bir modele daraltir -- hem 'All Models' hem de
    'Model Based' sekmesinin saatlik grafikleri bunu paylasir."""
    model_filtresi = f"AND model = '{sql_kacir(model)}'" if model else ""
    sql = f"""
    SELECT EXTRACT(HOUR FROM "startTime")::int AS saat,
           COUNT(*) AS adet,
           ROUND(AVG(request_duration_ms)::numeric, 1) AS ortalama_ms
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= NOW() - INTERVAL '{days} days'
      {model_filtresi}
    GROUP BY saat
    ORDER BY saat;
    """
    satirlar = psql_sorgu(sql)
    veri = {i: {"adet": 0, "ortalama_ms": 0} for i in range(24)}
    for s in satirlar:
        veri[int(s[0])] = {"adet": int(s[1]), "ortalama_ms": float(s[2]) if s[2] else 0}
    return [{"saat": h, **veri[h]} for h in range(24)]


def gunluk_saatlik_izgara(days: int, model: str) -> tuple[list[str], list[list[int]]]:
    """Saatlik dagilim TOPLU gosterildiginde ('her gunun ayni saati toplansin')
    hangi gunde ne kadar geldigi kayboluyor -- kullanicinin istedigi 'gunleri
    yan yana gorelim' ozelligi icin bu, gun x saat matrisini (heatmap) uretir.
    Donen deger: (sirali gun listesi, gun basina 24 saatlik adet dizisi)."""
    sql = f"""
    SELECT TO_CHAR(DATE("startTime"), 'YYYY-MM-DD') AS gun,
           EXTRACT(HOUR FROM "startTime")::int AS saat,
           COUNT(*) AS adet
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= NOW() - INTERVAL '{days} days'
      AND model = '{sql_kacir(model)}'
    GROUP BY gun, saat
    ORDER BY gun, saat;
    """
    satirlar = psql_sorgu(sql)
    veri: dict[str, dict[int, int]] = {}
    for gun, saat, adet in satirlar:
        veri.setdefault(gun, {})[int(saat)] = int(adet)
    gunler = sorted(veri.keys())
    matris = [[veri[gun].get(h, 0) for h in range(24)] for gun in gunler]
    return gunler, matris


def model_listesi() -> list[str]:
    """Dropdown icin -- loglanmis tum farkli model isimleri."""
    satirlar = psql_sorgu('SELECT DISTINCT model FROM "LiteLLM_SpendLogs" WHERE model IS NOT NULL ORDER BY model;')
    return [s[0] for s in satirlar]


def gunluk_trend_model(days: int, model: str) -> list[dict]:
    """Tek bir modelin gun basina istek sayisi + ortalama sure -- 'Model
    Based' sekmesinin besledigi bolum icin."""
    sql = f"""
    SELECT TO_CHAR(DATE("startTime"), 'YYYY-MM-DD') AS gun,
           COUNT(*) AS adet,
           ROUND(AVG(request_duration_ms)::numeric, 1) AS ortalama_ms
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= NOW() - INTERVAL '{days} days'
      AND model = '{sql_kacir(model)}'
    GROUP BY DATE("startTime")
    ORDER BY gun;
    """
    satirlar = psql_sorgu(sql)
    return [
        {"gun": s[0], "adet": int(s[1]), "ortalama_ms": float(s[2]) if s[2] else 0}
        for s in satirlar
    ]


def model_ozet_metrikleri(days: int, model: str) -> dict | None:
    """Secilen tek model icin genis ozet: toplam istek, basari orani,
    ortalama/min/maks/p95 gecikme, toplam harcama, toplam token, cache hit
    orani. 'daha fazla metrik' istegi icin -- sadece gunluk trend degil."""
    sql = f"""
    SELECT
        COUNT(*) AS toplam_istek,
        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS basarili,
        SUM(CASE WHEN status = 'failure' THEN 1 ELSE 0 END) AS basarisiz,
        ROUND(AVG(request_duration_ms)::numeric, 1) AS ort_ms,
        MIN(request_duration_ms) AS min_ms,
        MAX(request_duration_ms) AS maks_ms,
        ROUND((PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY request_duration_ms))::numeric, 1) AS p95_ms,
        ROUND(SUM(spend)::numeric, 4) AS toplam_harcama,
        SUM(total_tokens) AS toplam_token,
        SUM(CASE WHEN cache_hit = 'True' THEN 1 ELSE 0 END) AS cache_isabet
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" >= NOW() - INTERVAL '{days} days'
      AND model = '{sql_kacir(model)}';
    """
    satirlar = psql_sorgu(sql)
    if not satirlar or not satirlar[0][0] or satirlar[0][0] == "0":
        return None
    s = satirlar[0]

    def sayi(deger: str, tip=int):
        return tip(deger) if deger not in (None, "") else 0

    toplam = sayi(s[0])
    return {
        "toplam_istek": toplam,
        "basarili": sayi(s[1]),
        "basarisiz": sayi(s[2]),
        "basari_orani": round(100 * sayi(s[1]) / toplam, 1) if toplam else 0,
        "ort_ms": sayi(s[3], float),
        "min_ms": sayi(s[4]),
        "maks_ms": sayi(s[5]),
        "p95_ms": sayi(s[6], float),
        "toplam_harcama": sayi(s[7], float),
        "toplam_token": sayi(s[8]),
        "cache_isabet": sayi(s[9]),
        "cache_orani": round(100 * sayi(s[9]) / toplam, 1) if toplam else 0,
    }


def sure_metin(ms: float | int | None) -> str:
    """Ham milisaniyeyi insan-okur hale getirir -- 1000ms uzeri saniyeye
    ceviriyor (ornegin '54086 ms' yerine '54.1s'). Dataviz best-practice:
    okuyucuya birim donusumunu yaptirma, sen yap."""
    if ms is None:
        return "-"
    ms = float(ms)
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def mode_gruplarina_ayir(mm: list[dict]) -> dict[str, list[dict]]:
    """model_mode_ozet ciktisini call_type'a gore gruplar -- her mode kendi
    olcegini alsin diye (bir 54sn'lik goruntu uretme cubugu, milisaniyelik
    chat cubuklarini gorunmez kilmasin)."""
    gruplar: dict[str, list[dict]] = {}
    for satir in mm:
        gruplar.setdefault(satir["call_type"], []).append(satir)
    return gruplar


# LiteLLM Admin UI'nin kendi gorunumune benzetmek icin: ayni font yigini
# (sistem sans-serif), ayni mavi vurgu tonu, yuvarlatilmis-kart + ince
# kenarlik + hafif golge, ayni baslik olcekleri.
CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; background:#f9fafb; color:#111827; padding:24px 32px; max-width:1040px; margin:0 auto; -webkit-font-smoothing:antialiased; }
h1 { font-size:22px; font-weight:600; margin:0 0 4px; letter-spacing:-0.01em; }
.alt-baslik { color:#6b7280; font-size:13px; margin-bottom:24px; }
.sekme-sec { display:flex; gap:8px; margin-bottom:28px; border-bottom:1px solid #e5e7eb; padding-bottom:0; }
.sekme-sec a { color:#6b7280; text-decoration:none; padding:10px 4px; margin-right:20px; font-size:14px; font-weight:500; border-bottom:2px solid transparent; }
.sekme-sec a.aktif { color:#2563eb; border-bottom-color:#2563eb; }
.periyot { margin-bottom:24px; display:flex; gap:8px; }
.periyot-etiket { font-size:11px; color:#6b7280; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:8px; font-weight:600; }
.periyot a { color:#374151; text-decoration:none; padding:6px 14px; border-radius:6px; border:1px solid #d1d5db; font-size:13px; background:#fff; }
.periyot a.aktif { background:#2563eb; color:#fff; border-color:#2563eb; }
.kart { background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 2px rgba(0,0,0,0.04); }
.kart h2 { font-size:15px; font-weight:600; margin:0 0 14px; color:#111827; }
.bolum-baslik { font-size:13px; font-weight:600; color:#374151; text-transform:uppercase; letter-spacing:0.05em; margin:8px 0 12px; }
.mode-etiket { font-size:11px; color:#6b7280; font-weight:normal; }
.bos { color:#6b7280; font-style:italic; padding:20px; text-align:center; }
.model-sec { margin-bottom:20px; }
.model-sec select { background:#fff; color:#111827; border:1px solid #d1d5db; border-radius:6px; padding:8px 12px; font-size:13px; min-width:280px; }
.bolge-aciklama { color:#6b7280; font-size:13px; margin-bottom:20px; }
.stat-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:12px; margin-bottom:20px; }
.stat-kutu { background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:14px 16px; box-shadow:0 1px 2px rgba(0,0,0,0.04); }
.stat-kutu .deger { font-size:20px; font-weight:600; color:#111827; }
.stat-kutu .etiket { font-size:11px; color:#6b7280; text-transform:uppercase; letter-spacing:0.04em; margin-top:2px; }
.gorunum-sec { display:flex; gap:8px; margin-bottom:16px; }
.gorunum-sec button { color:#374151; background:#fff; border:1px solid #d1d5db; border-radius:6px; padding:6px 14px; font-size:13px; cursor:pointer; font-family:inherit; }
.gorunum-sec button.aktif { background:#2563eb; color:#fff; border-color:#2563eb; }
.izgara-sarici { overflow-x:auto; }
.izgara { border-collapse:collapse; font-size:11px; }
.izgara th, .izgara td { padding:4px 6px; text-align:center; border:1px solid #f3f4f6; }
.izgara th { color:#6b7280; font-weight:500; position:sticky; top:0; background:#fff; }
.izgara td.gun-etiketi { color:#374151; font-weight:500; text-align:right; white-space:nowrap; background:#fff; position:sticky; left:0; }
.izgara td.hucre { color:#1e3a8a; font-weight:500; min-width:28px; }
.kpi-satir { display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:12px; margin-bottom:24px; }
"""

# Her iki sekmenin de kendi <script> blogunda kullandigi ortak JS: ms'yi
# okunur hale getiren sureFormatla() + Chart.js tooltip'lerini bu formata
# baglayan tooltipGeriCagirmalari (dataset etiketinde "duration" geciyorsa
# saniye/ms olarak, aksi halde ham sayi olarak gosterir).
ORTAK_JS = """
function sureFormatla(ms) {
  if (ms === null || ms === undefined) return '-';
  return ms >= 1000 ? (ms / 1000).toFixed(2) + 's' : Math.round(ms) + 'ms';
}
const tooltipGeriCagirmalari = {
  label: function(ctx) {
    const etiket = ctx.dataset.label || '';
    const deger = ctx.parsed.x !== null && ctx.parsed.x !== undefined && ctx.chart.options.indexAxis === 'y' ? ctx.parsed.x : ctx.parsed.y;
    if (deger === null || deger === undefined) return null;
    // birim:'ms' -- Python tarafinda suresel dataset'lere elle konan ozel
    // alan (regex'e guvenmek yerine); yoksa etiket metnine bakiyoruz.
    if (ctx.dataset.birim === 'ms' || /duration/i.test(etiket)) {
      return etiket.replace(/\\s*\\(ms\\)/i, '') + ': ' + sureFormatla(deger);
    }
    return etiket + ': ' + Number(deger).toLocaleString();
  }
};
// Sure (ms) iceren bir eksenin tick'lerini de sureFormatla ile gosterir --
// "60000" yerine "60.00s" gibi -- sadece cagiran yerde ilgili eksene uygulanir.
function sureEksenTema(eksen) {
  return {
    ...acikTema,
    scales: {
      ...acikTema.scales,
      [eksen]: { ...acikTema.scales[eksen], ticks: { ...acikTema.scales[eksen].ticks, callback: sureFormatla } }
    }
  };
}
"""


def sekme_url(view: str, days: int, model_days: int, model: str) -> str:
    return f"/?view={view}&days={days}&model_days={model_days}&model={urllib.parse.quote(model)}"


def periyot_secici(view: str, aktif_gun: int, days: int, model_days: int, model: str) -> str:
    """Bir periyot buton grubu -- `view`e gore ya `days` ya da `model_days`
    parametresini degistirir, digerini oldugu gibi korur."""
    parcalar = []
    for d in (7, 30, 90, 365):
        yeni_days = d if view == "all" else days
        yeni_model_days = d if view == "model" else model_days
        aktif = "aktif" if d == aktif_gun else ""
        parcalar.append(
            f'<a href="{sekme_url(view, yeni_days, yeni_model_days, model)}" class="{aktif}">{d} days</a>'
        )
    return "".join(parcalar)


def sayfa_uret(view: str, days: int, model: str = "", model_days: int | None = None) -> str:
    if model_days is None:
        model_days = days
    if view not in ("model", "all"):
        view = "all"

    sekme_html = f"""
<div class="sekme-sec">
  <a href="{sekme_url('model', days, model_days, model)}" class="{'aktif' if view == 'model' else ''}">Model Based</a>
  <a href="{sekme_url('all', days, model_days, model)}" class="{'aktif' if view == 'all' else ''}">All Models</a>
</div>"""

    try:
        if view == "model":
            modeller = model_listesi()
            model_gunluk = gunluk_trend_model(model_days, model) if model else []
            model_metrik = model_ozet_metrikleri(model_days, model) if model else None
            model_saatlik = saatlik_dagilim(model_days, model) if model else []
            model_izgara_gunler, model_izgara = gunluk_saatlik_izgara(model_days, model) if model else ([], [])
        else:
            mm = model_mode_ozet(days)
            gunluk = gunluk_trend(days)
            saatlik = saatlik_dagilim(days)
    except RuntimeError as e:
        return f"<h1>Could not reach Postgres</h1><pre>{html.escape(str(e))}</pre>"

    # ==================== "Model Based" sekmesi =============================
    if view == "model":
        periyot_html = periyot_secici("model", model_days, days, model_days, model)
        model_secenekleri = "".join(
            f'<option value="{html.escape(m)}" {"selected" if m == model else ""}>{html.escape(m)}</option>'
            for m in modeller
        )

        model_secici_taban = sekme_url("model", days, model_days, "")  # zaten "...&model=" ile bitiyor

        if model and model_metrik:
            stat_grid_html = f"""
<div class="stat-grid">
  <div class="stat-kutu"><div class="deger">{model_metrik['toplam_istek']}</div><div class="etiket">Total Requests</div></div>
  <div class="stat-kutu"><div class="deger">{model_metrik['basari_orani']}%</div><div class="etiket">Success Rate</div></div>
  <div class="stat-kutu"><div class="deger">{sure_metin(model_metrik['ort_ms'])}</div><div class="etiket">Avg Latency</div></div>
  <div class="stat-kutu"><div class="deger">{sure_metin(model_metrik['min_ms'])}</div><div class="etiket">Min Latency</div></div>
  <div class="stat-kutu"><div class="deger">{sure_metin(model_metrik['maks_ms'])}</div><div class="etiket">Max Latency</div></div>
  <div class="stat-kutu"><div class="deger">{sure_metin(model_metrik['p95_ms'])}</div><div class="etiket">P95 Latency</div></div>
  <div class="stat-kutu"><div class="deger">${model_metrik['toplam_harcama']:.4f}</div><div class="etiket">Total Spend</div></div>
  <div class="stat-kutu"><div class="deger">{model_metrik['toplam_token']}</div><div class="etiket">Total Tokens</div></div>
  <div class="stat-kutu"><div class="deger">{model_metrik['cache_orani']}%</div><div class="etiket">Cache Hit Rate</div></div>
</div>"""
        elif model:
            stat_grid_html = '<div class="bos">No data for this model in this period.</div>'
        else:
            stat_grid_html = ""

        if model and model_izgara:
            izgara_maks = max((v for satir in model_izgara for v in satir), default=0) or 1
            izgara_basliklar = "".join(f"<th>{h:02d}</th>" for h in range(24))
            izgara_satirlar = []
            for gun, satir in zip(model_izgara_gunler, model_izgara):
                hucreler = []
                for v in satir:
                    yogunluk = v / izgara_maks
                    bg = f"rgba(42,120,214,{yogunluk:.2f})" if v else "transparent"
                    renk = "#fff" if yogunluk > 0.5 else "#1e3a8a"
                    hucreler.append(f'<td class="hucre" style="background:{bg};color:{renk}">{v or ""}</td>')
                izgara_satirlar.append(f'<tr><td class="gun-etiketi">{gun}</td>{"".join(hucreler)}</tr>')
            izgara_html = f"""
<div class="izgara-sarici">
  <table class="izgara">
    <thead><tr><th></th>{izgara_basliklar}</tr></thead>
    <tbody>{"".join(izgara_satirlar)}</tbody>
  </table>
</div>"""
        else:
            izgara_html = '<div class="bos">No data for this model in this period.</div>'

        if model and model_gunluk:
            model_trend_html = f"""
<h3 class="bolum-baslik">Daily Trend -- {html.escape(model)}</h3>
<div class="kart">
  <h2>Request Volume per Day</h2>
  <canvas id="modelGunlukAdetChart" width="900" height="240"></canvas>
</div>
<div class="kart">
  <h2>Average Response Time per Day</h2>
  <canvas id="modelGunlukSureChart" width="900" height="240"></canvas>
</div>

<h3 class="bolum-baslik">Hourly Distribution -- {html.escape(model)}</h3>
<div class="gorunum-sec">
  <button class="aktif" data-hedef="saatlikToplu" onclick="saatGorunumDegistir('saatlikToplu')">Aggregated (0-23)</button>
  <button data-hedef="saatlikGunluk" onclick="saatGorunumDegistir('saatlikGunluk')">By Day (side by side)</button>
</div>
<div id="saatlikToplu">
  <div class="kart">
    <h2>Request Volume by Hour (all days combined)</h2>
    <canvas id="modelSaatlikAdetChart" width="900" height="240"></canvas>
  </div>
  <div class="kart">
    <h2>Average Response Time by Hour (all days combined)</h2>
    <canvas id="modelSaatlikSureChart" width="900" height="240"></canvas>
  </div>
</div>
<div id="saatlikGunluk" hidden>
  <div class="kart">
    <h2>Requests per Hour, Day by Day</h2>
    {izgara_html}
  </div>
</div>"""
            model_trend_js = f"""
new Chart(document.getElementById('modelGunlukAdetChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps([r['gun'] for r in model_gunluk])},
    datasets: [
      {{ label: 'Request count', data: {json.dumps([r['adet'] for r in model_gunluk])}, borderColor: '#2a78d6', backgroundColor: 'rgba(42,120,214,0.1)', fill: true, tension: 0.25 }}
    ]
  }},
  options: acikTema
}});
new Chart(document.getElementById('modelGunlukSureChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps([r['gun'] for r in model_gunluk])},
    datasets: [
      {{ label: 'Average duration (ms)', data: {json.dumps([r['ortalama_ms'] for r in model_gunluk])}, borderColor: '#eb6834', backgroundColor: 'rgba(235,104,52,0.12)', fill: true, tension: 0.25 }}
    ]
  }},
  options: sureEksenTema('y')
}});
new Chart(document.getElementById('modelSaatlikAdetChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([f"{r['saat']:02d}:00" for r in model_saatlik])},
    datasets: [
      {{ label: 'Request count', data: {json.dumps([r['adet'] for r in model_saatlik])}, backgroundColor: '#2a78d6' }}
    ]
  }},
  options: acikTema
}});
new Chart(document.getElementById('modelSaatlikSureChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([f"{r['saat']:02d}:00" for r in model_saatlik])},
    datasets: [
      {{ label: 'Average duration (ms)', data: {json.dumps([r['ortalama_ms'] for r in model_saatlik])}, backgroundColor: '#eb6834' }}
    ]
  }},
  options: sureEksenTema('y')
}});"""
        elif model:
            model_trend_html = ""
            model_trend_js = ""
        else:
            model_trend_html = '<div class="kart"><div class="bos">Select a model above to see its metrics.</div></div>'
            model_trend_js = ""

        return f"""<!doctype html><html><head><meta charset="utf-8">
<title>LiteLLM Metrics Dashboard</title>
<style>{CSS}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
</head><body>
<h1>📊 LiteLLM Metrics Dashboard</h1>
<div class="alt-baslik">Live data from Postgres (LiteLLM_SpendLogs)</div>
{sekme_html}

<div class="bolge-aciklama">A single model's own metrics.</div>
<div class="periyot-etiket">Period</div>
<div class="periyot">{periyot_html}</div>
<div class="model-sec">
  <select onchange="location.href='{model_secici_taban}'+encodeURIComponent(this.value)">
    <option value="">-- Select a model --</option>
    {model_secenekleri}
  </select>
</div>
{stat_grid_html}
{model_trend_html}

<script>
{ORTAK_JS}
const acikTema = {{
  responsive: false,
  plugins: {{ legend: {{ labels: {{ color: '#111827' }} }}, tooltip: {{ callbacks: tooltipGeriCagirmalari }} }},
  scales: {{
    x: {{ ticks: {{ color: '#374151' }}, grid: {{ color: '#e5e7eb' }} }},
    y: {{ ticks: {{ color: '#374151' }}, grid: {{ color: '#e5e7eb' }} }}
  }}
}};
function saatGorunumDegistir(hedef) {{
  document.querySelectorAll('.gorunum-sec button').forEach(b => b.classList.toggle('aktif', b.dataset.hedef === hedef));
  document.getElementById('saatlikToplu').hidden = hedef !== 'saatlikToplu';
  document.getElementById('saatlikGunluk').hidden = hedef !== 'saatlikGunluk';
}}
{model_trend_js}
</script>
</body></html>"""

    # ==================== "All Models" sekmesi ===============================
    periyot_html = periyot_secici("all", days, days, model_days, model)

    gunluk_bos = "" if gunluk else '<div class="bos">No data for this period.</div>'

    gruplar = mode_gruplarina_ayir(mm)
    mode_kartlari = []
    mode_js = []
    for i, (call_type, satirlar) in enumerate(gruplar.items()):
        canvas_id = f"modeChart{i}"
        baslik = MODE_ADLARI.get(call_type, call_type)
        renk = MODE_RENKLERI.get(call_type, "#2a78d6")
        yukseklik = max(180, len(satirlar) * 34)
        mode_kartlari.append(f"""
<div class="kart">
  <h2>{html.escape(baslik)} <span class="mode-etiket">({html.escape(call_type)})</span></h2>
  <canvas id="{canvas_id}" width="900" height="{yukseklik}"></canvas>
</div>""")
        mode_js.append(f"""
new Chart(document.getElementById('{canvas_id}'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([r['model'] for r in satirlar])},
    datasets: [{{
      label: 'Average duration (ms) -- {len(satirlar)} models, {sum(r["adet"] for r in satirlar)} requests',
      data: {json.dumps([r['ortalama_ms'] for r in satirlar])},
      backgroundColor: '{renk}',
      borderRadius: 3
    }}]
  }},
  options: {{ ...sureEksenTema('x'), indexAxis: 'y' }}
}});""")

    mode_kartlari_html = "".join(mode_kartlari) if mode_kartlari else '<div class="kart"><div class="bos">No data for this period.</div></div>'
    mode_js_str = "".join(mode_js)

    # Toplu grafik: seaborn denemesinde begenilen "mode'a gore renklendirme"
    # (hue) fikri burada Chart.js'e tasindi -- her mode kendi dataset'i,
    # degerler kendi etiketi disinda null (stacked ile bosluk birakmiyor),
    # boylece hem renk hem de otomatik legend mode bazinda cikiyor.
    mm_sirali = sorted(mm, key=lambda r: -r["ortalama_ms"])
    toplu_yukseklik = max(280, len(mm_sirali) * 32)
    toplu_bos = "" if mm_sirali else '<div class="bos">No data for this period.</div>'
    toplu_etiketler = [r["model"] for r in mm_sirali]  # mode zaten renk+legend ile belli, tekrar yazmaya gerek yok
    toplu_datasets = []
    for call_type in gruplar:
        degerler = [r["ortalama_ms"] if r["call_type"] == call_type else None for r in mm_sirali]
        toplu_datasets.append({
            "label": MODE_ADLARI.get(call_type, call_type),
            "data": degerler,
            "backgroundColor": MODE_RENKLERI.get(call_type, "#2a78d6"),
            "borderRadius": 3,
            "birim": "ms",
        })
    toplu_html = f"""
<div class="kart">
  <h2>All Models (Combined)</h2>
  {toplu_bos}
  <canvas id="modelChartToplu" width="900" height="{toplu_yukseklik}"></canvas>
</div>"""
    toplu_js = f"""
new Chart(document.getElementById('modelChartToplu'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(toplu_etiketler)},
    datasets: {json.dumps(toplu_datasets)}
  }},
  options: {{
    ...acikTema,
    indexAxis: 'y',
    scales: {{
      ...acikTema.scales,
      x: {{ ...acikTema.scales.x, ticks: {{ ...acikTema.scales.x.ticks, callback: sureFormatla }}, stacked: true }},
      y: {{ ...acikTema.scales.y, stacked: true }}
    }}
  }}
}});"""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>LiteLLM Metrics Dashboard</title>
<style>{CSS}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
</head><body>
<h1>📊 LiteLLM Metrics Dashboard</h1>
<div class="alt-baslik">Live data from Postgres (LiteLLM_SpendLogs)</div>
{sekme_html}

<div class="periyot-etiket">Period</div>
<div class="periyot">{periyot_html}</div>

<h3 class="bolum-baslik">Response Time -- All Models Combined</h3>
{toplu_html}

<h3 class="bolum-baslik">Response Time -- By Mode</h3>
{mode_kartlari_html}

<h3 class="bolum-baslik">Daily Trend</h3>
<div class="kart">
  <h2>Request Volume per Day</h2>
  {gunluk_bos}
  <canvas id="gunlukAdetChart" width="900" height="240"></canvas>
</div>
<div class="kart">
  <h2>Average Response Time per Day</h2>
  <canvas id="gunlukSureChart" width="900" height="240"></canvas>
</div>

<h3 class="bolum-baslik">Hourly Distribution (0-23)</h3>
<div class="kart">
  <h2>Request Volume by Hour</h2>
  <canvas id="saatlikAdetChart" width="900" height="240"></canvas>
</div>
<div class="kart">
  <h2>Average Response Time by Hour</h2>
  <canvas id="saatlikSureChart" width="900" height="240"></canvas>
</div>

<script>
{ORTAK_JS}
const acikTema = {{
  responsive: false,
  plugins: {{ legend: {{ labels: {{ color: '#111827' }} }}, tooltip: {{ callbacks: tooltipGeriCagirmalari }} }},
  scales: {{
    x: {{ ticks: {{ color: '#374151' }}, grid: {{ color: '#e5e7eb' }} }},
    y: {{ ticks: {{ color: '#374151' }}, grid: {{ color: '#e5e7eb' }} }}
  }}
}};

{toplu_js}

{mode_js_str}

new Chart(document.getElementById('gunlukAdetChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps([r['gun'] for r in gunluk])},
    datasets: [
      {{ label: 'Request count', data: {json.dumps([r['adet'] for r in gunluk])}, borderColor: '#2a78d6', backgroundColor: 'rgba(42,120,214,0.1)', fill: true, tension: 0.25 }}
    ]
  }},
  options: acikTema
}});

new Chart(document.getElementById('gunlukSureChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps([r['gun'] for r in gunluk])},
    datasets: [
      {{ label: 'Average duration (ms)', data: {json.dumps([r['ortalama_ms'] for r in gunluk])}, borderColor: '#eb6834', backgroundColor: 'rgba(235,104,52,0.12)', fill: true, tension: 0.25 }}
    ]
  }},
  options: acikTema
}});

new Chart(document.getElementById('saatlikAdetChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([f"{r['saat']:02d}:00" for r in saatlik])},
    datasets: [
      {{ label: 'Request count', data: {json.dumps([r['adet'] for r in saatlik])}, backgroundColor: '#2a78d6' }}
    ]
  }},
  options: acikTema
}});

new Chart(document.getElementById('saatlikSureChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([f"{r['saat']:02d}:00" for r in saatlik])},
    datasets: [
      {{ label: 'Average duration (ms)', data: {json.dumps([r['ortalama_ms'] for r in saatlik])}, backgroundColor: '#eb6834' }}
    ]
  }},
  options: acikTema
}});
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} - {fmt % args}", flush=True)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        try:
            days = int(q.get("days", ["7"])[0])
        except ValueError:
            days = 7
        model = q.get("model", [""])[0]
        try:
            model_days = int(q.get("model_days", [str(days)])[0])
        except ValueError:
            model_days = days
        view = q.get("view", ["all"])[0]

        gövde = sayfa_uret(view, days, model, model_days).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(gövde)))
        self.end_headers()
        self.wfile.write(gövde)


if __name__ == "__main__":
    sunucu = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[dashboard] http://localhost:{PORT} adresinde hazir", flush=True)
    sunucu.serve_forever()
