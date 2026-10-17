from app.models import Source


def source_is_publishable(source: Source | None) -> bool:
    if source is None or not source.rights_verified:
        return False
    # A claim must be traceable; a checkbox without evidence is not sufficient.
    license_name = (source.license_name or "").strip()
    permission_reference = (source.permission_reference or "").strip()
    if not license_name and not permission_reference:
        return False
    return True
