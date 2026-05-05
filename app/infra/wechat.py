# app/infra/wechat.py
# 微信基础设施层
# 职责：
# - 封装微信官方接口的底层调用
# - 实现 code 换取 openid（身份凭证转换）
# - 本模块仅负责通信，不涉及用户注册、积分发放等业务逻辑

import requests
import logging
from app.config import settings

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)

# 微信官方接口：小程序登录凭证校验
WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatAuthError(Exception):
    """自定义异常：当微信接口返回错误或通信失败时抛出"""
    pass


def code_to_openid(code: str) -> str:
    """
    使用微信 code 换取用户的唯一标识 openid
    :param code: 前端（小程序）通过 wx.login() 获取的临时登录凭证
    :return: 用户的 openid
    :raises WechatAuthError: 当 code 无效或微信接口报错时抛出
    """

    # 构造请求参数
    # appid 和 secret 从环境变量或 config.py 中读取，保证安全性
    params = {
        "appid": settings.WECHAT_APP_ID,
        "secret": settings.WECHAT_APP_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",  # 固定值
    }

    try:
        # 向微信服务器发送 GET 请求
        # 设置 5 秒超时，防止微信接口响应过慢拖垮应用
        resp = requests.get(WECHAT_CODE2SESSION_URL, params=params, timeout=5)
        resp.raise_for_status()  # 如果 HTTP 状态码不是 200，抛出异常

        data = resp.json()
        logger.debug("微信接口原始响应内容: %s", data)

        # 微信接口纠错逻辑：
        # 即使 HTTP 状态码是 200，微信也可能在 JSON 中返回 errcode
        if "openid" not in data:
            error_msg = data.get("errmsg", "unknown error")
            err_code = data.get("errcode", -1)
            logger.error(f"微信授权失败: [错误码:{err_code}] {error_msg}")
            raise WechatAuthError(f"微信认证失败: {error_msg}")

        # 成功拿到 openid
        return data["openid"]

    except requests.exceptions.RequestException as e:
        # 处理网络连接超时、DNS 解析失败等请求层面的错误
        logger.error(f"连接微信服务器发生网络错误: {str(e)}")
        raise WechatAuthError("无法连接到微信服务器，请稍后重试")


# app/infra/wechat.py 增加生成小程序码的功能

def get_access_token() -> str:
    """获取微信调用凭证（有效期2小时，实战建议存入缓存）"""
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={settings.WECHAT_APP_ID}&secret={settings.WECHAT_APP_SECRET}"
    resp = requests.get(url).json()
    return resp.get("access_token")


def generate_login_qrcode(scene_id: str):
    """
    生成带参数的小程序码（Unlimited接口）
    :param scene_id: 你的 Gradio 页面生成的唯一标识
    :return: 二维码图片的二进制数据
    """
    token = get_access_token()
    url = f"https://api.weixin.qq.com/wxa/getwxacodeunlimit?access_token={token}"

    # page 是你小程序里处理登录的页面路径
    # scene 是传给小程序的参数，最大32个字符
    payload = {
        "scene": scene_id,
        "page": "pages/index/index",
        "check_path": False,
        "env_version": "trial"  # 体验版
        #"env_version": "release"  # 正式版
    }
    resp = requests.post(url, json=payload)
    return resp.content  # 返回的是图片字节流，可以直接给 Gradio 显示