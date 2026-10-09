# =====================================================================
# FILE: core/machine_model.py
# =====================================================================
"""
Kinematic description of a rotating machine: its shafts, gear stages and
bearings, and the characteristic orders they produce.

The point of this module is to turn "there is a rise at 47.0x" into "there is a
rise at the 2nd-stage gear mesh". Nothing here reads a signal or computes a
spectrum -- it only knows the geometry of the machine and the arithmetic that
maps that geometry onto shaft orders. `signal_processing/` consumes the result
to label plots; the model itself is persisted with the project.

Here in core/ for the same reason as project_model.py: pure data, no I/O, no
numpy, no Qt, testable in closed form.

Orders are expressed relative to a reference shaft whose order is 1.0 (usually
the shaft the tacho is on). A shaft downstream of a 3:1 step-up runs at order
3.0; a belt reduction might put one at 0.4.

All internal documentation strings and variable labels are standardly written
in English.
"""

from dataclasses import dataclass, field
from math import cos, radians
from typing import List, Optional
import uuid


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# Kind tags on a CharacteristicOrder. String constants rather than an enum so
# they serialise straight into the project file and read back without a lookup.
ORDER_KIND_SHAFT = "shaft"
ORDER_KIND_GEAR_MESH = "gear_mesh"
ORDER_KIND_BEARING_FTF = "bearing_ftf"
ORDER_KIND_BEARING_BPFO = "bearing_bpfo"
ORDER_KIND_BEARING_BPFI = "bearing_bpfi"
ORDER_KIND_BEARING_BSF = "bearing_bsf"


@dataclass(frozen=True)
class CharacteristicOrder:
    """
    One order the machine is expected to excite, with a label to put on a plot.

    `source_id` points back at the shaft / gear stage / bearing it came from, so
    a UI can group them or let the user mute one source.
    """
    order: float
    label: str
    kind: str
    source_id: str


@dataclass
class Shaft:
    """
    A rotating shaft. `order` is its speed as a multiple of the reference
    shaft's speed; the reference shaft is 1.0.
    """
    name: str
    order: float = 1.0
    id: str = field(default_factory=lambda: _new_id("shaft"))

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "order": self.order}

    @classmethod
    def from_dict(cls, data: dict) -> "Shaft":
        return cls(
            id=data.get("id") or _new_id("shaft"),
            name=data.get("name", ""),
            order=float(data.get("order", 1.0)),
        )


@dataclass
class GearStage:
    """
    A gear mounted on `shaft_id` with `teeth` teeth. Its mesh frequency is
    `teeth` events per revolution of that shaft.
    """
    name: str
    shaft_id: str
    teeth: int
    id: str = field(default_factory=lambda: _new_id("gear"))

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "shaft_id": self.shaft_id, "teeth": self.teeth}

    @classmethod
    def from_dict(cls, data: dict) -> "GearStage":
        return cls(
            id=data.get("id") or _new_id("gear"),
            name=data.get("name", ""),
            shaft_id=data.get("shaft_id", ""),
            teeth=int(data.get("teeth", 0)),
        )


