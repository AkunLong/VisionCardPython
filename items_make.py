import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Set

from openai import OpenAI
from app.config import settings


DEFAULT_CATEGORY = "animal"
BASE_DIR = Path(f"data/{DEFAULT_CATEGORY}")
SORT_FILE = BASE_DIR / "index.json"
TAGS_FILE = BASE_DIR / "tags.json"
ITEMS_DIR = BASE_DIR / "items"
EXAMPLE_FILE = ITEMS_DIR / "example.json"


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_tag_ids(tags_data: Any) -> Set[str]:
    """
    支持两种 tags.json 结构：
    1. 数组结构: [{"id": "color_red", ...}]
    2. 对象结构: {"tags": [{"id": "color_red", ...}]}
    """
    if isinstance(tags_data, list):
        tags = tags_data
    elif isinstance(tags_data, dict) and isinstance(tags_data.get("tags"), list):
        tags = tags_data["tags"]
    else:
        raise ValueError("tags.json 格式不符合预期，需要是数组，或者包含 tags 数组的对象。")

    tag_ids = set()

    for tag in tags:
        tag_id = tag.get("id")
        if tag_id:
            tag_ids.add(tag_id)

    if not tag_ids:
        raise ValueError("tags.json 里没有找到任何 tag id。")

    return tag_ids


def extract_sort_items(sort_data: Dict[str, Any]) -> List[Dict[str, str]]:
    items = sort_data.get("items")

    if not isinstance(items, list):
        raise ValueError("index.json 必须包含 items 数组。")

    result = []

    for item in items:
        item_id = item.get("id")
        name = item.get("name")

        if not item_id or not name:
            raise ValueError(f"index.json 中存在缺少 id 或 name 的项目: {item}")

        result.append({
            "id": item_id,
            "name": name
        })

    return result


def filename_from_item_id(item_id: str) -> str:
    return f"{item_id}.json"


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """
    尽量从模型返回中提取 JSON。
    要求模型只返回 JSON，但这里做一层容错。
    """
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("模型返回内容中没有找到 JSON 对象。")

    return json.loads(match.group(0))


def validate_item(data: Dict[str, Any], item_id: str, zh_name: str, allowed_tag_ids: Set[str]) -> None:
    """
    做必要校验：
    1. id 必须和 index.json 一致
    2. tags 只能来自 tags.json
    3. 必要字段不能缺
    """
    if data.get("id") != item_id:
        raise ValueError(f"id 不一致，期望 {item_id}，实际 {data.get('id')}")

    if "content" not in data:
        raise ValueError("缺少 content 字段。")

    if "zh-CN" not in data["content"]:
        raise ValueError("缺少 content.zh-CN 字段。")

    if "en" not in data["content"]:
        raise ValueError("缺少 content.en 字段。")

    if data["content"]["zh-CN"].get("name") != zh_name:
        raise ValueError(
            f"中文 name 不一致，期望 {zh_name}，实际 {data['content']['zh-CN'].get('name')}"
        )

    tags = data.get("tags", {})
    primary = tags.get("primary", [])
    secondary = tags.get("secondary", [])

    if not isinstance(primary, list) or not isinstance(secondary, list):
        raise ValueError("tags.primary 和 tags.secondary 必须是数组。")

    used_tags = set(primary + secondary)
    invalid_tags = used_tags - allowed_tag_ids

    if invalid_tags:
        raise ValueError(f"发现 tags.json 之外的标签: {sorted(invalid_tags)}")

    if len(primary) != 3:
        raise ValueError(f"tags.primary 建议固定 3 个，实际为 {len(primary)} 个。")

    required_paths = [
        ("sku_id", data.get("sku_id")),
        ("age_range.min", data.get("age_range", {}).get("min")),
        ("age_range.max", data.get("age_range", {}).get("max")),
        ("difficulty", data.get("difficulty")),
        ("media", data.get("media")),
        ("attributes", data.get("attributes")),
        ("content.zh-CN.intro", data["content"]["zh-CN"].get("intro")),
        ("content.zh-CN.story.title", data["content"]["zh-CN"].get("story", {}).get("title")),
        ("content.zh-CN.story.body", data["content"]["zh-CN"].get("story", {}).get("body")),
        ("content.zh-CN.knowledge.title", data["content"]["zh-CN"].get("knowledge", {}).get("title")),
        ("content.zh-CN.knowledge.body", data["content"]["zh-CN"].get("knowledge", {}).get("body")),
        ("content.en.name", data["content"]["en"].get("name")),
        ("content.en.intro", data["content"]["en"].get("intro")),
        ("content.en.story.title", data["content"]["en"].get("story", {}).get("title")),
        ("content.en.story.body", data["content"]["en"].get("story", {}).get("body")),
        ("content.en.knowledge.title", data["content"]["en"].get("knowledge", {}).get("title")),
        ("content.en.knowledge.body", data["content"]["en"].get("knowledge", {}).get("body")),
    ]

    missing = [name for name, value in required_paths if value in [None, "", [], {}]]

    if missing:
        raise ValueError(f"缺少必要内容: {missing}")


