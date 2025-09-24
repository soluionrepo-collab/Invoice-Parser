from pydantic import BaseModel
from typing import Optional

class AzureResponseModel(BaseModel):
    content: str
    input_tokens: int
    output_tokens: int
    latency_seconds: Optional[float] = None

class SignupRequest(BaseModel):
    name: str
    password: str
    email: str
    
class LoginRequest(BaseModel):
    email: str
    password: str