import requests
import re
from app.config import settings

def push_to_wechat(msg_type, msg_time, msg_content, detail_url):
    """
    一行代码推送：支持多用户列表，内部已封装身份信息、Token获取与文本处理
    """
    # --- 1. 固定配置信息 ---
    APP_ID = "wxa3b4a2add529fe8f"
    APP_SECRET = "a530072098715167720dcba39db4235b"
    # 这里修改为列表，把所有人的 OpenID 放进去
    if settings.LOCAL:
        USER_LIST = [
            "oZhVDt5YJ2SW2NU0x9VOYTnpOouk" # 我
        ]
    else:
        USER_LIST = [
            "oZhVDt5YJ2SW2NU0x9VOYTnpOouk", # 我
            "oZhVDt5KVlqC6gn5biYwBeLIU-Zo", # 易读猫
            "oZhVDtxgK2eJLLep7JL7EpDbWyXk", # 贝加
            "oZhVDt9VtlGKcXxY4lipyx5H-GvE", # 野水
            "oZhVDtyguTXBQAflZgCMEeOtM4M8", # Bil桃老师
            "oZhVDt5E903_rkoR7k_wKaukrs3E", # penn
            "oZhVDt4LtRDzLYidrSWzTfwbuhbM", # 老象
        ]
    TEMPLATE_ID = "APxokMl81LRPsMdxrvpcEqgzLn6T528UZfwML57iQ8c"

    # --- 2. 自动获取 Access Token (只获取一次) ---
    token_url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={APP_ID}&secret={APP_SECRET}"
    try:
        token_res = requests.get(token_url, timeout=5).json()
        access_token = token_res.get("access_token")
        if not access_token:
            print(f"❌ Token获取失败: {token_res}")
            return False
    except Exception as e:
        print(f"❌ 网络异常: {e}")
        return False

    # --- 3. 处理早报内容摘要 ---
    clean_text = re.sub(r'[#*|>\-]', '', msg_content)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    summary = clean_text[:100] + "..." if len(clean_text) > 100 else clean_text

    # --- 4. 循环发送给列表中的每个人 ---
    send_url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}"

    all_success = True
    for user_id in USER_LIST:
        payload = {
            "touser": user_id,
            "template_id": TEMPLATE_ID,
            "url": detail_url,
            "data": {
                "type": {"value": msg_type, "color": "#173177"},
                "time": {"value": msg_time, "color": "#173177"},
                "content": {"value": summary, "color": "#333333"}
            }
        }

        try:
            res = requests.post(send_url, json=payload).json()
            if res.get("errcode") == 0:
                print(f"✅ 推送成功 -> 用户: {user_id}")
            else:
                print(f"❌ 推送失败 -> 用户: {user_id}, 原因: {res}")
                all_success = False
        except Exception as e:
            print(f"❌ 发送请求异常 -> 用户: {user_id}: {e}")
            all_success = False

    return all_success


def push_test():
    # 假设这是你的后台 JSON 数据
    raw_json = {
        "task_type": "pm",
        "update_time": "06:50:32",
        "content": "# 2026年1月18日科技流量早报...\n\n这里是正文内容..."
    }

    # 你在业务逻辑中只需这样调用：
    push_to_wechat(
        msg_type = "早报" if raw_json['task_type'] == 'am' else "晚报",
        msg_time = raw_json['update_time'],
        msg_content = raw_json['content'],
        detail_url = "https://news.edubookai.com/search/get_latest_html"
    )

# push_test()