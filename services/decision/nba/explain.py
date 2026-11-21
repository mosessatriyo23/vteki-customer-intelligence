"""
explain.py — Alasan keputusan NBA dalam kalimat yang mudah dipahami
===================================================================
Revisi mentor (Fase 4 lanjutan): "alasan skor ditulis pakai kalimat yang gampang
dipahami".

`DecisionRecord.rationale_text` (K-07) sengaja tetap teknis karena dipakai audit
(memuat kode seperti ALL_CANDIDATES_BLOCKED). Modul ini menambahkan versi kedua,
`plain_rationale`, untuk ditampilkan ke staf bisnis di UI.

Aturan (sesuai arahan mentor "jangan pernah menampilkan angka contoh seolah hasil asli"):
  - Fungsi MURNI: hanya membaca `DecisionRecord`; tanpa database, jaringan, atau LLM.
  - Tidak ada angka karangan. Bila skor belum ada / kedaluwarsa (`degraded_input`),
    kalimat mengatakan "data skor belum tersedia" dan TIDAK menampilkan angka EV/skor.
  - Reason code TIDAK diterjemahkan di sini (tidak dipakai logika keputusan; lihat
    D5). Alasan skor berasal dari formatter Moses dan disisipkan apa adanya.

Dipanggil oleh `services/decision/nba/serving.py`; James/Marvin cukup memakai hasilnya.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from services.decision.nba.engine import (
    NO_ACTION_REASON_ALL_BLOCKED,
    NO_ACTION_REASON_BELOW_MIN_EV,
    NO_ACTION_REASON_FREQ_CAP,
    NO_ACTION_REASON_OPT_OUT,
    DecisionRecord,
)

PLAIN_RATIONALE_VERSION = "plain-id-1.1"
"""Versi templat kalimat; dicatat agar perubahan redaksi dapat ditelusuri."""

ACTION_LABELS: Dict[str, str] = {
    "NO_ACTION": "tidak melakukan apa-apa",
    "COMPLAINT_RESOLUTION": "menyelesaikan keluhan pelanggan",
    "RELATIONSHIP_MANAGER_CONTACT": "dihubungi relationship manager",
    "RETENTION_OUTREACH": "pendekatan agar pelanggan tetap bertahan",
    "CROSS_SELL": "memperkenalkan produk di kategori lain",
    "UPSELL": "menawarkan peningkatan keanggotaan",
    "RENEWAL_REMINDER": "pengingat perpanjangan keanggotaan",
    "SERVICE_REMINDER": "pengingat jadwal layanan",
    "EDUCATION": "edukasi layanan dan produk",
    "LOYALTY_REWARD": "ucapan terima kasih dan poin loyalitas",
    "WIN_BACK_OFFER": "penawaran agar pelanggan kembali",
}

CHANNEL_LABELS: Dict[str, str] = {
    "email": "email",
    "push": "notifikasi aplikasi",
    "sms": "SMS",
    "phone": "telepon",
    "branch": "kunjungan cabang",
    "task_rm": "tugas untuk relationship manager",
}

BAND_LABELS: Dict[str, str] = {
    "LOW": "rendah",
    "MEDIUM": "sedang",
    "HIGH": "tinggi",
    "VERY_HIGH": "sangat tinggi",
}

_NO_SCORE_SENTENCE = (
    "Data skor prediksi pelanggan ini belum tersedia atau sudah kedaluwarsa, "
    "sehingga sistem tidak memakai angka skor dan memilih langkah yang paling aman."
)


def _label(action_id: str) -> str:
    return ACTION_LABELS.get(action_id, action_id.replace("_", " ").lower())


def _channel_label(channel: Optional[str]) -> str:
    if not channel:
        return ""
    return CHANNEL_LABELS.get(channel.lower(), channel)


def _failed_checks(checks: List[Dict[str, Any]]) -> List[str]:
    return [str(c.get("check_name")) for c in checks if c.get("passed") is False]


def _rupiah(amount: float) -> str:
    """Format Rupiah Indonesia: titik sebagai pemisah ribuan (Rp 2.158.000)."""
    return "Rp " + f"{amount:,.0f}".replace(",", ".")


def _moses_explanation_sentences(
    explanation: Optional[Mapping[str, Any]],
) -> List[str]:
    """
    Kalimat penjelasan skor dari formatter Moses (`score_explanations`), disisipkan
    APA ADANYA (tidak ditulis ulang). Bentuk tidak valid diabaikan, bukan diperbaiki.
    """
    if not isinstance(explanation, Mapping):
        return []
    sentences = explanation.get("sentences")
    if not isinstance(sentences, (list, tuple)) or not sentences:
        return []
    if not all(isinstance(item, str) and item.strip() for item in sentences):
        return []
    out = ["Penjelasan skor: " + " ".join(item.strip() for item in sentences)]
    notice = explanation.get("notice")
    if isinstance(notice, str) and notice.strip():
        out.append(notice.strip())
    return out


def _score_sentence(
    record: DecisionRecord,
    score_note: Optional[str],
    score_explanation: Optional[Mapping[str, Any]],
) -> str:
    """Kalimat tentang skor; kosong bila skor tidak tersedia (tidak ada angka palsu)."""
    if record.degraded_input:
        return score_note or _NO_SCORE_SENTENCE
    snapshot = record.scores_snapshot or {}
    band = BAND_LABELS.get(str(snapshot.get("churn_risk_band")), None)
    sentences: List[str] = []
    if band is not None:
        sentences.append(f"Risiko pelanggan berhenti berbelanja tergolong {band}.")
    sentences.extend(_moses_explanation_sentences(score_explanation))
    return " ".join(sentences)


def explain_decision(
    record: DecisionRecord,
    *,
    score_note: Optional[str] = None,
    score_explanation: Optional[Mapping[str, Any]] = None,
) -> str:
    """
    Mengubah `DecisionRecord` menjadi paragraf pendek berbahasa Indonesia sehari-hari.

    Tidak pernah menampilkan angka bila skor belum tersedia. Hanya menampilkan
    perkiraan nilai (EV, Rupiah) bila skor valid dan aksi yang dipilih bukan NO_ACTION.

    Args:
        score_note: kalimat alasan spesifik mengapa skor tidak dipakai (mis. belum
            direview orang lain). Hanya dipakai saat `degraded_input`; diisi oleh
            `serving.py` yang tahu penyebabnya.
        score_explanation: keluaran `explain_contributions` Moses (`sentences`,
            `notice`, `version`). Disisipkan apa adanya HANYA bila skor benar-benar
            dipakai. Modul ini tidak menerjemahkan reason code sendiri, supaya
            "kenapa skor ini" punya satu sumber redaksi (Moses) dan "kenapa keputusan
            ini" punya satu sumber (modul ini).
    """
    selected = record.selected_action_id
    failed = _failed_checks(record.checks)
    sentences: List[str] = []

    if selected == "COMPLAINT_RESOLUTION":
        sentences.append(
            "Pelanggan ini punya keluhan berat yang belum selesai, jadi semua promosi "
            "ditahan. Langkah yang disarankan adalah menyelesaikan keluhannya dulu."
        )
    elif selected == "NO_ACTION":
        reason = record.no_action_reason
        score_is_the_cause = record.degraded_input and reason in (
            NO_ACTION_REASON_ALL_BLOCKED,
            NO_ACTION_REASON_BELOW_MIN_EV,
        )
        if score_is_the_cause:
            sentences.append(
                "Belum ada rekomendasi pesan untuk pelanggan ini, jadi tidak ada pesan "
                "yang dikirim."
            )
        elif reason == NO_ACTION_REASON_OPT_OUT:
            sentences.append(
                "Tidak ada pesan yang dikirim karena pelanggan menolak dihubungi "
                "atau belum ada izin kontak yang jelas."
            )
        elif reason == NO_ACTION_REASON_FREQ_CAP:
            sentences.append(
                "Tidak ada pesan yang dikirim karena pelanggan sudah menerima "
                "terlalu banyak pesan dalam 14 hari terakhir (maksimal 2)."
            )
        elif reason == NO_ACTION_REASON_ALL_BLOCKED:
            sentences.append(
                "Tidak ada pesan yang dikirim karena tidak ada aksi yang memenuhi "
                "syarat kelayakan atau kesesuaian produk untuk pelanggan ini."
            )
        elif reason == NO_ACTION_REASON_BELOW_MIN_EV:
            sentences.append(
                "Tidak ada pesan yang dikirim karena perkiraan manfaatnya lebih kecil "
                "dari batas minimum yang ditetapkan, jadi tidak sepadan dengan biayanya."
            )
        elif "CONSENT_CHECK" in failed:
            sentences.append(
                "Tidak ada pesan yang dikirim karena pelanggan belum memberi izin "
                "pada kanal yang tersedia."
            )
        else:
            sentences.append(
                "Sistem memilih untuk tidak melakukan apa-apa untuk pelanggan ini."
            )
        if reason in (NO_ACTION_REASON_OPT_OUT, NO_ACTION_REASON_FREQ_CAP):
            sentences.append(
                "Skor yang tinggi saja tidak cukup untuk mengabaikan aturan ini."
            )
    else:
        channel = _channel_label(record.channel_selected)
        via = f" lewat {channel}" if channel else ""
        sentences.append(f"Disarankan: {_label(selected)}{via}.")
        if not record.degraded_input:
            sentences.append(
                f"Perkiraan manfaat bersihnya sekitar {_rupiah(record.expected_value)} "
                "(hasil hitung sistem, bukan jaminan)."
            )

    score_sentence = _score_sentence(record, score_note, score_explanation)
    if score_sentence:
        sentences.append(score_sentence)

    return " ".join(sentences)