def build_prompt(
    example_item: Dict[str, Any],
    allowed_tag_ids: List[str],
    item_id: str,
    zh_name: str,
    category: str = "animal"
) -> List[Dict[str, str]]:
    system_prompt = f"""
    你是一名儿童认知卡内容数据生成助手，负责为 3-6 岁儿童生成{category}认知卡 JSON。

    你必须严格遵守：
    1. 只输出一个合法 JSON 对象，不要输出 Markdown，不要解释。
    2. JSON 字段结构必须严格参考 example，不要新增字段，不要删除字段，不要改字段名。
    3. id 必须使用用户指定的 id。
    4. sku_id 使用 card_{category}_英文语义名，例如 fruit_apple 对应 card_{category}_apple。
    5. category 固定为 {category}。
    6. media 里的图片地址全部保持空字符串。
    7. content.zh-CN.audio_url 和 content.en.audio_url 里的 intro/story 保持空字符串。
    8. tags.primary 固定 3 个标签。
    9. tags.secondary 固定 3 个标签。
    10. 所有 tag 必须来自 allowed_tag_ids，不允许编造标签。
    11. 内容面向 3-6 岁儿童，中文要简单、温暖、有画面感。
    12. 英文要简单自然，适合儿童启蒙，不要使用太复杂的词。
    13. story.body 不要太短，中文约 150-230 字，英文约 90-150 词。
    14. knowledge.body 简短准确，中文约 50-90 字，英文约 30-70 词。
    15. zh-CN.words 填英文小写单词，例如 apple。
    16. en.words 保持空字符串。

    参考：{example_item}
    """.strip()

    user_prompt = {
        "task": "请根据 example 的字段结构，为指定水果生成完整 JSON。",
        "target": {
            "id": item_id,
            "zh_name": zh_name
        },
        "allowed_tag_ids": allowed_tag_ids,
        "example": example_item
    }

    return [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": json.dumps(user_prompt, ensure_ascii=False, indent=2)
        }
    ]


def call_deepseek(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.4
) -> Dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"}
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("模型返回为空。")

    return extract_json_from_text(content)


def generate_one_item(
    client: OpenAI,
    model: str,
    example_item: Dict[str, Any],
    allowed_tag_ids: Set[str],
    item_id: str,
    zh_name: str,
    category: str = "animal",
    max_retries: int = 3
) -> Dict[str, Any]:
    allowed_tag_ids_list = sorted(allowed_tag_ids)
    messages = build_prompt(example_item, allowed_tag_ids_list, item_id, zh_name, category)

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            data = call_deepseek(client, model, messages)
            validate_item(data, item_id, zh_name, allowed_tag_ids)
            return data

        except Exception as e:
            last_error = e
            print(f"  第 {attempt} 次生成失败: {e}")

            repair_prompt = f"""
            上一次输出不符合要求，错误是：
            {str(e)}
            
            请重新输出完整合法 JSON。
            注意：
            1. 只输出 JSON。
            2. id 必须是 {item_id}。
            3. 中文 name 必须是 {zh_name}。
            4. 所有 tags 必须来自 allowed_tag_ids。
            5. 不要新增字段，不要删除字段。
            """.strip()

            messages.append({
                "role": "assistant",
                "content": "上一版 JSON 未通过校验。"
            })
            messages.append({
                "role": "user",
                "content": repair_prompt
            })

            time.sleep(1.5)

    raise RuntimeError(f"{zh_name} 生成失败，已重试 {max_retries} 次。最后错误: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="品类名称，如 animal, fruit, flower 等")
    parser.add_argument("--model", default="deepseek-v4-pro", help="DeepSeek 模型名，例如 deepseek-v4-pro 或 deepseek-v4-flash")
    parser.add_argument("--overwrite", action="store_true", help="是否覆盖已存在的水果 JSON")
    parser.add_argument("--start", type=int, default=0, help="从 index.json 的第几个开始，0 表示从头开始")
    parser.add_argument("--limit", type=int, default=0, help="最多生成几个，0 表示不限制")
    args = parser.parse_args()

    category = args.category
    base_dir = Path(f"data/{category}")
    sort_file = base_dir / "index.json"
    tags_file = base_dir / "tags.json"
    items_dir = base_dir / "items"
    example_file = items_dir / "example.json"

    api_key = settings.DEEPSEEK_API_KEY

    if not api_key:
        raise EnvironmentError("请先设置环境变量 DEEPSEEK_API_KEY。")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com"
    )

    sort_data = load_json(sort_file)
    tags_data = load_json(tags_file)
    example_item = load_json(example_file)

    sort_items = extract_sort_items(sort_data)
    allowed_tag_ids = extract_tag_ids(tags_data)

    if args.start > 0:
        sort_items = sort_items[args.start:]

    if args.limit > 0:
        sort_items = sort_items[:args.limit]

    print(f"准备生成 {len(sort_items)} 个item JSON。")
    print(f"使用模型: {args.model}")
    print(f"允许标签数量: {len(allowed_tag_ids)}")

    failed_items = []

    for index, item in enumerate(sort_items, start=1):
        item_id = item["id"]
        zh_name = item["name"]
        output_file = items_dir / filename_from_item_id(item_id)

        if output_file.exists() and not args.overwrite:
            print(f"[{index}/{len(sort_items)}] 跳过已存在: {zh_name} -> {output_file}")
            continue

        print(f"[{index}/{len(sort_items)}] 正在生成: {zh_name} -> {output_file}")

        try:
            generated = generate_one_item(
                client=client,
                model=args.model,
                example_item=example_item,
                allowed_tag_ids=allowed_tag_ids,
                item_id=item_id,
                zh_name=zh_name,
                category=category
            )
            print(generated)
            save_json(output_file, generated)
            print(f"  已保存: {output_file}")
        except Exception as e:
            print(f"  ❌ 生成失败: {zh_name} ({item_id}) — {e}")
            failed_items.append({"id": item_id, "name": zh_name, "error": str(e)})

        time.sleep(1.0)

    if failed_items:
        print(f"\n⚠️  {len(failed_items)} 个 item 生成失败:")
        for fi in failed_items:
            print(f"  - {fi['name']} ({fi['id']}): {fi['error']}")
    else:
        print("\n✅ 全部处理完成，无失败。")


if __name__ == "__main__":
    main()