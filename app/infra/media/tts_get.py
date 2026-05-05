# tts模型接口调用
# app/infra/llm/tts_get.py

import httpx
import json
from typing import Dict, Any, Optional
from datetime import datetime
import os
from pathlib import Path
import uuid
from moviepy.editor import AudioFileClip, CompositeAudioClip
import random

# 导入全局并发控制信号量
from app.infra.concurrency import TTS_SEMAPHORE
# 文件日志初始化
import logging
logger = logging.getLogger(__name__)

# 路径初始化
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 2. 定义绝对路径
TEMP_DIR = BASE_DIR / "temp" / "tts_voice"
BGM_DIR = BASE_DIR / "orchestrator" / "resources" / "audio_data" / "bgm"

# 3. 确保临时目录存在
try:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    # 如果是权限问题，可以回退到系统临时目录
    import tempfile
    TEMP_DIR = Path(tempfile.gettempdir()) / "tts_voice"
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

class TTSProvider:
    def __init__(self, api_key: str, base_url: str, model: str = "speech-2.8-hd"):
        """
        初始化 Minimax 提供者
        :param api_key: 你的 Minimax API Key
        :param base_url: API 基础地址 (例如: https://api.minimaxi.com/v1/t2a_v2)
        :param model: 模型名称，默认使用 deepseek-chat (V3)
        """
        self.api_key = api_key
        # 统一处理 URL 结尾，避免拼接时出现双斜杠
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def text_to_oss_url(self, text: str, voice_id: str, bgm_switch: int, bgm_temp_file: str) -> str:
        """
        核心业务逻辑：文字 -> 本地临时mp3 -> OSS URL -> 删除本地
        优化点：减少同步IO阻塞，优化路径生成逻辑
        """
        from app.infra.infra_provider import use_oss

        # 1. 生成唯一标识，减少不必要的 datetime 格式化开销
        unique_suffix = f"{uuid.uuid4().hex[:12]}"
        local_path = str(TEMP_DIR / f"tts_{unique_suffix}.wav")
        mix_local_path = str(TEMP_DIR / f"mix_{unique_suffix}.wav")

        final_wav_path = local_path

        try:
            # 2. TTS 生成
            success = await self.generate_speech_to_file(
                text=text, voice_id=voice_id, file_path=local_path
            )
            if not success:
                logger.error("TTS generation failed")
                return ""

            # 3. BGM 处理逻辑优化
            if bgm_switch == 1:
                # 性能优化：可以考虑在类变量中缓存 bgm 列表，而不是每次 listdir
                files = [f for f in os.listdir(BGM_DIR) if f.endswith((".mp3", ".wav", ".ogg"))]
                if files:
                    bgm_path = str(BGM_DIR / random.choice(files))
                    await self.mix_voice_bgm(voice_path=local_path, bgm_path=bgm_path, output_path=mix_local_path)
                    final_wav_path = mix_local_path
            elif bgm_switch == 2 and bgm_temp_file:
                await self.mix_voice_bgm(voice_path=local_path, bgm_path=bgm_temp_file, output_path=mix_local_path)
                final_wav_path = mix_local_path

            # 4. 上传到 OSS
            # 优化：oss_path 的生成放在真正需要上传前
            oss_folder = datetime.now().strftime("%Y-%m-%d")
            oss_file_name = os.path.basename(final_wav_path)
            oss_path = f"audio/{oss_folder}/{oss_file_name}"

            audio_url = await use_oss().upload_and_get_url(
                local_file_path=final_wav_path,
                oss_path=oss_path
            )
            return audio_url

        except Exception as e:
            logger.exception(f"TTS Service Process Error: {e}")
            raise e
        finally:
            # 5. 最终清理逻辑：使用 anyio 或 aiofiles 异步删除，避免阻塞事件循环
            # 无论成功失败都会执行
            for path in {local_path, mix_local_path}:
                try:
                    if os.path.exists(path):
                        os.remove(path)  # 如果量极大，建议使用 anyio.Path(path).unlink()
                except Exception as clean_err:
                    logger.warning(f"Failed to cleanup file {path}: {clean_err}")


    async def generate_speech_to_file(
            self,
            text: str,
            voice_id: str,
            file_path: str,
            voice_setting: Optional[Dict[str, Any]] = None,
            audio_setting: Optional[Dict[str, Any]] = None
            ) -> bool:
        """
        同步语音合成流式接口：受信号量保护，防止服务器过载
        """
        # -----------测试报错逻辑
        # from fastapi import HTTPException
        # raise HTTPException(status_code=500, detail="服务器系统异常")
        # -----------测试报错逻辑

        logger.info(f"Generating TTS from {text}")
        # 使用信号量：如果已有 max_concurrent 个任务在跑，这里会异步等待
        # print(f"DEBUG: 准备获取信号量... 当前计数: {TTS_SEMAPHORE._value}")
        async with TTS_SEMAPHORE:
            logger.info(f"Starting TTS task for {len(text)} chars...")

            # 内部逻辑保持不变
            default_voice_setting = {
                "voice_id": voice_id,
                "speed": 1.3,
                "vol": 1,
                "pitch": 0,
                # "emotion": "happy"
            }
            default_audio_setting = {
                "sample_rate": 44100,
                "bitrate": 256000,
                "format": "mp3",
                "channel": 1
            }
            payload = {
                "model": self.model,
                "text": text,
                "stream": False,
                "voice_setting": voice_setting or default_voice_setting,
                "audio_setting": audio_setting or default_audio_setting,
                "continuous_sound": False  # 必须为 False
            }

            try:
                async with httpx.AsyncClient(timeout=300.0,trust_env=False) as client:
                    # 像官方案例一样，直接一次性 POST
                    # print(json.dumps(payload))
                    response = await client.post(self.base_url, headers=self.headers, json=payload)

                    if response.status_code != 200:
                        logger.error(f"TTS Error: {response.text}")
                        return False
                    # 直接解析整个 JSON (对应官方案例的 print(response.text))
                    parsed_json = json.loads(response.text)
                    # 获取audio字段的值
                    audio_value = bytes.fromhex(parsed_json['data']['audio'])
                    with open(file_path, 'wb') as f:
                        f.write(audio_value)
                        return True
            except Exception as e:
                logger.exception(f"TTS Infra Failed: {e}")
                raise e

    async def mix_voice_bgm(self,
            voice_path: str,
            bgm_path: str,
            output_path: str,
            bgm_ratio: float = 0.03,
            bgm_head: float = 2.0,
            bgm_tail: float = 3.0,
            voice_tail: float = 0.1
    ):
        """
        混音人声与背景音乐。
        :param str voice_path: 人声文件的本地路径（如：'voice.wav'）
        :param str bgm_path: 背景音乐文件的本地路径（如：'music.mp3'）
        :param str output_path: 合成后的音频输出路径（如：'final.mp3'）
        :param float bgm_ratio: BGM 的音量比例（建议 0.1-0.3），用于控制背景音大小
        :param float bgm_head: 开头留白时长（秒）：人声开始前，纯 BGM 播放的时长
        :param float bgm_tail: 结束留白时长（秒）：人声结束后，BGM 继续播放的时长
        :param float voice_tail: 人声末尾裁剪时长（秒）：用于裁掉人声末尾可能的噪音并进行淡出处理
        :return: 混音完成后的处理状态
        """
        # 将所有 Clip 初始化为 None，方便在 finally 中统一回收
        voice_raw = bgm = voice = bgm_loop = bgm1 = bgm2 = final = None

        try:
            # 1. 加载
            voice_raw = AudioFileClip(voice_path)
            bgm = AudioFileClip(bgm_path)

            # === 【原逻辑】人声干净收尾 =========================================
            safe_end = max(0, voice_raw.duration - voice_tail)
            voice = (voice_raw.subclip(0, safe_end)
                     .audio_fadeout(voice_tail)
                     .set_start(bgm_head))

            # 2. 计算时长
            total_dur = bgm_head + voice.duration + bgm_tail
            clip_dur = bgm.duration

            # 3. 无限循环 BGM
            def loop_frame(get_frame, t):
                return get_frame(t % clip_dur)

            bgm_loop = bgm.fl(loop_frame, apply_to="audio").set_duration(total_dur)

            # 4-5. 两段 BGM 包络（保持原逻辑）
            # bgm1: 开头那段较高的音量，然后淡出
            bgm1 = (bgm_loop.subclip(0, bgm_head)
                    .volumex(1 - bgm_ratio)
                    .audio_fadeout(bgm_head))
            # bgm2: 贯穿全程的底噪
            bgm2 = (bgm_loop.subclip(0, total_dur)
                    .volumex(bgm_ratio)
                    .audio_fadeout(bgm_tail))

            # 6-7. 合成
            final = CompositeAudioClip([bgm1, bgm2, voice])

            # === 写出文件 ======================================================
            wav_path = output_path.rsplit(".", 1)[0] + ".wav"
            final.write_audiofile(wav_path, fps=44100, codec="pcm_s16le",
                                  logger=None)  # logger=None 也能减少一点开销
            print(f"✅ 合成完成（WAV）：{wav_path}")
            return wav_path

        finally:
            # === 【核心修复】强制释放内存 =======================================
            # MoviePy 必须显式调用 close()，否则句柄不释放，内存会堆积
            for clip in [final, bgm1, bgm2, bgm_loop, voice, voice_raw, bgm]:
                if clip is not None:
                    try:
                        clip.close()
                    except:
                        pass
            # 释放后建议手动清一下内存
            import gc
            gc.collect()

"""
_____男
Reflective Ryan - 清亮干净,轻松自然,邻家朋友 | moss_audio_9c223de9-7ce1-11f0-9b9f-463feaa3106a

南方小哥 - 温润细腻,娓娓道来,亲切邻家 | Chinese (Mandarin)_Southern_Young_Man

Credible Alex - 质朴自然,娓娓道来,经验分享感 | moss_audio_ce44fc67-7ce3-11f0-8de5-96e35d26fb85

_____女

Grounded Grace - 清亮,快慢有致,真实接地气 | moss_audio_aaa1346a-7ce7-11f0-8e61-2e6e3c7ee85d

嚣张小姐 - 娇俏明亮,灵动跳跃,傲娇自信 | Arrogant_Miss

Wary Willow - 略带沙哑,随意自然,酷飒感 | moss_audio_3dee3d0c-7ce6-11f0-8ff8-2a857e2646d2

"""