import argparse
import asyncio
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests
from PIL import Image

from app.infra.infra_provider import get_img, get_llm


DEFAULT_CATEGORY = "fruit"
BASE_DIR = Path(f"data/{DEFAULT_CATEGORY}")
ITEMS_DIR = BASE_DIR / "items"
IMAGE_DIR = BASE_DIR / "images"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_item_files(items_dir: Path) -> Iterable[Path]:
    return sorted(items_dir.glob("*.json"))


def item_slug(item_path: Path, item_data: Dict[str, Any], category: str = "fruit") -> str:
    item_id = item_data.get("id", "")
    if item_id:
        return item_id
    return item_path.stem


def get_content(item_data: Dict[str, Any], lang: str = "zh-CN") -> Optional[Dict[str, Any]]:
    content = item_data.get("content", {})
    lang_content = content.get(lang)
    return lang_content if isinstance(lang_content, dict) else None


def extract_json_from_llm_text(text: str) -> Dict[str, Any]:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```json", "", text)
        text = re.sub(r"^```", "", text)
        text = re.sub(r"```$", "", text)
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"LLM 没有返回 JSON：\n{text}")

    return json.loads(text[start:end + 1])


def normalize_image_result(result: Any) -> str:
    if isinstance(result, str):
        return result

    if isinstance(result, list):
        if not result:
            raise RuntimeError("图片接口返回空 list")
        first = result[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for key in ["url", "image_url", "oss_url"]:
                if first.get(key):
                    return first[key]

    if isinstance(result, dict):
        for key in ["url", "image_url", "oss_url"]:
            if result.get(key):
                return result[key]
        if isinstance(result.get("urls"), list) and result["urls"]:
            return result["urls"][0]

    raise TypeError(f"无法识别图片接口返回格式: {type(result)} / {result}")


async def generate_image_prompts_by_llm(
    item_data: Dict[str, Any],
    model: str = "qwen-plus-stream-false",
) -> Dict[str, str]:
    zh = item_data.get("content", {}).get("zh-CN", {}) or {}
    en = item_data.get("content", {}).get("en", {}) or {}

    compact_item = {
        "id": item_data.get("id"),
        "category": item_data.get("category"),
        "audio": item_data.get("audio", {}),
        "attributes": item_data.get("attributes", {}),
        "zh": {
            "name": zh.get("name"),
            "intro": zh.get("intro"),
            "story": zh.get("story", {}),
            "knowledge": zh.get("knowledge", {}),
        },
        "en": {
            "name": en.get("name"),
            "intro": en.get("intro"),
            "story": en.get("story", {}),
            "knowledge": en.get("knowledge", {}),
        },
    }

    system_prompt = """
    你是儿童早教产品的图片提示词专家。

    你的任务是：根据输入的 item，生成 3 条中文图片生成提示词。
    这些提示词将用于批量生成儿童识物卡片图片，要求风格稳定、统一、可规模化生产。

    请严格输出 JSON，不要输出 Markdown，不要解释。

    JSON 格式：
    {
      "main_image": "...",
      "story_image": "...",
      "knowledge_image": "..."
    }

    ====================
    【核心要求：稳定、统一、可控】
    ====================

    所有图片必须：
    - 风格统一
    - 光线一致
    - 构图一致
    - 适合批量生成上百张图片

    不要使用否定表达（如：不要、无、避免等），必须用正向描述来表达效果。

    --------------------
    1. main_image（最重要：认知主图）
    --------------------

    这是儿童识物卡片主图，必须接近电商白底商品图。

    要求：

    【主体】
    - 单个主体
    - 主体完整
    - 居中构图，占画面约80%
    - 正面或轻微自然角度
    - 主体颜色不要是白色
    - 主体的颜色尽量要鲜艳，用红橙黄绿青蓝紫
    - 颜色鲜艳丰富

    【背景】
    - 纯白色背景
    - 背景亮度一致，整体干净通透

    【光线（重点）】
    - 整体画面明亮、通透
    - 光线从多个方向均匀照亮主体

    【质感】
    - 真实摄影风格（photorealistic）
    - 材质真实自然（适当表现物体表面质感，如光滑、柔软、粗糙等）
    - 高光为柔和均匀反射，不是强烈高光点
    - 细节清晰但不过度锐化

    【整体风格】
    - 类似电商白底商品图
    - 主体边缘清晰自然

    【禁止内容（用正向规避）】
    - 画面中只包含主体本身

    --------------------
    2. story_image（绘本插画）
    --------------------

    这是故事模块图片，必须接近儿童绘本风格。

    要求：

    【风格】
    - 儿童绘本插画风格（hand-painted illustration）
    - 温暖、柔和、明亮
    - 类似经典童话绘本（安徒生风格）

    【角色】
    - 可以包含动物角色（如小兔子、小熊等）
    - 角色可爱、友好、安全
    - Q版比例（大头小身体），圆润

    【场景】
    - 根据故事内容，提炼一个最有画面感的瞬间
    - 场景具体（如花园、野餐、森林、街道等）
    - 构图饱满但不拥挤

    【光线】
    - 柔和自然光（soft daylight）
    - 画面明亮，色彩温暖
    - 对比度适中偏低

    【质感】
    - 手绘质感明显
    - 色彩柔和统一
    - 不呈现3D渲染质感

    --------------------
    3. knowledge_image（真实科普图）
    --------------------

    这是“有趣小知识”模块图片，必须为真实世界摄影。

    要求：

    【内容】
    - 根据 knowledge 内容选择最合适场景
    - 例如：自然环境、生活场景、室内、户外等

    【风格】
    - 真实摄影风格
    - 自然光（natural daylight）
    - 清晰、自然、有生活感

    【画面】
    - 构图简洁
    - 主体明确
    - 颜色真实不过度增强

    --------------------
    【通用要求】
    --------------------

    - 正方形构图（1:1）
    - 高分辨率
    - 画面干净
    - 主体明确
    - 不出现任何文字

    ====================
    【重要约束】
    ====================

    - 不要生成英文提示词
    - 每条提示词必须完整具体
    - 风格必须稳定，不能随机变化
    - 优先保证 main_image 风格绝对一致

    """

    user_prompt = f"""
请根据下面 item 生成图片提示词：

{json.dumps(compact_item, ensure_ascii=False, indent=2)}
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = await get_llm(model=model).chat_completion(messages=messages)
    content = result["choices"][0]["message"]["content"].strip()

    prompts = extract_json_from_llm_text(content)

    for key in ["main_image", "story_image", "knowledge_image"]:
        if key not in prompts or not isinstance(prompts[key], str) or not prompts[key].strip():
            raise ValueError(f"LLM 返回缺少字段 {key}：\n{content}")

    return {
        "main_image": prompts["main_image"].strip(),
        "story_image": prompts["story_image"].strip(),
        "knowledge_image": prompts["knowledge_image"].strip(),
    }


def save_prompt(path: Path, prompt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")


def download_image_as_jpeg(url: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    image = Image.open(BytesIO(response.content))

    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        background.paste(image, mask=image.split()[-1] if image.mode in ("RGBA", "LA") else None)
        image = background
    else:
        image = image.convert("RGB")

    image.save(output_path, format="JPEG", quality=95, optimize=True)


async def generate_image_with_retry(
    prompt: str,
    w: int,
    h: int,
    max_retries: int = 3,
    sleep_seconds: float = 2.0,
) -> str:
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            result = await get_img().generate_image(prompt=prompt, w=w, h=h)
            url = normalize_image_result(result)

            if not url:
                raise RuntimeError("图片接口没有返回 url")

            return url

        except Exception as e:
            last_error = e
            print(f"    第 {attempt} 次生成失败: {e}")
            await asyncio.sleep(sleep_seconds)

    raise RuntimeError(f"图片生成失败，最后错误: {last_error}")


async def process_item(
    item_path: Path,
    image_dir: Path,
    overwrite: bool,
    llm_model: str,
    w: int,
    h: int,
    sleep_seconds: float,
    task_type: str = "all",
    category: str = "fruit",
) -> None:
    item_data = load_json(item_path)
    slug = item_slug(item_path, item_data, category)

    zh = get_content(item_data, "zh-CN") or {}
    name = zh.get("name", slug)

    print(f"\n处理: {item_path.name} / {name}")

    prompt_json_path = image_dir / "prompts" / f"{slug}_prompts.json"

    tasks = [
        {
            "type": "main",
            "prompt_key": "main_image",
            "image_file": f"{slug}_main.jpg",
            "prompt_file": f"{slug}_main_prompt.txt",
        },
        {
            "type": "story",
            "prompt_key": "story_image",
            "image_file": f"{slug}_story.jpg",
            "prompt_file": f"{slug}_story_prompt.txt",
        },
        {
            "type": "knowledge",
            "prompt_key": "knowledge_image",
            "image_file": f"{slug}_knowledge.jpg",
            "prompt_file": f"{slug}_knowledge_prompt.txt",
        },
    ]

    # 收集需要 LLM 生成的 prompt（txt 不存在的才需要）
    need_llm_keys = set()
    for task in tasks:
        image_type = task["type"]
        if task_type != "all":
            mapped = task_type if task_type != "fact" else "knowledge"
            if image_type != mapped:
                continue
        prompt_path = image_dir / image_type / task["prompt_file"]
        if not prompt_path.exists() or overwrite:
            need_llm_keys.add(task["prompt_key"])

    prompts = {}
    if need_llm_keys:
        if prompt_json_path.exists() and not overwrite:
            prompts = json.loads(prompt_json_path.read_text(encoding="utf-8"))
            print(f"  使用已缓存 prompts.json: {prompt_json_path}")
        else:
            print("  正在调用 LLM 生成图片 prompts...")
            prompts = await generate_image_prompts_by_llm(item_data=item_data, model=llm_model)
            prompt_json_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_json_path.write_text(
                json.dumps(prompts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  已保存 prompts.json: {prompt_json_path}")

    for task in tasks:
        image_type = task["type"]
        if task_type != "all":
            mapped = task_type if task_type != "fact" else "knowledge"
            if image_type != mapped:
                continue

        image_path = image_dir / image_type / task["image_file"]
        prompt_path = image_dir / image_type / task["prompt_file"]

        if image_path.exists() and not overwrite:
            print(f"  跳过 {image_type}: 图片已存在 {image_path}")
            continue

        # txt 是缓存/数据源，优先从 txt 读取
        if prompt_path.exists() and not overwrite:
            prompt = prompt_path.read_text(encoding="utf-8").strip()
            print(f"  使用 prompt.txt 缓存: {prompt_path}")
        else:
            prompt = prompts[task["prompt_key"]]
            save_prompt(prompt_path, prompt)

        print(f"  生成 {image_type}: {image_path}")
        print(f"    prompt 长度: {len(prompt)}")

        url = await generate_image_with_retry(prompt=prompt, w=w, h=h)
        print(f"    图片 URL: {url}")

        download_image_as_jpeg(url, image_path)
        print(f"    已保存 JPEG: {image_path}")

        await asyncio.sleep(sleep_seconds)


async def check_and_fix_missing(task_type: str = "all", w: int = 4096, h: int = 4096, category: str = DEFAULT_CATEGORY) -> None:
    """
    自动检测缺失图片并补全，缺啥补啥。
    - 没有 prompts.json 的 item：走 process_item 全流程（LLM 生成 prompt + 出图）
    - 有 prompts.json 但缺图的：直接用已有 prompt 补图
    """
    items_dir = Path(f"data/{category}/items")
    image_dir = Path(f"data/{category}/images")
    prompts_dir = image_dir / "prompts"

    effective_task_type = task_type if task_type != "fact" else "knowledge"

    item_files = list(iter_item_files(items_dir))
    print(f"🔍 正在扫描 {len(item_files)} 个项目的图片完整性 (模式: {task_type})...")

    full_process_items = []  # 没跑过的，需要全流程
    missing_tasks = []       # 跑过但缺图的，只需补图

    for item_path in item_files:
        item_data = load_json(item_path)
        slug = item_slug(item_path, item_data, category)
        prompts_json_path = prompts_dir / f"{slug}_prompts.json"

        # 检查该 item 是否有任何缺失图片
        sub_check_configs = [
            ("main", image_dir / "main" / f"{slug}_main.jpg",
             image_dir / "main" / f"{slug}_main_prompt.txt", "main_image"),
            ("story", image_dir / "story" / f"{slug}_story.jpg",
             image_dir / "story" / f"{slug}_story_prompt.txt", "story_image"),
            ("knowledge", image_dir / "knowledge" / f"{slug}_knowledge.jpg",
             image_dir / "knowledge" / f"{slug}_knowledge_prompt.txt", "knowledge_image"),
        ]

        has_missing = False
        for t_type, img_path, _, _ in sub_check_configs:
            if effective_task_type != "all" and t_type != effective_task_type:
                continue
            if not img_path.exists():
                has_missing = True
                break

        if not has_missing:
            continue

        # 没有 prompts.json → 全流程处理
        if not prompts_json_path.exists():
            full_process_items.append(item_path)
            continue

        # 有 prompts.json → 找出缺哪些图，用已有 prompt 补
        prompts_json_data = None
        try:
            prompts_json_data = json.loads(prompts_json_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  读取 prompts.json 失败 {prompts_json_path.name}: {e}")
            full_process_items.append(item_path)
            continue

        for t_type, img_path, prompt_path, prompt_key in sub_check_configs:
            if effective_task_type != "all" and t_type != effective_task_type:
                continue

            if img_path.exists():
                continue

            # 尝试从 _prompt.txt 读取
            saved_prompt = None
            if prompt_path.exists():
                try:
                    saved_prompt = prompt_path.read_text(encoding="utf-8").strip()
                except Exception as e:
                    print(f"  读取 Prompt 失败 {prompt_path.name}: {e}")

            # 回退：从 prompts.json 读取
            if not saved_prompt and prompts_json_data and isinstance(prompts_json_data, dict):
                saved_prompt = (prompts_json_data.get(prompt_key) or "").strip()

            if saved_prompt:
                missing_tasks.append({
                    "type": t_type,
                    "img_path": img_path,
                    "prompt": saved_prompt,
                    "slug": slug
                })
            else:
                # prompt 也拿不到，走全流程
                full_process_items.append(item_path)
                break

    total = len(full_process_items) + len(missing_tasks)
    if total == 0:
        print("✅ 所有图片均已存在。")
        return

    print(f"🚀 发现缺失: {len(full_process_items)} 个项目需全流程处理, {len(missing_tasks)} 张图片需补绘")

    # 1. 全流程处理（生成 prompt + 出图）
    for i, item_path in enumerate(full_process_items, 1):
        slug = item_slug(item_path, load_json(item_path), category)
        print(f"\n[{i}/{len(full_process_items)}] 全流程: {slug}")
        try:
            await process_item(
                item_path=item_path,
                image_dir=image_dir,
                overwrite=False,
                llm_model="deepseek-reasoner-stream-false",
                w=w, h=h,
                sleep_seconds=1.2,
                task_type=task_type,
                category=category,
            )
        except Exception as e:
            print(f"    ❌ 全流程失败 {slug}: {e}")

    # 2. 补图处理
    for i, task in enumerate(missing_tasks, 1):
        t_type = task["type"]
        img_path = task["img_path"]
        prompt = task["prompt"]

        print(f"[补图 {i}/{len(missing_tasks)}] {t_type}: {img_path.name}")

        try:
            url = await generate_image_with_retry(prompt=prompt, w=w, h=h)
            download_image_as_jpeg(url, img_path)
            print(f"    成功保存: {img_path}")
            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"    ❌ 补绘失败 {img_path.name}: {e}")

    print("\n✨ 缺失图片补全任务结束。")

async def async_main(item_name: str = None, task_type: str = "all") -> None:
    """
    :param item_name: 指定特定的 item 名称进行处理，自动开启覆盖模式。
    :param task_type: 指定处理的任务类型，可选 "all", "main", "story", "fact"。
    """
    parser = argparse.ArgumentParser(description="批量生成主图、故事图、小知识图。")

    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="品类名称，如 animal, fruit, flower 等")
    parser.add_argument("--items-dir", default=None, help="items JSON 目录（默认 data/{category}/items）")
    parser.add_argument("--image-dir", default=None, help="图片输出目录（默认 data/{category}/images）")
    parser.add_argument("--llm-model", default="deepseek-reasoner-stream-false", help="LLM 模型")

    parser.add_argument("--overwrite", action="store_true", help="是否覆盖已存在图片")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个文件")
    parser.add_argument("--start", type=int, default=0, help="从第几个文件开始")

    parser.add_argument("--w", type=int, default=4096, help="宽度")
    parser.add_argument("--h", type=int, default=4096, help="高度")
    parser.add_argument("--sleep", type=float, default=1.2, help="间隔秒数")

    # 允许从函数参数或命令行传入
    parser.add_argument("--item-name", default=item_name)
    parser.add_argument("--task-type", default=task_type, choices=["all", "main", "story", "fact"])

    args = parser.parse_args()

    category = args.category
    items_dir = Path(args.items_dir) if args.items_dir else Path(f"data/{category}/items")
    image_dir = Path(args.image_dir) if args.image_dir else Path(f"data/{category}/images")

    all_files = list(iter_item_files(items_dir))

    # 逻辑过滤
    if args.item_name:
        item_files = [f for f in all_files if args.item_name in f.name]
        if not item_files:
            print(f"❌ 未找到匹配 '{args.item_name}' 的文件")
            return
        args.overwrite = True  # 手动指定单项时，强制覆盖
        print(f"🎯 单项图片重绘模式: {item_files[0].name} | 任务: {args.task_type}")
    else:
        item_files = all_files
        if args.start > 0: item_files = item_files[args.start:]
        if args.limit > 0: item_files = item_files[:args.limit]
        print(f"🚀 批量图片模式: 准备处理 {len(item_files)} 个项")

    failed_items = []

    for index, item_path in enumerate(item_files, start=1):
        print(f"\n[{index}/{len(item_files)}] 处理图片中: {item_path.name}")
        try:
            await process_item(
                item_path=item_path,
                image_dir=image_dir,
                overwrite=args.overwrite,
                llm_model=args.llm_model,
                w=args.w,
                h=args.h,
                sleep_seconds=args.sleep,
                task_type=args.task_type,
                category=category,
            )
        except Exception as e:
            print(f"  ❌ 图片生成失败: {item_path.name} — {e}")
            failed_items.append({"file": item_path.name, "error": str(e)})

    if failed_items:
        print(f"\n⚠️  {len(failed_items)} 个 item 图片生成失败:")
        for fi in failed_items:
            print(f"  - {fi['file']}: {fi['error']}")
    else:
        print("\n✅ 全部图片处理完成，无失败。")


import asyncio


async def test_rebuild_specific_items():
    """
    测试用例：一次性修复多个指定的瑕疵项
    """
    # 你想重跑的 item 列表
    fix_list = [
        {"name": "apple", "task": "story"},  # 只要重画 apple 的故事图
        {"name": "banana", "task": "all"},  # banana 全部重画
        {"name": "cherry", "task": "main"}  # cherry 只重画主图
    ]

    print(f"🛠️ 开始修复任务，共 {len(fix_list)} 个项目...")

    for target in fix_list:
        print(f"\n>>> 正在修复: {target['name']} ({target['task']})")
        # 直接调用 async_main，利用我们改好的 item_name 参数
        await async_main(item_name=target['name'], task_type=target['task'])

    print("\n✨ 所有指定修复任务已完成！")


if __name__ == "__main__":
    asyncio.run(async_main())
