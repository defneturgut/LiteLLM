"""
OZEL GUARDRAIL / HOOK -- LiteLLM Proxy'ye takilan kendi Python kodun.
================================================================================
Bu dosya container'a /app/config/custom_guardrail.py olarak baglanir ve
config.yaml'da su satirla devreye girer:

    litellm_settings:
      callbacks: custom_guardrail.proxy_handler_instance

NE ISE YARAR? Istek saglayiciya GITMEDEN once araya girip:
  * yasakli icerigi ENGELLEYEBILIRSIN      (prompt injection, kufur, rakip adi)
  * hassas veriyi MASKELEYEBILIRSIN        (TC kimlik, IBAN, e-posta, telefon)
  * istegi DEGISTIREBILIRSIN               (sistem promptu ekle, model degistir)
  * kendi is kurallarini uygulayabilirsin  (mesai disi pahali model yasak vb.)

Cevap dondukten sonra da araya girebilirsin (async_post_call_success_hook).

KURUMSAL ALTERNATIFLER (hazir entegrasyonlar):
    presidio (PII maskeleme), lakera, aporia, bedrock guardrails,
    azure content safety, openai moderation, pangea, javelin
"""

import re
from typing import Any, Literal, Optional

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

# --- Kurallar -------------------------------------------------------------
YASAKLI_KELIMELER = ["bomba yapimi", "ignore previous instructions", "sistem promptunu yazdir"]

# DIKKAT -- SIRA ONEMLIDIR: kalilar yukaridan asagi uygulanir.
# Turk cep telefonu (05551234567) da 11 hanelidir; TCKN kalibini once
# koyarsan telefonlari yanlislikla TCKN olarak maskeler. Bu, PII kurallarinda
# en sik yapilan hatadir: DAR kalibi genis kalibin USTUNE yaz.
MASKELER = [
    (re.compile(r"\bTR\d{2}[\s\d]{20,28}\b"), "[IBAN-GIZLENDI]"),
    (re.compile(r"[\w\.\-]+@[\w\.\-]+\.\w+"), "[EPOSTA-GIZLENDI]"),
    (re.compile(r"\b(?:\+90|0)5\d{9}\b"), "[TELEFON-GIZLENDI]"),   # once telefon
    (re.compile(r"\b[1-9]\d{10}\b"), "[TCKN-GIZLENDI]"),           # sonra TCKN
]


def _maskele(metin: str):
    """Metindeki hassas veriyi maskeler. (maskelenmis_metin, kac_adet) doner."""
    toplam = 0
    for kalip, yerine in MASKELER:
        metin, adet = kalip.subn(yerine, metin)
        toplam += adet
    return metin, toplam


