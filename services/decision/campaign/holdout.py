"""
holdout.py — Holdout Control Group Splitter (Minggu 9)
======================================================
Membagi audiens kampanye menjadi Treatment Group (default 90%) dan Holdout Control Group
(default 10%) secara ACAK-DETERMINISTIK memakai hashing `customer_id + random_seed`.

Mengapa hashing, bukan random():
- Hasil sama persis setiap kali dijalankan (reproduksi audit / sidang), tanpa perlu
  menyimpan daftar anggota.
- Anggota satu pelanggan tidak berubah bila audiens bertambah/berkurang.
- Memakai SHA-256 (bukan `hash()` bawaan Python yang berubah tiap proses).

Kontrak: K-08 (`control_holdout_ratio`, `random_seed`, `ab_test_ratio`).
- `control_holdout_ratio` harus 0 < r < 1 (default 0.10).
- Jika `control_holdout_ratio` diisi, `random_seed` WAJIB ada (K-08 `dependencies`).
- Jika hanya `ab_test_ratio` diisi, rasio control = (100 - ab_test_ratio) / 100.

CATATAN: pembagian hash itu ACAK-DETERMINISTIK, jadi proporsi aktual mendekati, bukan persis,
rasio target (terutama pada audiens kecil). Gunakan `HoldoutSplit.actual_control_ratio`.

Isolasi Control Group secara mekanis dijaga oleh `simulator/channel_sim.py`, yang menolak
mengirim ke anggota control.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

DEFAULT_HOLDOUT_RATIO: float = 0.10
"""Proporsi Holdout Control Group default (target_definitions.md, CONTROL_HOLDOUT_RATIO)."""

GROUP_TREATMENT = "TREATMENT"
GROUP_CONTROL = "CONTROL"


# ---------------------------------------------------------------------------
# Validasi & hashing
# ---------------------------------------------------------------------------


def _validate_ratio(holdout_ratio: float) -> float:
    if isinstance(holdout_ratio, bool) or not isinstance(holdout_ratio, (int, float)):
        raise ValueError("holdout_ratio harus berupa angka.")
    if not 0.0 < float(holdout_ratio) < 1.0:
        raise ValueError(
            f"holdout_ratio harus di antara 0 dan 1 (eksklusif), diterima {holdout_ratio}."
        )
    return float(holdout_ratio)


def _validate_seed(random_seed: int) -> int:
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise ValueError("random_seed harus berupa integer.")
    return random_seed


def _clean_customer_id(customer_id: Any) -> str:
    text = str(customer_id).strip() if customer_id is not None else ""
    if not text:
        raise ValueError("customer_id tidak boleh kosong.")
    return text


def hash_bucket(customer_id: str, random_seed: int) -> float:
    """
    Memetakan (customer_id, random_seed) ke angka deterministik di [0, 1).

    Memakai 53 bit teratas SHA-256 agar pembagian ke 2**53 tepat di float (tidak pernah 1.0).
    """
    cid = _clean_customer_id(customer_id)
    seed = _validate_seed(random_seed)
    digest = hashlib.sha256(f"{cid}:{seed}".encode("utf-8")).digest()
    top53 = int.from_bytes(digest[:8], "big") >> 11
    return top53 / float(1 << 53)


def assign_group(
    customer_id: str,
    random_seed: int,
    holdout_ratio: float = DEFAULT_HOLDOUT_RATIO,
) -> str:
    """Mengembalikan `CONTROL` bila bucket < holdout_ratio, selain itu `TREATMENT`."""
    ratio = _validate_ratio(holdout_ratio)
    return (
        GROUP_CONTROL
        if hash_bucket(customer_id, random_seed) < ratio
        else GROUP_TREATMENT
    )


# ---------------------------------------------------------------------------
# Hasil pembagian
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldoutSplit:
    """Hasil pembagian audiens satu kampanye (tidak dapat diubah setelah dibuat)."""

    campaign_id: str
    random_seed: int
    holdout_ratio: float
    treatment_ids: Tuple[str, ...]
    control_ids: Tuple[str, ...]
    duplicates_removed: int = 0
    _treatment_set: FrozenSet[str] = field(init=False, repr=False, compare=False)
    _control_set: FrozenSet[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        treatment = frozenset(self.treatment_ids)
        control = frozenset(self.control_ids)
        if treatment & control:
            raise ValueError("Seorang pelanggan tidak boleh berada di dua grup.")
        object.__setattr__(self, "_treatment_set", treatment)
        object.__setattr__(self, "_control_set", control)

    @property
    def n_treatment(self) -> int:
        return len(self.treatment_ids)

    @property
    def n_control(self) -> int:
        return len(self.control_ids)

    @property
    def n_total(self) -> int:
        return self.n_treatment + self.n_control

    @property
    def has_control_group(self) -> bool:
        return self.n_control > 0

    @property
    def actual_control_ratio(self) -> float:
        return self.n_control / self.n_total if self.n_total else 0.0

    def group_of(self, customer_id: str) -> Optional[str]:
        """`TREATMENT`, `CONTROL`, atau None bila pelanggan bukan bagian audiens."""
        cid = _clean_customer_id(customer_id)
        if cid in self._control_set:
            return GROUP_CONTROL
        if cid in self._treatment_set:
            return GROUP_TREATMENT
        return None

    def is_control(self, customer_id: str) -> bool:
        return self.group_of(customer_id) == GROUP_CONTROL

    def is_treatment(self, customer_id: str) -> bool:
        return self.group_of(customer_id) == GROUP_TREATMENT

    def to_dict(self, include_ids: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "campaign_id": self.campaign_id,
            "random_seed": self.random_seed,
            "control_holdout_ratio": self.holdout_ratio,
            "actual_control_ratio": self.actual_control_ratio,
            "n_treatment": self.n_treatment,
            "n_control": self.n_control,
            "duplicates_removed": self.duplicates_removed,
        }
        if include_ids:
            data["treatment_ids"] = list(self.treatment_ids)
            data["control_ids"] = list(self.control_ids)
        return data


# ---------------------------------------------------------------------------
# Fungsi utama
# ---------------------------------------------------------------------------


def split_audience(
    customer_ids: Iterable[str],
    random_seed: int,
    holdout_ratio: float = DEFAULT_HOLDOUT_RATIO,
    campaign_id: str = "",
) -> HoldoutSplit:
    """
    Membagi audiens menjadi Treatment dan Holdout Control.

    ID ganda hanya dihitung sekali (urutan kemunculan pertama dipertahankan) dan jumlah
    duplikat dicatat di `duplicates_removed`.
    """
    ratio = _validate_ratio(holdout_ratio)
    seed = _validate_seed(random_seed)
    seen: set[str] = set()
    treatment: List[str] = []
    control: List[str] = []
    duplicates = 0
    for raw in customer_ids:
        cid = _clean_customer_id(raw)
        if cid in seen:
            duplicates += 1
            continue
        seen.add(cid)
        if hash_bucket(cid, seed) < ratio:
            control.append(cid)
        else:
            treatment.append(cid)
    return HoldoutSplit(
        campaign_id=campaign_id,
        random_seed=seed,
        holdout_ratio=ratio,
        treatment_ids=tuple(treatment),
        control_ids=tuple(control),
        duplicates_removed=duplicates,
    )


def split_from_campaign(
    campaign: Mapping[str, Any], customer_ids: Iterable[str]
) -> HoldoutSplit:
    """
    Membagi audiens memakai metadata kampanye bentuk K-08.

    Aturan rasio:
      1. `control_holdout_ratio` diisi -> dipakai (dan `ab_test_ratio` diabaikan).
      2. Jika tidak, `ab_test_ratio` diisi -> control = (100 - ab_test_ratio) / 100.
      3. Jika keduanya kosong -> 0.10.
    `random_seed` selalu wajib agar pembagian dapat direproduksi.
    """
    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ValueError("campaign_id wajib diisi (K-08).")
    seed = campaign.get("random_seed")
    if seed is None:
        raise ValueError("random_seed wajib diisi agar pembagian dapat direproduksi.")

    ratio_raw = campaign.get("control_holdout_ratio")
    if ratio_raw is not None:
        ratio = ratio_raw
    elif campaign.get("ab_test_ratio") is not None:
        ratio = (100 - campaign["ab_test_ratio"]) / 100
    else:
        ratio = DEFAULT_HOLDOUT_RATIO
    return split_audience(customer_ids, seed, ratio, campaign_id=campaign_id)
