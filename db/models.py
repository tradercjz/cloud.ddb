import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    environments = relationship("Environment", back_populates="owner", cascade="all, delete-orphan")

class Environment(Base):
    __tablename__ = "environments"
    id = Column(String, primary_key=True, default=lambda: f"ddb-env-{uuid.uuid4().hex[:8]}")
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    status = Column(String, default="PENDING", index=True)
    message = Column(String, nullable=True)
    
    container_group_id = Column(String, nullable=True, unique=True)
    region_id = Column(String)
    public_ip = Column(String, nullable=True)
    port = Column(Integer, default=8848)
    
    code_server_group_id = Column(String, nullable=True, unique=True) # code-server ECI 的 ID
    code_server_public_ip = Column(String, nullable=True)            # code-server ECI 的公网 IP
    code_server_port = Column(Integer, default=8080)                 # code-server 服务的端口
    
    spec_cpu = Column(Float)
    spec_memory = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    
    owner = relationship("User", back_populates="environments")
    
class Feedback(Base):
    __tablename__ = "feedback"
    
    id = Column(Integer, primary_key=True, index=True)
    turn_id = Column(String, index=True, nullable=False, unique=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    feedback_type = Column(String, nullable=False) # 'like' or 'dislike'
    prompt = Column(String, nullable=False)
    response = Column(String, nullable=False)
    
    # Use JSON type for conversation history. 
    # If using PostgreSQL, JSONB is more efficient.
    # For SQLite or MySQL, JSON is a good choice.
    conversation_history = Column(JSON, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    owner = relationship("User")