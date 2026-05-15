from dataclasses import dataclass
@dataclass(frozen=True)
class AppVersion:
    app_name: str = "Secure Wipe"
    app_version: str = "26.0.2" # year.major.minor // tick to 26.1.0 for release
    recovery_schema_version: str = "1.0" # major.minor
    report_schema_version: str = "1.0" # major.minor