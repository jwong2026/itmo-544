""" Settings for the stack, read from the same .env file the bash scripts use. """
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

REQUIRED_KEYS = [
    "AWS_REGION", "AZ_A", "AZ_B", "AMI_ID", "INSTANCE_TYPE", "KEY_NAME", "APP_SECURITY_GROUP_ID",
    "WEATHER_ROLE_NAME", "WEATHER_PROFILE_NAME", "WEATHER_LT_NAME",
    "WEATHER_TG_NAME", "WEATHER_ASG_NAME", "WEATHER_LISTENER_PORT",
    "ADVISOR_ROLE_NAME", "ADVISOR_PROFILE_NAME", "ADVISOR_LT_NAME",
    "ADVISOR_TG_NAME", "ADVISOR_ASG_NAME", "ADVISOR_LISTENER_PORT",
    "ALB_NAME", "ALB_SG_NAME",
    "DB_INSTANCE_ID", "DB_NAME", "DB_USER", "DB_SG_NAME", "DB_SUBNET_GROUP_NAME", "DB_PASSWORD_PARAM",
    "GEMINI_PARAM_NAME", "GEMINI_MODEL", "CONTACT_EMAIL",
]


class ConfigError(Exception):
    """ Raised when .env is missing keys or has a bad value, with a message that says which. """


def load_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """ Read KEY=VALUE lines into a dict. Comments and blank lines are skipped. """
    values: dict[str, str] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _int(values: dict[str, str], key: str, default: int | None = None) -> int:
    """ Read an integer setting, with a message that names the key if it is not a number. """
    raw = values.get(key)
    if raw in (None, ""):
        if default is None:
            raise ConfigError(f"Missing keys in .env: {key}")
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a whole number (for example '8080'). Got: '{raw}'") from None


@dataclass(frozen=True)
class Tier:
    """ Everything that belongs to one application tier (weather or advisor). """
    name: str
    role_name: str
    profile_name: str
    lt_name: str
    tg_name: str
    asg_name: str
    listener_port: int
    app_dir: Path

    @property
    def policy_name(self) -> str:
        return f"{self.role_name}-policy"

    @property
    def service_name(self) -> str:
        return self.name


@dataclass(frozen=True)
class Settings:
    region: str
    ami_id: str
    key_name: str
    instance_type: str
    app_sg_id: str
    alb_name: str
    alb_sg_name: str
    az_a: str
    az_b: str
    weather: Tier
    advisor: Tier

    db_instance_id: str
    db_name: str
    db_user: str
    db_sg_name: str
    db_subnet_group_name: str
    db_password_param: str

    gemini_param_name: str
    gemini_model: str
    contact_email: str
    cache_seconds: int = 600
    key_cache_seconds: int = 60
    app_port: int = 3000

    @property
    def tiers(self) -> tuple[Tier, Tier]:
        return (self.weather, self.advisor)

    def tier(self, name: str) -> Tier:
        return {"weather": self.weather, "advisor": self.advisor}[name]

    def secret_param_for(self, tier: Tier) -> str:
        """ The one SSM parameter this tier may read: DB password for weather, Gemini key for advisor. """
        return {"weather": self.db_password_param, "advisor": self.gemini_param_name}[tier.name]

    @classmethod
    def from_values(cls, v: dict[str, str], base_dir: str | Path = ".") -> "Settings":
        missing = [k for k in REQUIRED_KEYS if not v.get(k)]
        if missing:
            raise ConfigError("Missing keys in .env: " + ", ".join(missing))
        if v["AZ_A"] == v["AZ_B"]:
            raise ConfigError("AZ_A and AZ_B must be different availability zones (the ALB and DB subnet group need two).")
        base = Path(base_dir)

        def tier(prefix: str) -> Tier:
            return Tier(
                name=prefix.lower(),
                role_name=v[f"{prefix}_ROLE_NAME"],
                profile_name=v[f"{prefix}_PROFILE_NAME"],
                lt_name=v[f"{prefix}_LT_NAME"],
                tg_name=v[f"{prefix}_TG_NAME"],
                asg_name=v[f"{prefix}_ASG_NAME"],
                listener_port=_int(v, f"{prefix}_LISTENER_PORT"),
                app_dir=base / f"{prefix.lower()}-app",
            )

        return cls(
            region=v["AWS_REGION"], ami_id=v["AMI_ID"], key_name=v["KEY_NAME"],
            instance_type=v["INSTANCE_TYPE"], app_sg_id=v["APP_SECURITY_GROUP_ID"],
            alb_name=v["ALB_NAME"], alb_sg_name=v["ALB_SG_NAME"], az_a=v["AZ_A"], az_b=v["AZ_B"],
            weather=tier("WEATHER"), advisor=tier("ADVISOR"),
            db_instance_id=v["DB_INSTANCE_ID"], db_name=v["DB_NAME"], db_user=v["DB_USER"],
            db_sg_name=v["DB_SG_NAME"], db_subnet_group_name=v["DB_SUBNET_GROUP_NAME"],
            db_password_param=v["DB_PASSWORD_PARAM"],
            gemini_param_name=v["GEMINI_PARAM_NAME"], gemini_model=v["GEMINI_MODEL"],
            contact_email=v["CONTACT_EMAIL"],
            cache_seconds=_int(v, "CACHE_SECONDS", 600),
            key_cache_seconds=_int(v, "KEY_CACHE_SECONDS", 60),
        )

    @classmethod
    def from_file(cls, path: str | Path = ".env") -> "Settings":
        path = Path(path)
        return cls.from_values(load_dotenv(path), base_dir=path.resolve().parent)
