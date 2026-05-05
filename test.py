import json

with open("data/fruit/tags.json", "r") as f:
    tags = json.load(f)

for tag in tags:
    print(tag["icon"])

import os
import json


def process_json_files(directory):
    # 检查目录是否存在
    if not os.path.exists(directory):
        print(f"错误: 目录 '{directory}' 不存在。")
        return

    # 计数器
    count = 0

    # 遍历目录下所有文件
    for filename in os.listdir(directory):
        if filename.endswith(".json"):
            file_path = os.path.join(directory, filename)

            try:
                # 1. 读取 JSON 数据
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 2. 修改逻辑: 检查路径 content -> zh-CN -> words 是否存在
                # 使用 get() 链式访问防止因为 key 不存在导致报错
                content = data.get("content", {})
                zh_cn = content.get("zh-CN", {})

                if "words" in zh_cn:
                    original_word = zh_cn["words"]
                    # 将大写转换为小写
                    lower_word = original_word.lower()

                    if original_word != lower_word:
                        zh_cn["words"] = lower_word

                        # 3. 写回文件
                        with open(file_path, 'w', encoding='utf-8') as f:
                            # ensure_ascii=False 保证中文不被转义成 \uXXXX
                            # indent=4 保持美观的缩进
                            json.dump(data, f, ensure_ascii=False, indent=4)

                        print(f"已处理: {filename} ('{original_word}' -> '{lower_word}')")
                        count += 1

            except Exception as e:
                print(f"处理文件 {filename} 时出错: {e}")

    print(f"\n任务完成！共修改了 {count} 个文件。")


if __name__ == "__main__":
    target_dir = "data/fruit/items-ok"
    process_json_files(target_dir)