@dataclass
class Bearing:
    """
    A rolling-element bearing on `shaft_id`. The four fault frequencies (cage,
    outer race, inner race, rolling element) follow from the standard geometry:
    number of elements, element diameter, pitch diameter and contact angle.

    Diameters share whatever unit the user enters -- only their ratio matters.
    """
    name: str
    shaft_id: str
    rolling_elements: int
    element_diameter: float
    pitch_diameter: float
    contact_angle_deg: float = 0.0
    id: str = field(default_factory=lambda: _new_id("brg"))

    def _ratio(self) -> float:
        return (self.element_diameter / self.pitch_diameter) * cos(radians(self.contact_angle_deg))

    def fault_orders_per_shaft_rev(self) -> dict:
        """
        FTF / BPFO / BPFI / BSF as events per one revolution of the host shaft.
        Multiply by the shaft order for the machine order.
        """
        n = self.rolling_elements
        r = self._ratio()
        return {
            ORDER_KIND_BEARING_FTF: 0.5 * (1.0 - r),
            ORDER_KIND_BEARING_BPFO: (n / 2.0) * (1.0 - r),
            ORDER_KIND_BEARING_BPFI: (n / 2.0) * (1.0 + r),
            ORDER_KIND_BEARING_BSF: (self.pitch_diameter / (2.0 * self.element_diameter)) * (1.0 - r * r),
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "shaft_id": self.shaft_id,
            "rolling_elements": self.rolling_elements,
            "element_diameter": self.element_diameter,
            "pitch_diameter": self.pitch_diameter,
            "contact_angle_deg": self.contact_angle_deg,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Bearing":
        return cls(
            id=data.get("id") or _new_id("brg"),
            name=data.get("name", ""),
            shaft_id=data.get("shaft_id", ""),
            rolling_elements=int(data.get("rolling_elements", 0)),
            element_diameter=float(data.get("element_diameter", 0.0)),
            pitch_diameter=float(data.get("pitch_diameter", 1.0)),
            contact_angle_deg=float(data.get("contact_angle_deg", 0.0)),
        )


_BEARING_LABEL = {
    ORDER_KIND_BEARING_FTF: "FTF",
    ORDER_KIND_BEARING_BPFO: "BPFO",
    ORDER_KIND_BEARING_BPFI: "BPFI",
    ORDER_KIND_BEARING_BSF: "BSF",
}


@dataclass
class MachineModel:
    """
    A machine as a bag of shafts, gear stages and bearings. Referenced from a
    test setup so every measurement of that machine shares one order map.
    """
    name: str
    shafts: List[Shaft] = field(default_factory=list)
    gear_stages: List[GearStage] = field(default_factory=list)
    bearings: List[Bearing] = field(default_factory=list)
    id: str = field(default_factory=lambda: _new_id("machine"))

    def shaft_by_id(self, shaft_id: str) -> Optional[Shaft]:
        return next((s for s in self.shafts if s.id == shaft_id), None)

    def characteristic_orders(self) -> List[CharacteristicOrder]:
        """
        Every order this machine is expected to excite, sorted ascending.

        A gear stage or bearing whose host shaft is missing is skipped rather
        than raising -- a half-built model should still describe what it can.
        """
        out: List[CharacteristicOrder] = []

        for shaft in self.shafts:
            out.append(CharacteristicOrder(
                order=shaft.order, label=f"{shaft.name} 1X",
                kind=ORDER_KIND_SHAFT, source_id=shaft.id,
            ))

        for gear in self.gear_stages:
            shaft = self.shaft_by_id(gear.shaft_id)
            if shaft is None:
                continue
            out.append(CharacteristicOrder(
                order=gear.teeth * shaft.order, label=f"{gear.name} GMF",
                kind=ORDER_KIND_GEAR_MESH, source_id=gear.id,
            ))

        for bearing in self.bearings:
            shaft = self.shaft_by_id(bearing.shaft_id)
            if shaft is None:
                continue
            for kind, per_rev in bearing.fault_orders_per_shaft_rev().items():
                out.append(CharacteristicOrder(
                    order=per_rev * shaft.order,
                    label=f"{bearing.name} {_BEARING_LABEL[kind]}",
                    kind=kind, source_id=bearing.id,
                ))

        out.sort(key=lambda co: co.order)
        return out

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "shafts": [s.to_dict() for s in self.shafts],
            "gear_stages": [g.to_dict() for g in self.gear_stages],
            "bearings": [b.to_dict() for b in self.bearings],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MachineModel":
        return cls(
            id=data.get("id") or _new_id("machine"),
            name=data.get("name", ""),
            shafts=[Shaft.from_dict(d) for d in data.get("shafts", [])],
            gear_stages=[GearStage.from_dict(d) for d in data.get("gear_stages", [])],
            bearings=[Bearing.from_dict(d) for d in data.get("bearings", [])],
        )
