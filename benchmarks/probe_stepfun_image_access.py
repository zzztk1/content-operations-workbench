import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    api_key = os.getenv("STEPFUN_IMAGE_API_KEY") or os.getenv("STEPFUN_API_KEY", "")
    base_url = os.getenv("STEPFUN_IMAGE_API_BASE", "https://api.stepfun.com/v1")
    model = os.getenv("STEPFUN_IMAGE_MODEL", "step-2x-large")
    client = OpenAI(api_key=api_key, base_url=base_url)

    result = {
        "generated_at": utc_now(),
        "api_base": base_url,
        "model": model,
        "ok": False,
    }
    try:
        response = client.images.generate(
            model=model,
            prompt="为一篇关于信息过载与判断力的中文公众号文章生成封面图：深蓝背景，抽象信息洪流，一个沉思的人物剪影，留出标题区域，杂志封面风格。",
            size=os.getenv("STEPFUN_IMAGE_SIZE", "1024x1024"),
        )
        item = response.data[0] if getattr(response, "data", None) else None
        result.update(
            {
                "ok": bool(item),
                "has_url": bool(getattr(item, "url", "") if item else ""),
                "has_b64_json": bool(getattr(item, "b64_json", "") if item else ""),
                "revised_prompt": getattr(item, "revised_prompt", "") if item else "",
                "url_preview": (getattr(item, "url", "") or "")[:300],
            }
        )
    except Exception as exc:
        result["error"] = str(exc)

    out_path = os.path.join(PROJECT_ROOT, "benchmarks", "latest_stepfun_image_access_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
