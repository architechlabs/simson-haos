"""Redacted details for debugging one Simson location."""
async def async_get_config_entry_diagnostics(hass, entry):
    site = entry.runtime_data
    inventory = site.inventory or {}
    return {
        "connection": site.connection,
        "presence": site.inventory_state,
        "event_checkpoint_present": site.journal.cursor is not None,
        "retained_call_observations": len(site.journal.calls),
        "inventory_endpoints": len(inventory.get("phones", {})),
        "notification_assignments": len(site.routes),
        "notifications_enabled": site.notifications_enabled,
        "observed_events": dict(site.journal.totals),
    }
