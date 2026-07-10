class SignRiverError(Exception):
    """Base exception for errors that can be shown to the user."""


class ConfigurationError(SignRiverError):
    pass


class ManifestError(SignRiverError):
    pass


class DownloadError(SignRiverError):
    pass


class IntegrityError(SignRiverError):
    pass


class PackageError(SignRiverError):
    pass


class ModuleLoadError(SignRiverError):
    pass


class FullUpdateRequired(SignRiverError):
    def __init__(self, version: str, url: str, notes: str = "") -> None:
        super().__init__(f"Launcher update {version} requires a full package")
        self.version = version
        self.url = url
        self.notes = notes
