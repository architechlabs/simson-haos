"""Shared entity base and device registry helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SITE_NAME, CONF_TENANT_NAME, DOMAIN
from .coordinator import SimsonCoordinator
from .model import Extension


def workspace_device(coordinator: SimsonCoordinator) -> DeviceInfo:
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.tenant_id}:{coordinator.site_id}")},
        name=f"{entry.data.get(CONF_TENANT_NAME, 'Simson')} · {entry.data.get(CONF_SITE_NAME, '')}".strip(" ·"),
        manufacturer="Architech Labs",
        model="Simson location",
        configuration_url="https://simson.architechlabs.in/dashboard/",
    )


def extension_device(coordinator: SimsonCoordinator, extension: Extension) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, extension.id)},
        name=f"{extension.extension} {extension.name}".strip(),
        manufacturer="Architech Labs",
        model="SIP gateway" if extension.gateway else "SIP phone",
        via_device=(DOMAIN, f"{coordinator.tenant_id}:{coordinator.site_id}"),
    )


class SimsonEntity(CoordinatorEntity[SimsonCoordinator]):
    """Base for everything that reads the shared workspace snapshot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SimsonCoordinator) -> None:
        super().__init__(coordinator)
