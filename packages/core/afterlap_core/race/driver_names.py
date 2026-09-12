from __future__ import annotations

from ..rng import StreamRegistry

CHAMPION_NAMES = (
    "Lewis Hamilton",
    "Michael Schumacher",
    "Juan Manuel Fangio",
    "Alain Prost",
    "Sebastian Vettel",
    "Max Verstappen",
    "Ayrton Senna",
    "Niki Lauda",
    "Jackie Stewart",
    "Nelson Piquet",
    "Jack Brabham",
    "Jim Clark",
    "Graham Hill",
    "Emerson Fittipaldi",
    "Mika Häkkinen",
    "Fernando Alonso",
    "Alberto Ascari",
    "Nigel Mansell",
    "Damon Hill",
    "Jacques Villeneuve",
    "Kimi Räikkönen",
    "Jenson Button",
    "Nico Rosberg",
    "Keke Rosberg",
    "Mario Andretti",
    "James Hunt",
    "John Surtees",
    "Denny Hulme",
    "Alan Jones",
    "Jody Scheckter",
    "Jochen Rindt",
)


def driver_names(seed: int, car_ids: tuple[str, ...]) -> dict[str, str]:
    names = StreamRegistry(seed).stream("cosmetic:driver-labels").permutation(CHAMPION_NAMES)
    return {car_id: str(name) for car_id, name in zip(car_ids, names, strict=False)}
