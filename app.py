from fastapi import FastAPI, HTTPException
from typing import Dict, Any, Optional
from pydantic import BaseModel
from langgraph.types import Command

# Import từ các file của bạn
from db import get_application
from graph import graph

class CV_Request(BaseModel):
    application_id: str
    cv_text: str

class Review_Request(BaseModel):
    application_id: str
    approve: bool
    decision: str  
    reviewer_notes: Optional[str] = "" 
    edited_extracted: Optional[Dict[str, Any]] = None

app = FastAPI(title="CV Analysis API")

@app.post("/submit_cv")
def submit_cv(request: CV_Request) -> Dict[str, Any]:
    application_id = request.application_id
    config = {
        "configurable": {
            "thread_id": application_id
        }
    }
    
    # Giá trị khởi tạo
    initial_state = {
        "messages": [],
        "application_id": application_id,
        "cv_text": request.cv_text,
        "extracted": {},
        "score": 0,
        "flags": [],
        "needs_human": True,
        "decision": None,
        "reviewer_notes": ""
    }

    # Chạy graph
    # invoke sẽ trả về state cuối cùng (hoặc tại điểm interrupt)
    graph.invoke(initial_state, config=config)
    
    # Lấy snapshot mới nhất từ Thread
    snapshot = graph.get_state(config)
    
    status = "done"
    interrupt_payload = None

    # Kiểm tra xem graph có đang dừng chờ không
    if snapshot.next:
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            status = "waiting_review"
            # Lấy thông tin recommendation từ interrupt
            interrupt_payload = snapshot.tasks[0].interrupts[0].value
            
    # [SỬA 3]: Lấy dữ liệu từ snapshot.values để đảm bảo đầy đủ nhất
    # snapshot.values chứa toàn bộ state hiện tại của thread
    current_state = snapshot.values if snapshot else {}

    return {
        "status": status,
        "interrupt": interrupt_payload,
        "draft": {
            "score": current_state.get("score", 0),
            "flags": current_state.get("flags", []),
            "decision": current_state.get("decision", None),
            "extracted": current_state.get("extracted", {}),
            "reviewer_notes": current_state.get("reviewer_notes", "")
        }
    }

@app.post("/submit_review")
def submit_review(request: Review_Request) -> Dict[str, Any]:
    id = request.application_id
    config = {
        "configurable": {
            "thread_id": id
        }
    }
    
    # Kiểm tra xem có đang chờ review không (Optional - giúp debug tốt hơn)
    snapshot = graph.get_state(config)
    if not snapshot.next:
         # Trường hợp người dùng spam nút submit hoặc graph đã xong rồi
        return {"ok": False, "message": "Graph is not expecting a review (invalid state)"}

    resume_payload = {
        "approve": request.approve,
        "decision": request.decision, 
        "reviewer_notes": request.reviewer_notes or "",
        "edited_extracted": request.edited_extracted,
    }

    # Tiếp tục graph
    graph.invoke(Command(resume=resume_payload), config=config)
    
    # Lấy kết quả final từ DB
    app_row = get_application(id)
    return {
        "ok": True,
        "final": app_row
    }