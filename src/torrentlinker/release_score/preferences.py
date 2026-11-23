"""Persisted ReleaseScore profiles and equipment, shared by all clients."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from torrentlinker.release_score import PROFILES


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    res: Literal["1080", "2160"] = "1080"
    basse: Literal["penal", "ok"] = "penal"
    hdr: Literal["sdr-req", "sdr-pref", "indiff", "pref", "requis"] = "sdr-pref"
    dv: Literal["auto", "refuse", "deconseille", "ok"] = "auto"
    avi: Literal["auto", "refuse", "deconseille", "ok"] = "auto"
    codec: Literal["requis", "pref", "indiff"] = "pref"
    langue: Literal["vff", "vf", "vo", "indiff"] = "vff"
    st: Literal["indiff", "pref", "requis"] = "indiff"
    audio: Literal["correct", "bon", "sansperte"] = "correct"
    poidsAudio: float = Field(default=15, ge=0, le=60)
    cible: float = Field(default=2, ge=0, le=60)
    plafond: float = Field(default=2.5, ge=0, le=80)


class Equipment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    taille: float | None = Field(default=None, ge=10, le=300)
    distance: float | None = Field(default=None, ge=0.3, le=20)
    definition: Literal["", "1080", "4k"] = Field(default="", alias="def")
    hdr: Literal["", "oui", "non"] = ""
    dv: Literal["", "oui", "non"] = ""
    avi: Literal["", "oui", "non"] = ""
    av1: Literal["", "oui", "non"] = ""
    dts: Literal["", "oui", "non"] = ""
    son: Literal["", "tv", "barre", "51", "atmos"] = ""
    priorite: Literal["", "place", "equilibre", "qualite"] = ""
    ecran: str = Field(default="", max_length=120)
    appareil: str = Field(default="", max_length=120)

    def recommendation(self) -> dict:
        """Port of upstream equipement.conseiller's deterministic profile choices."""
        t, d, priority = self.taille, self.distance, self.priorite
        hdr = self.definition == "4k" and self.hdr == "oui" and priority != "place"
        four_k = (
            self.definition == "4k"
            and priority != "place"
            and (
                not t
                or not d
                or d <= t * 0.03964
                or (d <= t * 0.0621 and priority == "qualite")
                or hdr
            )
        )
        res = "2160" if four_k else "1080"
        audio, weight = {
            "tv": ("correct", 15),
            "barre": ("bon", 15),
            "51": ("bon", 20),
            "atmos": ("sansperte", 30) if priority == "qualite" else ("bon", 25),
        }.get(self.son, ("correct", 15))
        targets = {
            "place": ((1, 1.5), (3, 4)),
            "equilibre": ((2, 2.5), (5, 6)),
            "qualite": ((4, 6), (20, 40)),
        }
        target, cap = targets[priority or "equilibre"][int(four_k)]
        return Profile.model_validate(
            dict(
                res=res,
                basse="ok" if priority == "place" else "penal",
                hdr="sdr-req"
                if self.hdr == "non"
                else "pref"
                if self.hdr == "oui" and four_k
                else "indiff",
                audio=audio,
                poidsAudio=weight,
                cible=target,
                plafond=cap,
            )
        ).model_dump()


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: str = "HDLight 1080p"
    profiles: dict[str, Profile] = Field(
        default_factory=lambda: {n: Profile(**p) for n, p in PROFILES.items()}, max_length=100
    )
    equipment: Equipment = Field(default_factory=Equipment)
    # Media suggests c411 releases scoring at least this much.
    threshold: int = Field(default=90, ge=0, le=100)

    @model_validator(mode="after")
    def valid_profiles(self):
        if not PROFILES.keys() <= self.profiles.keys():
            raise ValueError("Built-in profiles cannot be deleted or renamed.")
        if self.active not in self.profiles:
            raise ValueError("Choose an existing ReleaseScore profile.")
        if any(
            not name.strip()
            or name != name.strip()
            or len(name) > 120
            or name in {"__proto__", "constructor", "prototype"}
            for name in self.profiles
        ):
            raise ValueError("Use a profile name between 1 and 120 characters.")
        return self
