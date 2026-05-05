# 阿里云OSS上传基建
# app/infra/storage.py


import oss2
import asyncio
import os
import base64
import hmac
import hashlib
import json
from datetime import datetime, timedelta, timezone
from app.config import Settings

# 文件日志初始化
import logging
logger = logging.getLogger(__name__)


class AliyunOSSProvider:
    def __init__(self, access_key_id:str,access_key_secret:str,bucket_name: str, internal_endpoint: str, public_endpoint: str):
        """
        初始化阿里云 OSS 提供者
        :param auth: oss2.Auth 实例
        :param bucket_name: Bucket 名称
        :param internal_endpoint: 内网 Endpoint (例如 oss-cn-beijing-internal.aliyuncs.com)
        :param public_endpoint: 公网 Endpoint (例如 oss-cn-beijing.aliyuncs.com)
        """
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.auth = oss2.Auth(access_key_id, access_key_secret)
        self.bucket_name = bucket_name
        # 预先初始化两个 Bucket 实例。内网用于上传（省流、高速），公网用于签名（生成用户访问链接）
        # 修正逻辑：如果是测试环境，上传也走公网；否则走内网
        if hasattr(Settings, 'LOCAL') and Settings.LOCAL:
            print("DEBUG: 检测到测试环境，上传将使用公网 Endpoint")
            self.internal_bucket = oss2.Bucket(self.auth, public_endpoint, bucket_name)
        else:
            self.internal_bucket = oss2.Bucket(self.auth, internal_endpoint, bucket_name)
        self.public_bucket = oss2.Bucket(self.auth, public_endpoint, bucket_name)


    async def upload_and_get_url(self, local_file_path: str, oss_path: str, expires: int = 43200) -> str:
        """
        上传文件至 OSS 并返回公网带签名 URL，完成后自动删除本地文件
        :param local_file_path: 本地临时文件路径
        :param oss_path: 存放在 OSS 上的路径/文件名
        :param expires: 签名有效时间（秒），默认 12 小时
        """
        logger.info(f"正在准备上传文件: {local_file_path}")
        loop = asyncio.get_event_loop()

        try:
            # 检查本地文件是否存在
            if not os.path.exists(local_file_path):
                logger.error(f"Local file not found: {local_file_path}")
                return ""

            # 1. 内部上传逻辑：根据文件大小选择上传方式
            def _do_upload():
                file_size = os.path.getsize(local_file_path)
                # 小于 10MB 的 TTS 音频文件建议直接上传，避免产生断点续传碎片
                if file_size < 10 * 1024 * 1024:
                    self.internal_bucket.put_object_from_file(oss_path, local_file_path)
                else:
                    # 大文件使用断点续传，提高稳定性
                    oss2.resumable_upload(
                        self.internal_bucket,
                        oss_path,
                        local_file_path,
                        num_threads=2
                    )
                return True

            # 走内网 Endpoint 上传，不占用 3M 公网带宽
            await loop.run_in_executor(None, _do_upload)
            logger.info(f"OSS Internal Upload Success: {oss_path}")

            # 2. 内部签名逻辑：使用公网 Endpoint
            def _do_sign():
                # sign_url 返回的是带鉴权参数的字符串
                return self.public_bucket.sign_url('GET', oss_path, expires=expires)

            download_url = await loop.run_in_executor(None, _do_sign)

            # 兼容处理：强制使用 HTTPS 确保链接在浏览器/移动端正常打开
            if download_url and download_url.startswith("http://"):
                download_url = download_url.replace("http://", "https://", 1)

            return download_url

        except Exception as e:
            logger.error(f"OSS Infra Error: {str(e)}")
            return ""

        finally:
            # 3. 核心清理逻辑：无论成功失败，必须删除本地临时文件，防止 2G 服务器硬盘被 TTS 音频填满
            if os.path.exists(local_file_path):
                try:
                    os.remove(local_file_path)
                    logger.debug(f"Deleted temporary file: {local_file_path}")
                except Exception as clean_err:
                    logger.warning(f"Cleanup failed for {local_file_path}: {clean_err}")


    async def upload_file(self, local_file_path: str, oss_path: str) -> bool:
        """
        上传文件至 OSS，不删除本地文件，不返回签名 URL
        :param local_file_path: 本地文件路径
        :param oss_path: 存放在 OSS 上的路径/文件名
        :return: 是否上传成功
        """
        loop = asyncio.get_event_loop()

        try:
            if not os.path.exists(local_file_path):
                logger.error(f"Local file not found: {local_file_path}")
                return False

            def _do_upload():
                file_size = os.path.getsize(local_file_path)
                if file_size < 10 * 1024 * 1024:
                    self.internal_bucket.put_object_from_file(oss_path, local_file_path)
                else:
                    oss2.resumable_upload(
                        self.internal_bucket,
                        oss_path,
                        local_file_path,
                        num_threads=2
                    )
                return True

            await loop.run_in_executor(None, _do_upload)
            logger.info(f"OSS Upload Success: {oss_path}")
            return True

        except Exception as e:
            logger.error(f"OSS Upload Error: {str(e)}")
            return False

    async def download_file_internal(self, oss_path: str, local_dest_path: str) -> bool:
        """
        通过 ECS 内网从 OSS 下载文件到本地磁盘
        :param oss_path: OSS 上的路径 (例如: user_uploads/xxx/123.wav)
        :param local_dest_path: ECS 本地的存放路径
        :return: 下载是否成功
        """
        logger.info(f"正在通过内网下载 OSS 文件: {oss_path} -> {local_dest_path}")
        loop = asyncio.get_event_loop()

        try:
            # 确保本地目录存在
            os.makedirs(os.path.dirname(local_dest_path), exist_ok=True)

            def _do_download():
                # get_object_to_file 会根据文件大小自动选择最优下载策略
                # 且 internal_bucket 在初始化时已指向 internal_endpoint
                self.internal_bucket.get_object_to_file(oss_path, local_dest_path)
                return True

            # 在线程池中执行同步下载任务
            await loop.run_in_executor(None, _do_download)

            if os.path.exists(local_dest_path):
                logger.info(f"内网下载成功: {local_dest_path}")
                return True
            return False

        except Exception as e:
            logger.error(f"内网下载失败: {str(e)}")
            return False

    def generate_post_signature(self, user_id: str, expire_seconds: int = 3600):
        """
        生成前端直传所需的 PostObject 签名参数
        :param user_id: 用户ID，用于隔离目录
        :param expire_seconds: 签名有效期
        """
        # 从 self.auth 和 self.public_bucket 中提取已有的参数，避免修改 __init__
        access_key_id = self.access_key_id
        access_key_secret = self.access_key_secret
        # 从已有的 bucket 实例中获取 endpoint
        endpoint = self.public_bucket.endpoint

        # 1. 设置上传目录和过期时间
        upload_dir = f"user_uploads/{user_id}/"
        now = datetime.now(timezone.utc)
        expire_at = (now + timedelta(seconds=expire_seconds)).strftime('%Y-%m-%dT%H:%M:%SZ')

        # 2. 构造策略 (Policy)
        policy_dict = {
            "expiration": expire_at,
            "conditions": [
                {"bucket": self.bucket_name},
                ["starts-with", "$key", upload_dir],
                ["content-length-range", 0, 500 * 1024 * 1024]
            ]
        }

        policy_json = json.dumps(policy_dict).encode('utf-8')
        policy_base64 = base64.b64encode(policy_json).decode('utf-8')

        # 3. 生成 HMAC-SHA1 签名
        h = hmac.new(access_key_secret.encode('utf-8'), policy_base64.encode('utf-8'), hashlib.sha1)
        signature = base64.b64encode(h.digest()).decode('utf-8')

        # 4. 返回前端直传所需的 5 个核心要素
        return {
            "accessid": access_key_id,
            "host": f"https://{self.bucket_name}.{endpoint.replace('https://', '')}",
            "policy": policy_base64,
            "signature": signature,
            "dir": upload_dir
        }

    # --- 内部辅助函数 ---
    def _get_oss_token(self,user_id: str):
        html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>音频上传工具</title>
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {{ font-family: -apple-system, sans-serif; background: #f4f7f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
                    .card {{ background: white; padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); width: 90%; max-width: 400px; text-align: center; }}
                    h2 {{ color: #333; margin-bottom: 20px; }}
                    input[type="file"] {{ margin: 20px 0; width: 100%; }}
                    button {{ background: #2196F3; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 16px; width: 100%; font-weight: bold; }}
                    button:disabled {{ background: #ccc; }}
                    #status {{ margin-top: 20px; font-size: 14px; color: #666; word-break: break-all; }}
                    .copy-btn {{ margin-top: 10px; background: #4CAF50; display: none; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <h2>🎵 上传 BGM</h2>
                    <p style="font-size: 12px; color: #999;">仅支持 .mp3 / .wav (最大 20MB)</p>
                    <input type="file" id="fileInput" accept=".mp3,.wav">
                    <button id="upBtn" onclick="doUpload()">开始上传</button>
                    <div id="status">准备就绪</div>
                    <button id="copyBtn" class="copy-btn" onclick="copyPath()">复制路径并关闭</button>
                </div>

                <script>
                    let savedPath = "";

                    async function doUpload() {{
                        const fileInput = document.getElementById('fileInput');
                        const btn = document.getElementById('upBtn');
                        const status = document.getElementById('status');

                        if (!fileInput.files[0]) return alert("请先选择文件");
                        const file = fileInput.files[0];

                        // 简单校验
                        if (file.size > 20 * 1024 * 1024) return alert("超过 20MB 限额");

                        btn.disabled = true;
                        status.innerText = "⏳ 正在获取授权...";

                        try {{
                            // 1. 请求签名接口 (注意路径要对)
                            const res = await fetch('/scripts/get_oss_key', {{
                                method: 'POST',
                                headers: {{ 'x-user-id': '{user_id}' }}
                            }});
                            const p = await res.json();

                            status.innerText = "🚀 正在直传阿里云 OSS...";

                            // 2. 构造上传
                            const fd = new FormData();
                            savedPath = p.dir + Date.now() + "-" + file.name;
                            fd.append('key', savedPath);
                            fd.append('policy', p.policy);
                            fd.append('OSSAccessKeyId', p.accessid);
                            fd.append('success_action_status', '200');
                            fd.append('signature', p.signature);
                            fd.append('file', file);

                            const upRes = await fetch(p.host, {{ method: 'POST', body: fd }});

                            if (upRes.ok) {{
                                status.innerHTML = "<b style='color:green;'>✅ 上传成功！</b><br><small>" + savedPath + "</small>";
                                document.getElementById('copyBtn').style.display = 'block';
                                btn.innerText = "上传完成";
                            }} else {{
                                status.innerText = "❌ 上传失败，请检查配置";
                                btn.disabled = false;
                            }}
                        }} catch (e) {{
                            status.innerText = "❌ 出错了: " + e.message;
                            btn.disabled = false;
                        }}
                    }}

                    function copyPath() {{
                        navigator.clipboard.writeText(savedPath).then(() => {{
                            alert("路径已复制！请回到 Agent 页面填入 'BGM地址' 框。");
                            window.close();
                        }});
                    }}
                </script>
            </body>
            </html>
            """

    async def list_files_by_time(self, prefix: str, reverse: bool = True) -> list:
        """
        获取文件列表，并按最后修改时间排序
        :param prefix: 目录前缀
        :param reverse: 默认 True，即最新修改的文件排在最前面
        """
        loop = asyncio.get_event_loop()

        def _do_list():
            try:
                # 获取包含元数据的对象列表
                objects = [obj for obj in oss2.ObjectIterator(self.public_bucket, prefix=prefix) if not obj.is_prefix()]
                # 按最后修改时间排序
                objects.sort(key=lambda x: x.last_modified, reverse=reverse)
                return [obj.key for obj in objects]
            except Exception as e:
                logger.error(f"OSS List Sorted Error: {str(e)}")
                return []

        return await loop.run_in_executor(None, _do_list)



