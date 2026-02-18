import warnings
warnings.filterwarnings("ignore")

import sqlite3
import os
import json
from dotenv import load_dotenv
from typing import Optional, Dict, Any, Annotated, List, Literal, TypedDict

from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, add_messages, END, START
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver


from db import upsert_application, update_analysis, set_decision, get_application

load_dotenv()

RUBRIC = {
    "required_skills": ["python", "sql"],
    "nice_to_have": ["langchain", "langgraph", "fastapi", "docker"],
    "weights": {
        "required_skills": 60,
        "nice_to_have": 30,
        "experience": 10,
    }
}

def _model():
    return ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.3
    )

class State(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    application_id: str
    cv_text: str
    extracted: Dict[str, Any]
    score: int
    flags: List[str]
    needs_human: bool
    decision: Optional[str]
    reviewer_notes: str

def extract_CV(state: State) -> dict:
     # LLM chỉ trích xuất JSON theo schema; tránh thu thập thuộc tính nhạy cảm
    sys = SystemMessage(content=(
        "Bạn là hệ thống trích xuất CV cho mục đích screening.\n"
        "Chỉ trích xuất thông tin LIÊN QUAN CÔNG VIỆC.\n"
        "Không trích xuất/không suy đoán tuổi, giới tính, tôn giáo, chủng tộc, tình trạng hôn nhân.\n"
        "Chỉ trả về JSON thuần (không markdown), không nói hay nhận xét gì thêm:\n"
        "{"
        "\"name\": str|null, "
        "\"email\": str|null, "
        "\"years_experience\": number|null, "
        "\"skills\": [str], "
        "\"roles\": [str], "
        "\"projects\": [str], "
        "\"education\": str|null"
        "}\n"
        "Nếu thiếu thì để null hoặc []."
        "Lưu ý chỉ trả về dạng JSON thuần, không giải thích gì thêm."
    ))

    ai = _model().invoke([sys] + [HumanMessage(content=state['cv_text'])])

    try:
        extracted=json.loads(ai.content)
    except Exception as e:
        print("Error parsing JSON:", e)
        extracted = {
            "name": None,
            "email": None,
            "years_experience": None,
            "skills": [],
            "roles": [],
            "projects": [],
            "education": None
        }
    return {
        "extracted": extracted,
        "messages": [ai]
    }

def score_application(state: State) -> dict:
    required_skills = RUBRIC["required_skills"]
    nice_to_have = RUBRIC["nice_to_have"]

    skills= [s.lower() for s in state['extracted'].get("skills", [])]
    req_hit=sum(1 for skill in required_skills if skill in skills)
    req_score= (req_hit / len(required_skills)) * RUBRIC["weights"]["required_skills"]    

    nice_hit=sum(1 for skill in nice_to_have if skill in skills)
    nice_score= (nice_hit / len(nice_to_have)) * RUBRIC["weights"]["nice_to_have"]

    years_exp = state['extracted'].get("years_experience", 0) or 0
    years_exp=float(years_exp)
    exp_score = 10 if years_exp >=2 else int((years_exp/2)*RUBRIC["weights"]["experience"])
    score= max(0, min(100, int(req_score + nice_score + exp_score)))
    return {
        "score": score
    }

def flags_node(state: State) -> dict:
    extracted=state['extracted']
    flags=[]
    skills= [s.lower() for s in extracted.get("skills", [])]

    missing_required = [skill for skill in RUBRIC["required_skills"] if skill not in skills]

    if missing_required:
        flags.append(f"Missing required skills: {', '.join(missing_required)}")
    
    if not extracted.get("email"):
        flags.append("Missing contact information")
    
    if len(extracted.get("roles", []))==0 and len(extracted.get("projects", []))==0:
        flags.append("Lacks detail on roles/projects")

    need_human=True # screening luôn yêu cầu human review (production-safe)
    return {
        "flags": flags,
        "needs_human": need_human
    }

def human_review(state: State) -> dict:
    payload={
        "application_id": state['application_id'],
        "score": state['score'],
        "flags": state['flags'],
        "extracted": state['extracted'],
        "recommendation": "Recommend for next round" if float(state['score']) >= 70 else "Do not recommend"
    }

    decision=interrupt(payload)
    approve=bool(decision.get("approve", False))
    final_decision=decision.get("decision", "Shortlist") if approve else "Rejected"
    edited=decision.get("edited_extracted")
    notes=decision.get("reviewer_notes", "")
    if isinstance(edited, dict):
        state['extracted']=edited
    
    return {
        "needs_human": not approve,
        "decision": final_decision if approve else "Rejected",
        "reviewer_notes": notes,
        "extracted": state['extracted']
    }

def persist_analysis_node(state: State) -> dict:
    update_analysis(
        application_id=state['application_id'],
        extracted=state['extracted'],
        score=state['score'],
        flags=state['flags']
    )
    return {}

def finalize_decision_node(state: State) -> dict:
    decision = state.get("decision")
    if not decision:
        decision = "Shortlist" if float(state.get("score", 0)) >= 70 else "Rejected"
    set_decision(state["application_id"], decision, state.get("reviewer_notes", ""))
    return {}


def route_after_review(state: State) -> dict:
    return "finalize_decision_node" if not state.get("needs_human", True) else END 

def upsert_node(state: State) -> dict:
    res=upsert_application(state['application_id'], state['cv_text'])
    return {
        "decision": res['decision']
    }


# Build graph

builder=StateGraph(State)
builder.add_node("extract_CV", extract_CV)
builder.add_node("score_application", score_application)
builder.add_node("flags_node", flags_node)
builder.add_node("human_review", human_review)
builder.add_node("persist_analysis_node", persist_analysis_node)
builder.add_node("finalize_decision_node", finalize_decision_node)
builder.add_node("upsert_node", upsert_node)

builder.add_edge(START, "upsert_node")
builder.add_edge("upsert_node", "extract_CV")
builder.add_edge("extract_CV", "score_application")
builder.add_edge("score_application", "flags_node")
builder.add_edge("flags_node", "human_review")
builder.add_edge("human_review", "persist_analysis_node")

builder.add_conditional_edges("persist_analysis_node", route_after_review, ["finalize_decision_node", END])
builder.add_edge("finalize_decision_node", END)

conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)  # có thể thêm check_same_thread=False nếu dùng thread
checkpointer = SqliteSaver(conn)

