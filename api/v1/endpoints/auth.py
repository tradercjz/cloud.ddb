import random
import string
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from db import crud
from db.session import get_db
from core.security import create_access_token, verify_password
from schemas import Token, UserCreate 
from schemas import Token, UserRegister, EmailVerificationRequest, ResendVerificationRequest
from services.email_service import email_service
from datetime import timedelta, datetime

router = APIRouter()

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    user_in: UserRegister,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Handles user registration.
    Creates a new, inactive user and sends a verification email.
    """
    user = await crud.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    
    # 创建非活动用户
    new_user = await crud.create_user(db, user=user_in)
    
    # 生成验证码
    verification_code = ''.join(random.choices(string.digits, k=6))
    await crud.create_verification_code(db, user_id=new_user.id, code=verification_code)
    
    # 使用后台任务发送邮件，避免阻塞API
    email_to_send = user_in.email
    
    background_tasks.add_task(
        email_service.send_verification_email, # 使用工厂实例
        recipient_email=email_to_send,
        verification_code=verification_code
    )
    
    return {"message": "Registration successful. Please check your email for a verification code."}


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    verification_data: EmailVerificationRequest,
    db: Session = Depends(get_db)
):
    """
    Verifies a user's email address with a code.
    """
    db_code = await crud.get_verification_code(db, email=verification_data.email, code=verification_data.code)
    
    if not db_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code."
        )
        
    user = await crud.get_user_by_email(db, email=verification_data.email)
    if not user or user.id != db_code.user_id:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
         
    if user.is_active:
        return {"message": "Account is already active."}

    # Immediately extract the ID we need into a simple integer variable
    # before we do anything that might commit the session.
    code_id_to_delete = db_code.id

    # This line commits the session and expires the original 'db_code' object.
    await crud.activate_user(db, user=user)
    
    # Now we use the safe, simple integer variable. This will not trigger any lazy-loading.
    await crud.delete_verification_code(db, code_id=code_id_to_delete)
    
    return {"message": "Your account has been successfully activated. You can now log in."}


@router.post("/token", response_model=Token)
async def login_for_access_token(
    db: Session = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends()
):
    # 注意: OAuth2PasswordRequestForm 使用 'username' 字段，我们在这里把它当作 email
    user = await crud.get_user_by_email(db, email=form_data.username)
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")
        
    # 关键检查: 确保用户已激活
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not activated. Please verify your email first."
        )
        
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/resend-verification-email", status_code=status.HTTP_200_OK)
async def resend_verification_email(
    request: ResendVerificationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Resend the verification email to a user.
    Includes rate limiting to prevent abuse.
    """
    user = await crud.get_user_by_email(db, email=request.email)
    
    if not user:
        # 出于安全考虑，即使邮箱不存在，也返回一个通用的成功消息
        # 这样可以防止攻击者用这个接口来探测哪些邮箱已经被注册
        return {"message": "If an account with this email exists, a new verification email has been sent."}

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is already active."
        )
        
    user_id_to_use = user.id
    email_to_send = user.email

    # 速率限制检查
    latest_code = await crud.get_latest_verification_code_for_user(db, user_id=user.id)
    if latest_code and (datetime.utcnow() - latest_code.created_at) < timedelta(minutes=1):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You can request a new code once per minute. Please wait."
        )

    await crud.delete_all_verification_codes_for_user(db, user_id=user_id_to_use)

    new_code = ''.join(random.choices(string.digits, k=6))
    # Use the safe variable again.
    await crud.create_verification_code(db, user_id=user_id_to_use, code=new_code)
    
    background_tasks.add_task(
        email_service.send_verification_email,
        recipient_email=email_to_send, # Use the safe variable here too.
        verification_code=new_code
    )
    
    return {"message": "A new verification email has been sent."}