class BenimGuardrail(CustomLogger):

    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type: Literal[
            "completion", "text_completion", "embeddings", "image_generation",
            "moderation", "audio_transcription", "responses", "mcp_call",
        ],
    ) -> Optional[Any]:
        """
        Istek saglayiciya gitmeden ONCE calisir.
          - None dondurursen        -> istek oldugu gibi devam eder
          - degistirilmis data      -> degisiklikler uygulanir
          - HTTPException firlatirsan -> istek REDDEDILIR
        """
        mesajlar = data.get("messages") or []
        maskelenen = 0

        for m in mesajlar:
            icerik = m.get("content")
            if not isinstance(icerik, str):
                continue

            # 1) YASAKLI ICERIK -> engelle
            dusuk = icerik.lower()
            for kelime in YASAKLI_KELIMELER:
                if kelime in dusuk:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "Guardrail tarafindan engellendi",
                            "kural": "yasakli_icerik",
                            "eslesme": kelime,
                        },
                    )

            # 2) HASSAS VERI -> maskele (engelleme, sadece temizle)
            m["content"], adet = _maskele(icerik)
            maskelenen += adet

        if maskelenen:
            data.setdefault("metadata", {})["guardrail_maskelenen"] = maskelenen
            print(f"[guardrail] {maskelenen} adet hassas veri maskelendi", flush=True)

        # 3) IS KURALI ORNEGI: bu anahtarin metadata'sinda "kisitli" varsa
        #    pahali modeli kullandirtma
        meta = getattr(user_api_key_dict, "metadata", None) or {}
        if meta.get("kisitli") and data.get("model") in ("premium-model", "pahali-model"):
            data["model"] = "ucuz-model"
            print("[guardrail] kisitli anahtar -> model ucuz-model'e dusuruldu",
                  flush=True)

        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        """Cevap kullaniciya gitmeden ONCE calisir -> cikti filtreleme burada."""
        try:
            for secim in getattr(response, "choices", []) or []:
                icerik = getattr(getattr(secim, "message", None), "content", None)
                if isinstance(icerik, str):
                    temiz, adet = _maskele(icerik)
                    if adet:
                        secim.message.content = temiz
                        print(f"[guardrail] cevapta {adet} hassas veri maskelendi",
                              flush=True)
        except Exception as e:                                  # guardrail asla
            print(f"[guardrail] cikti kontrolu atlandi: {e}", flush=True)  # servisi dusurmesin
        return response

    async def async_post_call_failure_hook(self, request_data, original_exception,
                                           user_api_key_dict, traceback_str=None):
        """Hata olustugunda calisir -> alarm/metrik gondermek icin ideal yer."""
        print(f"[guardrail] HATA: {type(original_exception).__name__}", flush=True)

    async def async_post_call_streaming_iterator_hook(self, user_api_key_dict, response, request_data):
        """
        STREAMING icin -- async_post_call_success_hook streaming'de calismiyor
        (LiteLLM kaynagi: "audit-only, content already delivered to client").
        Yani bu metot OLMADAN cevap chunk chunk kullaniciya giderken hicbir
        maskeleme yapilmiyordu -- model kendi urettigi hassas veriyi CANLI
        sizdirabiliyordu.

        Cozum: LiteLLM'in kendi Presidio entegrasyonuyla AYNI desen --
        TCKN/IBAN gibi kaliplar birden fazla chunk'a bolunebilir (ornegin
        "9876" bir chunk'ta, "5432109" bir sonrakinde), o yuzden chunk chunk
        maskelemek guvenilmez. Tum akisi BIRIKTIR, TEK PARCA metne birlestir,
        maskele, SONRA tek seferde gonder. Bedeli: gercek "kelime kelime akis"
        kayboluyor (kullanici cevabi TOPLU alir) -- ama bu, guvenlik icin dogru
        takas. Ayni odunu LiteLLM'in kendi Presidio kodu da veriyor.
        """
        from litellm.llms.base_llm.base_model_iterator import convert_model_response_to_streaming
        from litellm.main import stream_chunk_builder
        from litellm.types.utils import ModelResponse, ModelResponseStream

        tum_parcalar = []
        try:
            async for parca in response:
                if isinstance(parca, ModelResponseStream):
                    tum_parcalar.append(parca)
                else:
                    # Tanimadigimiz bir sekil (orn. ham SSE bytes) -- guvenli
                    # tarafta kal, maskeleme yapmadan oldugu gibi gecir.
                    yield parca

            if not tum_parcalar:
                return

            birlesik = stream_chunk_builder(chunks=tum_parcalar, messages=request_data.get("messages"))
            if not isinstance(birlesik, ModelResponse):
                for parca in tum_parcalar:
                    yield parca
                return

            maskelenmis = await self.async_post_call_success_hook(
                data=request_data, user_api_key_dict=user_api_key_dict, response=birlesik)

            yield convert_model_response_to_streaming(maskelenmis)

        except Exception as e:
            print(f"[guardrail] streaming maskeleme atlandi: {e}", flush=True)
            for parca in tum_parcalar:
                yield parca


# LiteLLM bu ismi arar: "custom_guardrail.proxy_handler_instance"
proxy_handler_instance = BenimGuardrail()
