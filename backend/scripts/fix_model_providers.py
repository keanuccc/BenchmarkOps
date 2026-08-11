"""修复 legacy 模型 provider：OpenRouter 风格 seed 模型路由到 openrouter。

早期 seed 模型使用 openai/anthropic/google 等 provider 名，这些名字不是平台
已知网关（mock/openrouter/qiniu），会被归一化到默认网关；在 qiniu 默认网关
下模型名不匹配导致 400（no available channels）。这些模型的 model_id 本身是
OpenRouter 风格（如 openai/gpt-4o-mini），应路由到 openrouter。

用法：
    python scripts/fix_model_providers.py            # dry-run：只打印将修改的模型
    python scripts/fix_model_providers.py --apply    # 实际修改
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
LEGACY_PROVIDERS = {"openai", "anthropic", "google", "deepseek", "qwen", "zhipu", "tencent"}


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--apply", action="store_true", help="实际修改模型 provider")
    args = parser.parse_args()
    BASE = args.base

    st, models = req("GET", "/models/")
    targets = [
        m for m in models.get("items", [])
        if m.get("provider") in LEGACY_PROVIDERS
    ]
    print(f"待修复模型: {len(targets)}")
    for m in targets:
        print(f"  {m['name']}: {m['provider']}/{m['model_id']} -> openrouter/{m['model_id']}")
    if not args.apply:
        print("dry-run 完成；加 --apply 生效")
        return
    for m in targets:
        st, _ = req("PATCH", f"/models/{m['id']}", {"provider": "openrouter"})
        print(f"  修改 {m['name']}: {st}")


if __name__ == "__main__":
    main()
