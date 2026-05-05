# 图像大模型选择
# app/infra/media/img_get.py

import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone
import httpx
from typing import List

logger = logging.getLogger(__name__)

# 导入全局并发控制信号量
from app.infra.concurrency import IMAGE_SEMAPHORE

class JimengProvider:
    def __init__(self, access_key: str, secret_key: str):
        self.ak = access_key
        self.sk = secret_key
        self.host = 'visual.volcengineapi.com'
        self.endpoint = 'https://visual.volcengineapi.com'
        self.region = 'cn-north-1'
        self.service = 'cv'

    def _sign(self, key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    async def generate_image(self, prompt: str, version: str = "v4.0", w: int = 2048, h: int = 2048) -> List[str]:

        # 使用信号量控制同时进入此代码块的协程数量
        async with IMAGE_SEMAPHORE:
            # 1. 参数准备
            req_key = "jimeng_t2i_v40" if version == "v4.0" else "high_aes_general_v30l_zt2i"
            query_params = {'Action': 'CVProcess', 'Version': '2022-08-31'}
            body_params = {
                "req_key": req_key,
                "prompt": prompt,
                "width": w,
                "height": h,
                "return_url": True
            }

            # 使用 separators 确保 JSON 字符串紧凑，与签名计算时的格式完全一致
            payload_body = json.dumps(body_params, separators=(',', ':'))
            canonical_query = "&".join([f"{k}={v}" for k, v in sorted(query_params.items())])

            # 2. 时间戳
            t = datetime.now(timezone.utc)
            amz_date = t.strftime('%Y%m%dT%H%M%SZ')
            date_stamp = t.strftime('%Y%m%d')

            # 3. 计算 Payload Hash
            payload_hash = hashlib.sha256(payload_body.encode('utf-8')).hexdigest()

            # 4. 构造 Canonical Request
            canonical_headers = (
                f"content-type:application/json\n"
                f"host:{self.host}\n"
                f"x-content-sha256:{payload_hash}\n"
                f"x-date:{amz_date}\n"
            )
            signed_headers = "content-type;host;x-content-sha256;x-date"

            canonical_request = (
                f"POST\n/\n{canonical_query}\n"
                f"{canonical_headers}\n"
                f"{signed_headers}\n{payload_hash}"
            )

            # 5. 计算 String to Sign
            credential_scope = f"{date_stamp}/{self.region}/{self.service}/request"
            hashed_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
            string_to_sign = f"HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashed_request}"

            # 6. 计算 Signature
            k_date = self._sign(self.sk.encode('utf-8'), date_stamp)
            k_region = self._sign(k_date, self.region)
            k_service = self._sign(k_region, self.service)
            k_signing = self._sign(k_service, 'request')

            signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

            # 7. 构造请求头
            headers = {
                'X-Date': amz_date,
                'X-Content-Sha256': payload_hash,
                'Authorization': f"HMAC-SHA256 Credential={self.ak}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}",
                'Content-Type': 'application/json'
            }

        # 8. 发起异步请求
            # 3. 发起异步请求
            try:
                # 建议优化：AsyncClient 如果调用频繁，建议作为类成员变量复用，而不是每次新建
                async with httpx.AsyncClient(timeout=60.0) as client:
                    url = f"{self.endpoint}?{canonical_query}"
                    response = await client.post(url, headers=headers, content=payload_body)

                    if response.status_code != 200:
                        logger.error(f"Jimeng API Failed: {response.status_code} {response.text}")
                        return []

                    res_json = response.json()
                    if res_json.get("code") in [0, 10000] or (
                            res_json.get("data") and "image_urls" in res_json["data"]):
                        return res_json.get("data", {}).get("image_urls", [])

                    logger.error(f"Jimeng Business Error: {res_json}")
                    return []

            except Exception as e:
                logger.exception(f"Jimeng Connection Error: {e}")
                return []