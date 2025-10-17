# FILE: ./services/email_service.py

import aiosmtplib
from email.message import EmailMessage
from core.config import settings
import socket

class BaseEmailService:
    async def send_verification_email(self, recipient_email: str, verification_code: str):
        raise NotImplementedError

class MockEmailService(BaseEmailService):
    """
    一个模拟的邮件服务，用于开发和测试。
    它不会真的发送邮件，而是将邮件内容打印到控制台。
    """
    async def send_verification_email(self, recipient_email: str, verification_code: str):
        subject = f"【{settings.EMAILS_FROM_NAME}】请验证您的邮箱地址"
        body = f"""
        您好,

        感谢您注册 {settings.PROJECT_NAME}。
        您的邮箱验证码是: {verification_code}

        该验证码将在 {settings.EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES} 分钟后失效。

        如果您没有请求此验证码，请忽略此邮件。

        谢谢,
        {settings.EMAILS_FROM_NAME} 团队
        """
        
        print("\n--- MOCK EMAIL SERVICE ---")
        print(f"To: {recipient_email}")
        print(f"From: \"{settings.EMAILS_FROM_NAME}\" <{settings.EMAILS_FROM_EMAIL}>")
        print(f"Subject: {subject}")
        print("Body:")
        print(body.strip())
        print("--------------------------\n")

class RealEmailService(BaseEmailService):
    """
    使用 aiosmtplib 发送真实邮件的服务。
    """
    def __init__(self):
        # 在初始化时检查配置是否齐全
        required_settings = [
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            settings.SMTP_USER,
            settings.SMTP_PASSWORD,
            settings.EMAILS_FROM_EMAIL
        ]
        if not all(required_settings):
            raise ValueError(
                "Real email service is enabled, but some SMTP settings are missing in the configuration. "
                "Please set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and EMAILS_FROM_EMAIL."
            )
        print("INFO:     RealEmailService initialized.")

    async def send_verification_email(self, recipient_email: str, verification_code: str):
        subject = f"【{settings.EMAILS_FROM_NAME}】请验证您的邮箱地址"
        
        # 创建邮件消息对象
        message = EmailMessage()
        message["From"] = f"\"{settings.EMAILS_FROM_NAME}\" <{settings.EMAILS_FROM_EMAIL}>"
        message["To"] = recipient_email
        message["Subject"] = subject
        
        # 邮件正文 (HTML格式，更美观)
        html_body = f"""
        <html>
          <body>
            <p>您好,</p>
            <p>感谢您注册 {settings.PROJECT_NAME}。</p>
            <p>您的邮箱验证码是: <strong>{verification_code}</strong></p>
            <p>该验证码将在 {settings.EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES} 分钟后失效。</p>
            <p>如果您没有请求此验证码，请忽略此邮件。</p>
            <p>谢谢,<br>{settings.EMAILS_FROM_NAME} 团队</p>
          </body>
        </html>
        """
        message.set_content("This is a fallback for non-HTML email clients.")
        message.add_alternative(html_body, subtype="html")

        try:
            print(f"Attempting to send verification email to {recipient_email} via {settings.SMTP_HOST}...")
            # 建立异步SMTP连接并发送
            async with aiosmtplib.SMTP(
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                use_tls=True # 推荐始终使用TLS加密
            ) as smtp:
                await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                await smtp.send_message(message)
            print(f"Successfully sent verification email to {recipient_email}.")
        except aiosmtplib.SMTPException as e:
            print(f"ERROR: Failed to send email via SMTP. Error: {e.code} - {e.message}")
        except socket.gaierror:
            print(f"ERROR: Failed to send email. Could not resolve SMTP host: {settings.SMTP_HOST}")
        except Exception as e:
            print(f"ERROR: An unexpected error occurred while sending email: {e}")



def get_email_service() -> BaseEmailService:
    if settings.EMAIL_SERVICE_MODE == "real":
        return RealEmailService()
    return MockEmailService()

# 创建一个单例供整个应用使用
email_service: BaseEmailService = get_email_service()