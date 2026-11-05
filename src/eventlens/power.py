"""Battery health from a ``powercfg /batteryreport /xml`` file (SPEC.md section 12).

Create the file on the Windows PC with::

    powercfg /batteryreport /xml /output battery.xml

Only the capacity figures are read: how much charge the battery was designed
to hold, how much it holds now, and the charge cycle count.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from eventlens.catalog import Severity
from eventlens.sources import SourceError


@dataclass(frozen=True)
class Battery:
    """One battery. Capacities are in mWh."""

    name: str
    design_capacity: int
    full_charge_capacity: int
    cycle_count: int | None = None

    @property
    def wear_percent(self) -> int:
        """How much of the original capacity is lost, 0 to 100."""
        lost = 1 - self.full_charge_capacity / self.design_capacity
        return min(100, max(0, round(lost * 100)))

    @property
    def health_percent(self) -> int:
        return 100 - self.wear_percent

    @property
    def severity(self) -> Severity:
        wear = self.wear_percent
        if wear >= 60:
            return Severity.HIGH
        if wear >= 40:
            return Severity.MEDIUM
        if wear >= 20:
            return Severity.LOW
        return Severity.INFO

    @property
    def summary(self) -> str:
        return {
            Severity.INFO: "The battery is in good shape.",
            Severity.LOW: "The battery has lost some capacity, which is normal with age.",
            Severity.MEDIUM: "The battery is worn: it runs out much sooner than when new.",
            Severity.HIGH: "The battery is badly worn and will not last long away from a charger.",
        }[self.severity]

    @property
    def advice(self) -> str:
        if self.severity >= Severity.MEDIUM:
            return "Plan to replace the battery. Check the maker's battery recall list."
        return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(node: ET.Element, name: str) -> str:
    """A value that powercfg may write as an attribute or as a child element."""
    if name in node.attrib:
        return node.attrib[name].strip()
    for child in node:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _int(node: ET.Element, name: str) -> int | None:
    try:
        return int(_text(node, name))
    except ValueError:
        return None


def parse_battery_report(path: Path) -> list[Battery]:
    """Read the batteries from a ``powercfg /batteryreport /xml`` file.

    Returns an empty list for a PC with no battery, such as a desktop.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SourceError(f"could not read {path}: {exc.strerror or exc}") from exc
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SourceError(f"{path} is not a valid battery report: {exc}") from exc

    if _local(root.tag) != "BatteryReport":
        raise SourceError(f"{path} is not a battery report (made by powercfg /batteryreport /xml)")

    batteries = []
    for node in root.iter():
        if _local(node.tag) != "Battery":
            continue
        design = _int(node, "DesignCapacity")
        full = _int(node, "FullChargeCapacity")
        if not design or full is None:
            continue
        name = _text(node, "Id") or f"Battery {len(batteries) + 1}"
        batteries.append(Battery(name, design, full, _int(node, "CycleCount")))
    # A desktop PC has no battery: its report has an empty <Batteries> list.
    return batteries
