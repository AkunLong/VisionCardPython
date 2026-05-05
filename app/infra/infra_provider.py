# LLM选择分发工具
# app/infra/infra_provider.py

from app.infra.llm.llm_get import LLMProvider
# from app.infra.media.tts_get import TTSProvider
from app.infra.media.img_get import JimengProvider
from app.infra.storage import AliyunOSSProvider

from app.config import settings

def get_llm(model):
    if model == "deepseek-chat-stream-false":
        return LLMProvider(api_key=settings.DEEPSEEK_API_KEY, base_url=settings.DEEPSEEK_BASE_URL,model="deepseek-v4-pro")
    if model == "deepseek-reasoner-stream-false":
        return LLMProvider(api_key=settings.DEEPSEEK_API_KEY, base_url=settings.DEEPSEEK_BASE_URL,model="deepseek-v4-pro")
    elif model == "qwen-plus-stream-false":
        return LLMProvider(api_key=settings.QWEN_API_KEY, base_url=settings.QWEN_BASE_URL,model="qwen-plus")

def get_img():
    return JimengProvider(access_key=settings.JIMENG_API_KEY, secret_key=settings.JIMENG_SECRET_KEY)

def get_tts():
    return None
    # return TTSProvider(api_key=settings.MINIMAX_API_KEY, base_url=settings.MINIMAX_BASE_URL)

def use_oss():
    # 保留24小时
    return AliyunOSSProvider(access_key_id=settings.OSS_ACCESS_KEY,access_key_secret=settings.OSS_SECRET_KEY,bucket_name=settings.OSS_BUCKET_TEMP_NAME,internal_endpoint=settings.OSS_INTERNAL_ENDPOINT,public_endpoint=settings.OSS_PUBLIC_ENDPOINT)
def use_oss_save():
    # 永久保存
    return AliyunOSSProvider(access_key_id=settings.OSS_ACCESS_KEY, access_key_secret=settings.OSS_SECRET_KEY,
                             bucket_name=settings.OSS_BUCKET_SAVE_NAME,
                             internal_endpoint=settings.OSS_INTERNAL_ENDPOINT,
                             public_endpoint=settings.OSS_PUBLIC_ENDPOINT)


"""引用方法"""
async def llm_test():
    messages = [
        {"role": "system", "content": "陪用户聊天"},
        {"role": "user", "content": "你好啊"}
    ]
    msg_2 = await get_llm(model="qwen-plus-stream-false").chat_completion(messages=messages)
    print(msg_2['choices'][0]['message']['content'])

async def tts_test():
    text: str = '欢迎使用猫头鹰自媒体创作者平台，这里面都是宝贝，做短视频，这里啥都有'
    voice_id: str = 'Arrogant_Miss'
    await get_tts().text_to_oss_url(text=text, voice_id=voice_id,bgm_switch=0,bgm_temp_file='')
async def tts_test2():
    text: str = '欢迎使用猫头鹰自媒体创作者平台，这里面都是宝贝，做短视频，这里啥都有'
    voice_id: str = 'Arrogant_Miss'
    file_path = "test.wav"
    await get_tts().generate_speech_to_file(text=text, voice_id=voice_id, file_path=file_path)

async def img_test():
    w = 1920
    h = 1080
    prompt = "一张蓝天白云，绿地悠悠的壁纸"
    url = await get_img().generate_image(w=w, h=h,prompt=prompt)
    print(url)


async def use_oss_test():
    file_name = '/Users/kun/PycharmProjects/VideoTLAgent/tests/test.html'
    from datetime import datetime
    oss_folder = datetime.now().strftime("%Y-%m-%d")
    oss_path = f"audio/{oss_folder}/test.html"
    url = await  use_oss().upload_and_get_url(local_file_path=file_name,oss_path=oss_path)
    print(url)


async def tts_mix():
    from pathlib import Path
    import os
    import random
    import uuid

    # 1. 获取当前文件所在的绝对路径，并回溯到项目根目录
    # __file__ 是 .../app/infra/infra_provider.py
    # .parent.parent 是项目根目录 VideoTLAgent
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

    # 2. 使用绝对路径定义目录
    TEMP_DIR = BASE_DIR / "temp" / "wav"
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    BGM_DIR = BASE_DIR / "app" / "orchestrator" / "resources" / "audio_data" / "bgm"

    # 检查 BGM 目录是否存在，如果不存在打印调试信息
    if not BGM_DIR.exists():
        print(f"错误：找不到BGM目录，请确认路径是否存在: {BGM_DIR}")
        return

    # 3. 读取文件
    files = [f for f in os.listdir(BGM_DIR) if f.endswith((".mp3", ".wav", ".ogg"))]

    unique_suffix = f"{uuid.uuid4().hex[:12]}"
    local_path = str(TEMP_DIR / "干净男声.wav")

    # 确保 mix_temp 目录也存在
    mix_temp_dir = TEMP_DIR / "mix_temp"
    mix_temp_dir.mkdir(parents=True, exist_ok=True)
    mix_local_path = str(mix_temp_dir / f"mix_{unique_suffix}.wav")

    if files:
        bgm_path = str(BGM_DIR / random.choice(files))
        print(f"正在混音: {local_path} + {bgm_path}")
        await get_tts().mix_voice_bgm(voice_path=local_path, bgm_path=bgm_path, output_path=mix_local_path)
    else:
        print("BGM 目录为空，请放入音频文件")

async def img_get():
    prompt = '''
    一个完整的新鲜红苹果，单个主体，居中构图，画面饱满，正面微角度，正面光源
    纯白色背景，摄影风格，整体画面明亮通透，低对比度，
    光线均匀柔和，从多个方向均匀照亮主体，
    苹果表面各个区域亮度接近，没有明显明暗分区，
    主体边缘清晰干净，与背景自然分离，
    苹果表皮光滑，带有细小自然水珠，
    真实摄影风格，高清细节，质感自然，
    画面干净、明亮、通透，类似电商白底商品图，
    正方形构图，1:1，高分辨率
    '''
    w =4096
    h = 4096
    url = await get_img().generate_image(prompt=prompt,w=w,h=h)
    print(url)

if __name__ == "__main__":
    import asyncio

    asyncio.run(img_get())
    #asyncio.run(use_oss_test())







