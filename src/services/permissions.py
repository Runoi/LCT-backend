"""The fixed capability-string catalogue (single source of truth).

See `BACKEND_REQUIREMENTS_FROM_FRONTEND_TZ.md` section 3 and
`docs/adr/0002-capability-scope-rbac-with-district-level.md`: authorization
is done through these permission strings plus a resolved scope, never
through a hardcoded role name.
"""

PERMISSIONS: frozenset[str] = frozenset(
    {
        "facility.read.all",
        "facility.read.assigned",
        "sensor.read",
        "risk.read",
        "risk.acknowledge",
        "risk.resolve",
        "work_order.read",
        "work_order.create_draft",
        "work_order.submit",
        "analytics.read.summary",
        "analytics.read.technical",
        "report.export",
        "system.manage",
        "audit.read",
    }
)


def is_valid_permission(permission: str) -> bool:
    """Check whether a permission string is part of the fixed catalogue.

    Args:
        permission: The permission string to validate.

    Returns:
        True if the permission is a known capability string.
    """
    return permission in PERMISSIONS
