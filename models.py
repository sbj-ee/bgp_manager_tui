# models.py
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class BGPSession(Base):
    __tablename__ = "bgp_sessions"

    id = Column(Integer, primary_key=True)
    neighbor_ip = Column(String(45), unique=True, nullable=False)
    remote_as = Column(Integer, nullable=False)
    local_as = Column(Integer, nullable=False, default=0)
    local_ip = Column(String(45), nullable=False, default="")
    description = Column(String(255), default="")
    device_fqdn = Column(String(255), nullable=False)  # <-- NEW
    device_type = Column(String(50), nullable=False)
    status = Column(String(10), default="Unknown")
    session_state = Column(String(20), default="Unknown")
    last_updated = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<BGPSession {self.neighbor_ip} AS{self.remote_as} [{self.status}]>"
