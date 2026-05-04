from app import *  # noqa: F401,F403


def to_bool(value: str) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def resolve_inspirer_category(prompt: str, category_value: str = "auto") -> dict:
    selected = INSPIRER_CATEGORY_BY_VALUE.get(category_value) or INSPIRER_CATEGORY_BY_VALUE["auto"]
    if selected["value"] != "auto":
        return selected

    lowered_prompt = prompt.lower()
    for category in INSPIRER_CATEGORIES:
        if category["value"] == "auto":
            continue
        if any(keyword.lower() in lowered_prompt for keyword in category["keywords"]):
            return category
    return INSPIRER_CATEGORY_BY_VALUE["auto"]


def extract_inspirer_examples(category: dict, limit: int = 2) -> list[str]:
    if not category.get("directory"):
        return []
    prompt_file = IMAGE_INSPIRER_DB_DIR / category["directory"] / "prompt.md"
    if not prompt_file.exists():
        return []
    text = prompt_file.read_text(encoding="utf-8", errors="ignore")
    chunks = [chunk.strip() for chunk in text.split("---") if len(chunk.strip()) > 120]
    examples = []
    for chunk in chunks:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        content_lines = [line for line in lines if not line.startswith("**来源") and not line.startswith("![")]
        example = " ".join(content_lines)[:360]
        if example:
            examples.append(example)
        if len(examples) >= limit:
            break
    return examples


def build_inspirer_style_hints(examples: list[str]) -> str:
    text = "\n".join(examples)
    candidates = [
        ("电影", "电影感光影"),
        ("海报", "海报级构图"),
        ("留白", "克制留白"),
        ("高级", "高级质感"),
        ("写实", "写实细节"),
        ("插画", "插画表现力"),
        ("国潮", "国潮视觉"),
        ("信息图", "信息层级清晰"),
        ("产品", "产品主体突出"),
        ("品牌", "品牌调性统一"),
        ("光影", "明确光影层次"),
        ("材质", "材质细节丰富"),
        ("色彩", "色彩统一"),
        ("文字", "文字清晰可读"),
        ("8K", "高清细节"),
    ]
    hints = []
    for keyword, hint in candidates:
        if keyword in text and hint not in hints:
            hints.append(hint)
        if len(hints) >= 6:
            break
    return "、".join(hints) if hints else "主体明确、构图清晰、光影完整、风格统一、细节丰富"


def infer_prompt_scene_hints(prompt: str) -> list[str]:
    prompt_lower = prompt.lower()
    rules = [
        (("美女", "女孩", "女生", "人物", "肖像", "人像", "模特", "woman", "girl", "portrait"), "人物气质自然，姿态舒展，表情真实，服饰与场景协调"),
        (("狗", "犬", "猫", "宠物", "动物", "dog", "cat", "pet"), "宠物动作自然，毛发质感清晰，与人物形成互动关系"),
        (("上海", "外滩", "陆家嘴", "城市", "街道", "都市", "city", "street"), "城市地标和空间层次清楚，背景建筑具有地域辨识度"),
        (("十年后", "未来", "科幻", "future", "futuristic"), "加入克制的未来感细节，避免过度科幻化"),
        (("散步", "漫步", "走路", "walk", "walking"), "采用生活纪实感瞬间，步行动势自然，画面有叙事感"),
        (("黄昏", "夕阳", "夜景", "清晨", "雨", "雪", "sunset", "night"), "明确时间氛围和光线方向，增强环境情绪"),
    ]
    hints = []
    for keywords, hint in rules:
        if any(keyword in prompt_lower or keyword in prompt for keyword in keywords):
            hints.append(hint)
    return hints


def polish_prompt_text(prompt: str, category_value: str = "auto") -> str:
    prompt = prompt.strip()
    if not prompt:
        return prompt
    category = resolve_inspirer_category(prompt, category_value)
    examples = extract_inspirer_examples(category)
    style_hints = build_inspirer_style_hints(examples)
    scene_hints = infer_prompt_scene_hints(prompt)
    detail_parts = []
    if category["value"] != "auto":
        detail_parts.append(f"画面方向：{category['label']}")
    if scene_hints:
        detail_parts.append("，".join(scene_hints))
    detail_sentence = "。".join(detail_parts)
    style_sentence = f"视觉风格：{style_hints}，电影感构图，真实光影，高质量细节，色彩协调，主体突出，背景不杂乱。"

    return (
        f"{prompt}。"
        f"{detail_sentence + '。' if detail_sentence else ''}"
        f"{style_sentence}"
        "镜头要求：中景到全景视角，空间层次清晰，适度景深，画面比例稳定。"
        "负面约束：不要水印、不要乱码文字、不要畸形肢体、不要低清晰度、不要过度拥挤、不要风格漂移。"
    )


def polish_prompt_with_ai(prompt: str, category_value: str = "auto") -> str:
    prompt = prompt.strip()
    if not prompt:
        return prompt
    config = get_provider_config(include_secret=True)
    if not config.get("polish_enabled") or not config.get("polish_api_key") or not config.get("polish_base_url") or not config.get("polish_model"):
        raise ValueError("管理员暂未配置可用的 AI 润色接口。")

    client = build_client(config["polish_api_key"], config["polish_base_url"])
    system_prompt = (
        "你是专业图像生成提示词优化器。请把用户中文需求改写成最终可直接发送给生图模型的中文提示词。"
        "只输出润色后的提示词，不要解释、不要标题、不要 Markdown。保持主体和核心意图不变，补充构图、主体细节、环境、镜头、光线、色彩、材质、景深和画质要求。"
        "不要编造与原需求冲突的内容，不要加入水印、乱码文字、畸形肢体、低清晰度等负面元素。"
    )
    if category_value == "auto":
        user_prompt = f"原始提示词：{prompt}\n请自行判断最适合的视觉方向，不要被固定分类限制。"
    else:
        category = resolve_inspirer_category(prompt, category_value)
        user_prompt = f"原始提示词：{prompt}\n用户指定润色方向：{category['label']}"
    response = client.chat.completions.create(
        model=config["polish_model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )
    content = response.choices[0].message.content if response.choices else ""
    polished = (content or "").strip().strip('"“”')
    if not polished:
        raise ValueError("AI 润色接口没有返回有效提示词。")
    return polished
