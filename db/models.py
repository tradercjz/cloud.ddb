import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

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
    
    spec_cpu = Column(Float)
    spec_memory = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    
    owner = relationship("User", back_populates="environments")