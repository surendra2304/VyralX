from app.models import Source


def source_is_publishable(source: Source | None) -> bool:
    if source is None or not source.rights_verified:
        return False
    # A claim must be traceable; a checkbox without evidence is not sufficient.
    if not source.license_name.strip() and not source.permission_reference.strip():
        return False
    return True
