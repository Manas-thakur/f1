from enum import StrEnum


class Provenance(StrEnum):
    MEASURED = "measured"
    ESTIMATED = "estimated"
    CONFIGURED = "configured"
    SIMULATED = "simulated"


class Quality(StrEnum):
    VALID = "valid"
    DEGRADED = "degraded"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"


class FlagState(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    DOUBLE_YELLOW = "double_yellow"
    SAFETY_CAR = "safety_car"
    VIRTUAL_SAFETY_CAR = "virtual_safety_car"
    RED = "red"
    CHEQUERED = "chequered"
    UNKNOWN = "unknown"


class DeploymentProfile(StrEnum):
    HARVEST = "harvest"
    CONSERVE = "conserve"
    NEUTRAL = "neutral"
    PUSH = "push"
    OVERTAKE = "overtake"
