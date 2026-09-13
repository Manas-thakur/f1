from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from afterlap_core.race import RaceSettings, RacingLineSettings, StorylineSettings
from afterlap_core.race.circuit import catalogue
from afterlap_core.race.control import DriverControl
from afterlap_core.race.decision import decision_schema
from afterlap_core.race.diversity import apply_command_diversity
from afterlap_core.race.environment import (
    ACTION_FIELDS,
    ACTION_HIGH,
    ACTION_LOW,
    PROFILES,
    RaceEnv,
    encode_control,
)
from afterlap_core.race.policy import load_policy, policy_manifest
from afterlap_core.race.variability import Variability


def configure_runtime_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    logging.basicConfig(
        level=os.environ.get("RACE_LOG_LEVEL", "INFO").upper(),
        handlers=[console, file_handler],
        force=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic race generator and local WebSocket runtime")
    parser.add_argument(
        "command",
        choices=(
            "serve",
            "generate",
            "train",
            "evaluate",
            "train-decision",
            "evaluate-decision",
            "catalogue",
            "schema",
        ),
    )
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--preset", choices=("baseline", "mild", "training", "stress"), default="mild")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--driver-action", type=Path)
    parser.add_argument("--profile", choices=[p.value for p in PROFILES], default="neutral")
    parser.add_argument("--circuit", default="silverstone")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cars", type=int, default=20)
    parser.add_argument("--laps", type=int)
    parser.add_argument("--dt", type=float, default=0.01)
    parser.add_argument("--duration", type=float, default=1800)
    parser.add_argument("--wetness", type=float, default=0)
    parser.add_argument("--weather", choices=("sunny", "rainy"), default="sunny")
    parser.add_argument("--temperature-k", type=float, default=303.15)
    parser.add_argument("--wind-mps", type=float, default=0)
    parser.add_argument("--wake", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--contact-mode", choices=("ignore", "terminate"), default="ignore")
    parser.add_argument("--storylines", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--pit-stops", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--tyre-wear-scale", type=float, default=1)
    parser.add_argument("--racing-line", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--corner-line-strength", type=float, default=0.9)
    parser.add_argument("--line-randomness", type=float, default=0.7)
    parser.add_argument("--line-wander-m", type=float, default=0.8)
    parser.add_argument("--line-lookahead-m", type=float, default=65)
    parser.add_argument("--line-smoothing-m", type=float, default=30)
    parser.add_argument("--corner-overtakes", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--steps", type=int, default=10000)
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--eval-episodes", type=int, default=3)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--diversity", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--control-state", type=Path, default=Path(".afterlap/race/control.sqlite3"))
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(os.environ.get("RACE_LOG_FILE", ".afterlap/race/runtime.log")),
    )
    parser.add_argument("--output", type=Path, default=Path(".afterlap/race/transitions.jsonl"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18761)
    parser.add_argument("--origin", default="http://127.0.0.1:18760")
    args = parser.parse_args()
    if args.command == "catalogue":
        print(json.dumps({"circuits": catalogue()}, indent=2))
        return
    if args.command == "schema":
        print(
            json.dumps(
                {
                    "race_settings": RaceSettings.model_json_schema(),
                    "driver_control": DriverControl.model_json_schema(),
                    "rl_action": {
                        "fields": ACTION_FIELDS,
                        "low": ACTION_LOW.tolist(),
                        "high": ACTION_HIGH.tolist(),
                    },
                    "boost_decision": decision_schema(),
                },
                indent=2,
            )
        )
        return
    if args.driver_action and args.command != "evaluate":
        parser.error("--driver-action is only valid for evaluate")
    if args.driver_action and args.policy:
        parser.error("--driver-action and --policy are mutually exclusive")
    settings_payload = {
        "circuit": args.circuit,
        "seed": args.seed,
        "cars": args.cars,
        "dt_s": args.dt,
        "time_limit_s": args.duration,
        "wetness": args.wetness,
        "weather": args.weather,
        "temperature_k": args.temperature_k,
        "wind_mps": args.wind_mps,
        "wake": args.wake,
        "contact_mode": args.contact_mode,
        "variability": Variability(preset=args.preset),
        "storyline": StorylineSettings(
            enabled=args.storylines,
            pit_stops=args.pit_stops,
            tyre_wear_scale=args.tyre_wear_scale,
        ),
        "racing_line": RacingLineSettings(
            enabled=args.racing_line,
            corner_strength=args.corner_line_strength,
            randomness=args.line_randomness,
            wander_m=args.line_wander_m,
            lookahead_m=args.line_lookahead_m,
            smoothing_m=args.line_smoothing_m,
            overtake_in_corners=args.corner_overtakes,
        ),
    }
    if args.laps is not None:
        settings_payload["laps"] = args.laps
    settings = RaceSettings.model_validate(settings_payload)
    if args.settings:
        settings = RaceSettings.model_validate_json(args.settings.read_text())
    settings = apply_command_diversity(
        settings,
        args.diversity,
        default_enabled=args.command in {"train", "train-decision", "evaluate-decision"},
    )
    if args.command == "serve":
        from afterlap_api.race_server import run_server

        configure_runtime_logging(args.log_file)
        logging.getLogger("afterlap.race.control").info(
            json.dumps(
                {
                    "event": "race_server_starting",
                    "host": args.host,
                    "port": args.port,
                    "log_file": str(args.log_file.resolve()),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        print(f"race websocket: ws://{args.host}:{args.port}", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(
                run_server(
                    args.host,
                    args.port,
                    args.origin,
                    settings=settings,
                    policy_path=args.policy,
                    metrics_path=args.metrics,
                    control_state_path=args.control_state,
                )
            )
        return
    if args.command == "train-decision":
        from afterlap_core.race.training import train_decision_policy

        metrics = train_decision_policy(
            settings,
            args.output,
            args.steps,
            args.cycles,
            args.eval_episodes,
            args.learning_rate,
        )
        print(json.dumps(metrics, allow_nan=False))
        return
    if args.command == "evaluate-decision":
        if args.policy is None:
            parser.error("evaluate-decision requires --policy")
        from afterlap_core.race.decision import BoostDecisionEngine
        from afterlap_core.race.training import evaluate_decision_policy

        engine = BoostDecisionEngine(args.policy)
        metrics = evaluate_decision_policy(engine.model, settings, args.eval_episodes)
        print(json.dumps({"type": "boost_evaluation", **metrics}, allow_nan=False))
        return
    env = RaceEnv(settings)
    if args.command == "train":
        from stable_baselines3 import PPO
        from stable_baselines3.common.env_checker import check_env
        from stable_baselines3.common.monitor import Monitor

        check_env(env)
        model = PPO(
            "MlpPolicy",
            Monitor(env),
            seed=settings.seed,
            n_steps=128,
            batch_size=64,
            verbose=1,
            gamma=0.996672,
            device="cpu",
        )
        model.learn(total_timesteps=args.steps)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(args.output))
        assert env.session is not None
        args.output.with_suffix(".manifest.json").write_text(
            json.dumps(policy_manifest(env.session), indent=2)
        )
        print(json.dumps({"status": "training_completed", "output": str(args.output), "promoted": False}))
        return
    observation, _ = env.reset(seed=settings.seed)
    assert env.session is not None
    if args.command == "evaluate":
        policy = load_policy(args.policy, env.session) if args.policy else None
        fixed = (
            DriverControl.model_validate_json(args.driver_action.read_text())
            if args.driver_action
            else DriverControl(mode="automatic", profile=args.profile)
        )
        total_reward = 0.0
        while True:
            action = policy.predict(observation, deterministic=True)[0] if policy else encode_control(fixed)
            observation, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            if terminated or truncated:
                print(
                    json.dumps(
                        {"seed": settings.seed, "status": env.session.status, "reward": total_reward, **info},
                        allow_nan=False,
                    )
                )
                return
    env.action_space.seed(settings.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(policy_manifest(env.session)) + "\n")
        while True:
            action = env.action_space.sample()
            next_observation, reward, terminated, truncated, info = env.step(action)
            output.write(
                json.dumps(
                    {
                        "type": "transition",
                        "observation": observation.tolist(),
                        "action": action.tolist(),
                        "reward": reward,
                        "next_observation": next_observation.tolist(),
                        "terminated": terminated,
                        "truncated": truncated,
                        "info": info,
                    },
                    allow_nan=False,
                )
                + "\n"
            )
            observation = next_observation
            if terminated or truncated:
                print(json.dumps({"output": str(args.output), "status": env.session.status, **info}))
                break


if __name__ == "__main__":
    main()