graph = builder.compile(checkpointer=checkpointer)

# # ------------------------- Demo run -------------------------
# cv_text_1 = """
# Nguyễn Văn A
# Email: 
# Kinh nghiệm: 3 năm Backend
# Kỹ năng:  SQL, FastAPI, Docker, LangGraph, LangChain
# Dự án: Xây hệ thống chatbot nội bộ, API cho ticketing
# """

# state_init_1 = {
#     "messages": [HumanMessage(content=cv_text_1)],  # để trace (nếu bạn cần)
#     "application_id": "app_001",
#     "cv_text": cv_text_1,         # node extract thường đọc từ đây
#     "extracted": {},              # sẽ được node extract ghi vào
#     "score": 0,                   # sẽ được score_node cập nhật
#     "flags": [],                  # sẽ được flags_node cập nhật
#     "needs_human": True,          # flow review-safe
#     "decision": None,             # sẽ có sau review
#     "reviewer_notes": "",
# }

# from langgraph.types import Command

# # ------------------------- SỬA LẠI PHẦN DEMO RUN -------------------------
# thread_id = state_init_1["application_id"]
# config = {"configurable": {"thread_id": thread_id}}

# print(f"--- Bắt đầu xử lý Application ID: {thread_id} ---")

# # Bước 1: Chạy graph đến điểm interrupt
# # Graph sẽ tự dừng lại khi gặp hàm interrupt() trong node human_review
# events = graph.stream(state_init_1, config=config)

# for ev in events:
#     # In ra các event để theo dõi tiến trình (tùy chọn)
#     for key, value in ev.items():
#         print(f"Node: {key}")

# # Bước 2: Kiểm tra xem graph có đang bị tạm dừng (interrupt) không và lấy payload
# snapshot = graph.get_state(config)

# if snapshot.next:
#     # Lấy thông tin interrupt từ snapshot
#     # tasks[0].interrupts là danh sách các interrupt active
#     if snapshot.tasks and snapshot.tasks[0].interrupts:
#         interrupt_payload = snapshot.tasks[0].interrupts[0].value
#         print("\n=== PHÁT HIỆN INTERRUPT ===")
#         print("Reviewer cần xem xét:", interrupt_payload)
        
#         # Bước 3: Giả lập Human Input
#         print("\n>>> Người dùng thực hiện review...")
#         # Thay vì hardcode, hãy cho phép nhập từ bàn phím
#         decision_input = input("Nhập quyết định (Shortlist/Rejected): ")
#         reviewer_notes = input("Nhập ghi chú của reviewer: ")
#         human_input = {
#             "approve": True,
#             "decision": decision_input,
#             "reviewer_notes": reviewer_notes
#         }

#         # Bước 4: Resume graph với Command
#         # Resume sẽ trả về giá trị human_input vào biến 'decision' trong hàm human_review
#         print(">>> Đang resume graph...")
#         result = graph.invoke(
#             Command(resume=human_input),
#             config=config,
#         )

#         print("\n=== KẾT QUẢ CUỐI CÙNG ===")
#         print("Decision:", result.get("decision"))
#         print("Final Score:", result.get("score"))
#     else:
#         print("Graph dừng nhưng không tìm thấy interrupt payload.")
# else:
#     print("Graph đã chạy xong mà không gặp interrupt (hoặc đã kết thúc).")