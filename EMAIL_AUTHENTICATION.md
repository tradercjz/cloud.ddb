# 邮箱验证系统使用说明

## 概述

本项目实现了完整的用户注册和邮箱验证系统，新用户需要通过邮箱验证才能激活账户并登录。

## API 端点

### 1. 用户注册

**POST** `/api/v1/auth/register`

注册新用户并发送邮箱验证码。

**请求体:**
```json
{
  "username": "testuser",
  "email": "test@example.com", 
  "password": "password123"
}
```

**响应:**
```json
{
  "message": "Registration successful. Please check your email for verification code."
}
```

### 2. 发送验证码

**POST** `/api/v1/auth/send-verification`

重新发送邮箱验证码。

**请求体:**
```json
{
  "email": "test@example.com"
}
```

**响应:**
```json
{
  "message": "Verification code sent successfully."
}
```

### 3. 验证邮箱

**POST** `/api/v1/auth/verify-email`

使用验证码激活用户账户。

**请求体:**
```json
{
  "email": "test@example.com",
  "verification_code": "123456"
}
```

**响应:**
```json
{
  "message": "Email verified successfully. Your account is now active."
}
```

### 4. 用户登录

**POST** `/api/v1/auth/token`

用户登录（仅限已激活账户）。

**表单数据:**
- `username`: 用户名
- `password`: 密码

**响应:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer"
}
```

## 配置说明

在 `.env` 文件中配置邮件服务：

```bash
# Email Configuration
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com
EMAIL_VERIFICATION_EXPIRE_MINUTES=30
```

### 支持的邮件服务

- **Gmail**: 使用应用专用密码
- **Outlook/Hotmail**: 使用应用密码
- **其他 SMTP 服务**: 配置相应的服务器和端口

## 数据库表结构

### users 表
- `id`: 主键
- `username`: 用户名（唯一）
- `email`: 邮箱地址（唯一）
- `hashed_password`: 加密密码
- `is_active`: 激活状态 (0: 未激活, 1: 已激活)
- `created_at`: 创建时间

### email_verifications 表
- `id`: 主键
- `email`: 邮箱地址
- `verification_code`: 验证码
- `expires_at`: 过期时间
- `is_used`: 是否已使用 (0: 未使用, 1: 已使用)
- `created_at`: 创建时间

## 安全特性

1. **密码加密**: 使用 bcrypt 加密存储密码
2. **邮箱验证**: 必须通过邮箱验证才能登录
3. **验证码过期**: 验证码 30 分钟后自动过期
4. **单次使用**: 验证码只能使用一次
5. **重复注册检查**: 防止用户名和邮箱重复注册

## 测试

运行测试脚本：

```bash
python test_email_auth.py
```

## 故障排除

### 邮件发送失败
1. 检查 SMTP 配置是否正确
2. 确认邮箱服务商是否支持 SMTP
3. 检查防火墙和网络连接

### 验证码无效
1. 确认验证码是否过期（30分钟）
2. 检查验证码是否已使用
3. 确认邮箱地址是否正确

### 用户无法登录
1. 确认用户是否已完成邮箱验证
2. 检查用户名和密码是否正确
3. 确认账户是否被激活