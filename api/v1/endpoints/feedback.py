# FILE: ./api/v1/endpoints/feedback.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from db.session import get_db
from db import crud
from schemas import FeedbackCreate, UserInDB
from core.security import get_current_user

router = APIRouter()

@router.post("/", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    feedback_in: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """
    Receives and stores user feedback for a specific AI turn.
    """
    # 检查该 turn_id 是否已经提交过反馈，防止重复提交
    # 注意：这需要一个 get_feedback_by_turn_id 的 crud 函数
    # 为了简单起见，我们暂时依赖数据库的 unique 约束来处理重复
    try:
        await crud.create_feedback(db, feedback=feedback_in, owner_id=current_user.id)
        return {"status": "success", "message": "Feedback received successfully."}
    except Exception as e:
        # 这里的异常可能是因为 turn_id 已经存在（违反了 unique 约束）
        # 或者其他数据库错误
        print(f"Error saving feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback for this turn may already exist or a database error occurred."
        )