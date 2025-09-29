import os
import json
from locust import HttpUser, task, between
class BackendUser(HttpUser):
    """
    一个模拟用户，用于测试后端的登录和聊天功能。
    """
    # 每个模拟用户在执行任务之间会随机等待1到3秒
    wait_time = between(1, 3)
    # --- 配置 ---
    # 1. 设置被测试后端的主机地址
    # 推荐通过环境变量 API_HOST 设置, 例如: export API_HOST=http://127.0.0.1:8001
    # 如果不设置，则默认为 http://127.0.0.1:8001
    host = os.getenv("API_HOST", "http://127.0.0.1:8001")

    # 2. 设置用于登录的凭证
    # 同样，推荐使用环境变量 LOCUST_USER 和 LOCUST_PASSWORD
    username = os.getenv("LOCUST_USER", "admin")
    password = os.getenv("LOCUST_PASSWORD", "JZJZ112233")

    def on_start(self):
        """
        当一个 Locust 虚拟用户启动时被调用。
        每个虚拟用户都会在这里登录一次，并为后续的请求设置好认证头。
        """
        print(f"用户启动 - 正在为用户 {self.username} 登录...")
        
        # /token 接口需要 application/x-www-form-urlencoded 格式的数据
        response = self.client.post(
            "/api/v1/auth/token",
            data={"username": self.username, "password": self.password},
            name="/auth/token"  # 在Locust报告中为此请求命名
        )
        
        if response.status_code == 200:
            token = response.json().get("access_token")
            if token:
                print("登录成功，获取到Token。")
                # 为该用户的所有后续请求设置 Authorization 头
                self.client.headers["Authorization"] = f"Bearer {token}"
            else:
                print("登录响应成功，但未找到 access_token。")
                self.environment.runner.quit() # 严重错误，停止测试
        else:
            print(f"登录失败。状态码: {response.status_code}, 响应: {response.text}")
            # 如果登录失败，这个用户就无法继续测试，直接停止
            self.stop()

    @task
    def chat_request(self):
        """
        模拟用户向 /api/v1/chat 接口发送一个简单的聊天请求。
        这个任务会被用户反复执行。
        """
        # 这是一个对 /chat 接口有效的最小化、合法的请求体。
        # 我们在这里不提供 env_id，让后端进入“数据库无关”的模式，
        # 这样测试可以独立于任何活动的DolphinDB环境。
        chat_payload = {
            "conversation_history": [
                {
                    "role": "user",
                    "content": "Hello, can you tell me about DolphinDB? I want to know its core features."
                }
            ],
            "injected_context": None,
            "env_id": None
        }
        
        self.client.post(
            "/api/v1/chat",
            json=chat_payload,
            name="/chat"  # 将所有聊天请求在报告中归为一类
        )

