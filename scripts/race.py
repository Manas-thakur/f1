from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from pathlib import Path

from afterlap_core.race import RaceSettings
from afterlap_core.race.environment import PROFILES, RaceEnv
from afterlap_core.race.policy import load_policy, policy_manifest
from afterlap_core.race.variability import Variability


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic race generator and local WebSocket runtime")
    parser.add_argument("command", choices=("serve", "generate", "train", "evaluate"))
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--preset", choices=("baseline", "mild", "training", "stress"), default="mild")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--profile", choices=[p.value for p in PROFILES], default="neutral")
    parser.add_argument("--circuit", default="silverstone")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cars", type=int, default=20)
    parser.add_argument("--laps", type=int, default=3)
    parser.add_argument("--duration", type=float, default=1800)
    parser.add_argument("--wetness", type=float, default=0)
    parser.add_argument("--steps", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=Path(".afterlap/race/transitions.jsonl"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18761)
    parser.add_argument("--origin", default="http://127.0.0.1:18760")
    args = parser.parse_args()
    if args.command == "serve":
        from afterlap_api.race_server import run_server

        print(f"race websocket: ws://{args.host}:{args.port}", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run_server(args.host, args.port, args.origin))
        return
    settings = RaceSettings(
        circuit=args.circuit,
        seed=args.seed,
        cars=args.cars,
        laps=args.laps,
        time_limit_s=args.duration,
        wetness=args.wetness,
        variability=Variability(preset=args.preset),
    )
    if args.settings:
        settings = RaceSettings.model_validate_json(args.settings.read_text())
    env = RaceEnv(settings)
    if args.command == "train":
        from stable_baselines3 import PPO
        from stable_baselines3.common.env_checker import check_env
        from stable_baselines3.common.monitor import Monitor

        check_env(env)
        model = PPO(
            "MlpPolicy",
            Monitor(env),
            seed=args.seed,
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
    observation, _ = env.reset(seed=args.seed)
    assert env.session is not None
    if args.command == "evaluate":
        policy = load_policy(args.policy, env.session) if args.policy else None
        total_reward = 0.0
        while True:
            action = (
                int(policy.predict(observation, deterministic=True)[0])
                if policy
                else next(index for index, profile in enumerate(PROFILES) if profile.value == args.profile)
            )
            observation, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            if terminated or truncated:
                print(
                    json.dumps(
                        {"seed": args.seed, "status": env.session.status, "reward": total_reward, **info},
                        allow_nan=False,
                    )
                )
                return
    env.action_space.seed(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(policy_manifest(env.session)) + "\n")
        while True:
            action = int(env.action_space.sample())
            next_observation, reward, terminated, truncated, info = env.step(action)
            output.write(
                json.dumps(
                    {
                        "type": "transition",
                        "observation": observation.tolist(),
                        "action": action,
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
