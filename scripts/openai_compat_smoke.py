from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

import httpx
from openai import OpenAI

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin123456"
DEFAULT_MODEL = "nxb"
DEFAULT_PROMPT = "你好，介绍一下自己"
DEFAULT_STATIC_API_KEY_EXAMPLE = (
    "xV2HhwW6CqkmjyTZ1KfRG3oO1dUL2bv3oYcwLNO7v2RT73d5GX4_JvbvSFZUeIhM"
)


@dataclass(frozen=True)
class SmokeResult:
    message: str
    response_id: str
    autoagent_status: str | None
    raw_response: Any


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def login(*, base_url: str, username: str, password: str, timeout: float = 30.0) -> str:
    response = httpx.post(
        _join_url(base_url, "/api/v1/auth/login"),
        json={"username": username, "password": password},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"login response missing token: {data!r}")
    return token


def run_chat_completion(
    *,
    base_url: str,
    username: str,
    password: str,
    api_key: str | None,
    model: str,
    prompt: str,
    new_session: bool,
    timeout_sec: int | None,
    retry: int | None,
    dry_run: bool,
) -> SmokeResult:
    client = OpenAI(
        base_url=_join_url(base_url, "/v1"),
        api_key=api_key or login(base_url=base_url, username=username, password=password),
    )

    extra_body: dict[str, Any] = {
        "new_session": new_session,
        "dry_run": dry_run,
    }
    if timeout_sec is not None:
        extra_body["timeout_sec"] = timeout_sec
    if retry is not None:
        extra_body["retry"] = retry

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        extra_body=extra_body,
    )

    message = response.choices[0].message.content or ""
    x_autoagent = getattr(response, "x_autoagent", None)
    autoagent_status = getattr(x_autoagent, "status", None) if x_autoagent is not None else None
    return SmokeResult(
        message=message,
        response_id=response.id,
        autoagent_status=autoagent_status,
        raw_response=response,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test the OpenAI-compatible /v1/chat/completions endpoint.",
        epilog=(
            "Examples:\n"
            "  python3.11 scripts/openai_compat_smoke.py --password 'your-admin-password'\n"
            "  python3.11 scripts/openai_compat_smoke.py "
            f"--api-key '{DEFAULT_STATIC_API_KEY_EXAMPLE}'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--api-key",
        default=None,
        help="Use a preconfigured Bearer key directly and skip /api/v1/auth/login",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="AutoAgent target_profile name")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Set OpenAI extra_body.new_session=true",
    )
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--retry", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the full raw OpenAI response JSON when available.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_chat_completion(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        api_key=args.api_key,
        model=args.model,
        prompt=args.prompt,
        new_session=args.new_session,
        timeout_sec=args.timeout_sec,
        retry=args.retry,
        dry_run=args.dry_run,
    )
    print(f"response_id: {result.response_id}")
    if result.autoagent_status is not None:
        print(f"autoagent_status: {result.autoagent_status}")
    print("message:")
    print(result.message)

    if args.print_json:
        raw = result.raw_response
        if hasattr(raw, "model_dump"):
            print(json.dumps(raw.model_dump(), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(raw, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
