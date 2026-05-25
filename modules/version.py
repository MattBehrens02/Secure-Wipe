from dataclasses import dataclass
@dataclass(frozen=True)
class AppVersion:
    app_name: str = "Secure Wipe"
    app_version: str = "26.1.2" # year.major.minor
    recovery_schema_version: str = "1.1" # major.minor
    report_schema_version: str = "1.1" # major.minor