from __future__ import annotations

import os

from dotenv import load_dotenv


def present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def main() -> None:
    load_dotenv()
    checks = {
        "STEPFUN_API_KEY": present("STEPFUN_API_KEY"),
        "STEPFUN_IMAGE_API_KEY": present("STEPFUN_IMAGE_API_KEY") or present("STEPFUN_API_KEY"),
        "STEPFUN_VISION_API_KEY": present("STEPFUN_VISION_API_KEY") or present("STEPFUN_API_KEY"),
        "POSTGRES_DSN": present("POSTGRES_DSN"),
        "LLM_MOCK_false": os.getenv("LLM_MOCK", "").lower() == "false",
        "IMAGE_MOCK_false": os.getenv("IMAGE_MOCK", "").lower() == "false",
        "VISION_REVIEW_MOCK_false": os.getenv("VISION_REVIEW_MOCK", "").lower() == "false",
        "CHECKPOINTER_MOCK_false": os.getenv("CHECKPOINTER_MOCK", "").lower() == "false",
    }
    for name, ok in checks.items():
        print(f"{name}: {'OK' if ok else 'MISSING_OR_DISABLED'}")
    if all(checks.values()):
        print("REAL_MODE_READY")
    else:
        print("REAL_MODE_NOT_READY")


if __name__ == "__main__":
    main()
