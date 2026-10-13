"""
기계공학 실습 도우미 (실습 장비 사용 전 안전 점검 도구)
실행 방법:  python3 -m streamlit run app.py

학생: 초대 코드와 조를 골라 입장 -> 쓸 장비 고르기(사진 또는 목록)
      -> 사용 전 점검표 체크 -> 준비 상태 사진을 AI가 확인 -> 작업 -> 마무리 점검
교수: 수업 만들기(장비 목록, 초대 코드) -> 조별 점검 현황 보기, 점검표 수정
"""

import base64
import hashlib
import json
import random
import re
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from google import genai
from google.genai import types

# ------------------------------------------------------------
# 1. 기본 설정
# ------------------------------------------------------------
MODEL = "gemini-3.8-flash"  # 기본 모델. 붐비면 다른 모델로 자동으로 넘어간다.

HERE = Path(__file__).parent
RULES_FILE = HERE / "safety_rules.txt"   # 안전수칙 (메모장으로 수정 가능)
DATA_FILE = HERE / "classes.json"        # 수업, 학생, 진행 기록
GUIDE_FILE = HERE / "outfit_guide.svg"  # 복장 점검 촬영 예시 그림
MODEL_FILE = HERE / "model.txt"          # 관리자가 고른 모델 이름
KEY_FILE = HERE / "api_key.txt"          # 이 컴퓨터에 저장한 API 키 (남에게 주거나 깃허브에 올리면 안 됨)
SAFETY_RULES = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""

# 장비별 사용 전 점검표. 메모장으로 열어서 문장을 고치거나 장비를 추가할 수 있다.
CHECKLISTS = {
    "선반": [
        "장갑을 벗었고, 소매와 옷자락을 정리했다 (긴 머리는 묶었다)",
        "보안경을 썼다",
        "척 핸들을 척에서 뺐다",
        "공작물과 바이트가 단단히 고정됐다",
        "손으로 척을 한 바퀴 돌려서 걸리는 곳이 없는지 확인했다",
        "회전 속도와 이송 레버 위치를 확인했다",
    ],
    "밀링머신": [
        "장갑을 벗었고, 소매와 옷자락을 정리했다 (긴 머리는 묶었다)",
        "보안경을 썼다",
        "공작물이 바이스나 클램프에 단단히 고정됐다",
        "커터가 단단히 고정됐고 날이 깨지지 않았다",
        "테이블 위에 공구나 측정기가 남아 있지 않다",
        "이송 방향과 절삭 깊이를 확인했다",
    ],
    "탁상 드릴링머신": [
        "장갑을 벗었고, 소매와 옷자락을 정리했다 (긴 머리는 묶었다)",
        "보안경을 썼다",
        "공작물을 바이스나 클램프로 고정했다 (손으로 잡지 않는다)",
        "드릴 척 키를 척에서 뺐다",
        "드릴 날이 휘거나 무뎌지지 않았다",
        "얇은 판재라면 밑에 나무판을 받쳤다",
    ],
    "탁상 그라인더": [
        "보안경이나 보안면을 썼다",
        "장갑을 벗었고, 소매와 옷자락을 정리했다",
        "숫돌에 금이 가거나 깨진 곳이 없다",
        "받침대와 숫돌 사이 간격이 3mm 이내다",
        "숫돌 덮개와 보호판이 제자리에 있다",
        "켠 뒤 1분은 숫돌 정면을 피해 옆에 서서 공회전시킨다",
    ],
    "핸드 그라인더": [
        "보안면(또는 보안경), 장갑, 귀마개를 착용했다",
        "보호덮개가 붙어 있다",
        "디스크에 금이 없고 단단히 조여져 있다",
        "전선 피복이 벗겨진 곳이 없다",
        "불꽃이 튀는 방향에 사람과 불붙을 물건이 없다",
        "공작물이 움직이지 않게 고정됐다",
    ],
    "띠톱 기계": [
        "보안경을 썼고, 소매와 옷자락을 정리했다",
        "재료가 바이스에 단단히 고정됐다",
        "톱날이 팽팽하고 이가 빠지거나 금 간 곳이 없다",
        "톱날 덮개와 가이드가 제자리에 있다",
        "톱날이 지나가는 선 위에 손이 놓이지 않는다",
        "절삭유가 나오는지 확인했다",
    ],
    "고속절단기": [
        "보안경과 귀마개를 착용했다",
        "재료가 바이스에 단단히 고정됐다",
        "절단석에 금이 가거나 깨진 곳이 없다",
        "보호덮개가 제자리에 있다",
        "불꽃이 튀는 방향에 사람과 불붙을 물건이 없다",
        "소매와 옷자락을 정리했다",
    ],
    "아크 용접기": [
        "용접면, 용접 장갑, 앞치마를 착용했다 (긴소매 면 소재 옷)",
        "주변에 종이, 기름, 걸레, 스프레이 같은 불붙을 물건이 없다",
        "환기장치를 켰다",
        "케이블 피복이 벗겨진 곳이 없고 접지 클램프를 물렸다",
        "손과 장갑, 바닥이 젖어 있지 않다",
        "소화기 위치를 확인했다",
        "주변 사람에게 용접 시작을 알렸다 (불빛을 직접 보지 않게)",
    ],
    "가스 용접기": [
        "보안경(차광), 장갑, 앞치마를 착용했다",
        "가스 용기가 세워진 채 고정돼 있다",
        "호스와 연결부에서 가스가 새지 않는다 (비눗물 점검)",
        "역화방지기가 달려 있다",
        "밸브와 호스에 기름이 묻어 있지 않다",
        "주변에 불붙을 물건이 없고 소화기 위치를 확인했다",
    ],
    "CNC 선반": [
        "문(도어)이 닫히고 인터록이 작동한다",
        "공작물과 공구가 단단히 고정됐다",
        "원점과 공구 보정값을 확인했다",
        "프로그램을 확인했고, 처음에는 속도를 낮춰서 돌린다",
        "기계 안에 공구나 걸레가 남아 있지 않다",
    ],
    "머시닝센터": [
        "문(도어)이 닫히고 인터록이 작동한다",
        "공작물이 바이스나 지그에 단단히 고정됐다",
        "원점과 공구 길이 보정값을 확인했다",
        "프로그램을 확인했고, 처음에는 속도를 낮춰서 돌린다",
        "테이블 위에 공구나 측정기가 남아 있지 않다",
    ],
    "유압 프레스": [
        "보안경을 썼다",
        "공작물과 받침이 램 중심에 똑바로 놓였다",
        "가동부(램과 테이블 사이)에 손이 들어가지 않는다",
        "유압 호스와 연결부에서 기름이 새지 않는다",
        "압력 게이지를 확인했고 허용 압력을 넘기지 않는다",
        "주변 사람이 가동부에서 떨어져 있다",
    ],
    "공기 압축기": [
        "탱크의 물을 빼냈다 (드레인)",
        "압력계와 안전밸브가 정상이다",
        "호스와 연결부가 단단히 끼워져 있다",
        "에어건을 사람 쪽으로 향하지 않는다",
        "보안경을 썼다",
    ],
    "3D프린터": [
        "노즐과 베드가 뜨겁다는 것을 알고, 가동 중에는 만지지 않는다",
        "베드 위에 남은 출력물이나 이물질이 없다",
        "필라멘트가 엉키지 않고 제대로 끼워져 있다",
        "환기가 되는 상태다",
    ],
    "레이저 가공기": [
        "덮개가 닫히고 인터록이 작동한다",
        "가공할 재료가 허용된 재료다 (PVC 등 유독가스가 나오는 재료가 아니다)",
        "집진기(배기)를 켰다",
        "가공 중에는 자리를 비우지 않는다",
        "소화기 위치를 확인했다",
    ],
}

# 모든 장비에 공통으로 붙는 항목
COMMON_CHECKS = [
    "비상정지 버튼(또는 전원 스위치) 위치를 확인했다",
    "조교나 교수님이 실습실에 계신다",
]

# 점검표가 없는 장비에서 AI도 쓸 수 없을 때 쓰는 기본 항목
GENERIC_CHECKS = [
    "이 장비의 사용법을 교육받았다",
    "필요한 보호구를 착용했고, 소매와 옷자락을 정리했다",
    "공작물과 공구가 단단히 고정됐다",
    "안전덮개가 제자리에 있고 장비에 이상이 없다",
    "주변이 정리돼 있고 작업 반경 안에 사람이 없다",
]

DEFAULT_TOOLS = list(CHECKLISTS)

CHECK_PROMPT = """
대학교 기계공학과 실습실에서 '{tool}'을(를) 사용하기 직전에 학생이 확인해야 할 안전 점검 항목을 만들어줘.
- 5~6개, 한 줄에 하나씩, 각 줄은 '- '로 시작한다.
- "~했다", "~이다"처럼 학생이 체크할 수 있는 완료형 문장으로 쓴다.
- 그 장비에서 실제로 사고가 나는 원인을 막는 항목만 쓴다. 다른 설명은 쓰지 않는다.
"""

# 작업이 끝난 뒤 하는 마무리 점검 (모든 장비 공통)
END_CHECKS = [
    "전원을 껐고, 회전하던 부분이 완전히 멈췄다",
    "공작물과 공구를 장비에서 빼냈다",
    "칩과 가루를 브러시로 치웠다 (손이나 입으로 치우지 않았다)",
    "쓴 공구와 측정기를 제자리에 뒀다",
    "바닥의 기름, 절삭유, 칩을 치웠다",
    "작업 중 이상이 있었다면 조교나 교수님께 알렸다",
]

# 장비에 따라 마무리 점검에 더 붙는 항목
END_EXTRA = {
    "아크 용접기": ["용접기 전원을 껐고 홀더를 절연된 곳에 뒀다", "주변에 남은 불씨가 없는지 확인했다"],
    "가스 용접기": ["가스 용기 밸브를 잠갔고 호스의 잔압을 뺐다", "주변에 남은 불씨가 없는지 확인했다"],
    "핸드 그라인더": ["전원 플러그를 뽑았다", "주변에 남은 불씨가 없는지 확인했다"],
    "고속절단기": ["주변에 남은 불씨가 없는지 확인했다"],
    "공기 압축기": ["전원을 끄고 탱크의 압력과 물을 빼냈다"],
    "유압 프레스": ["램을 올려두고 압력을 풀었다"],
    "레이저 가공기": ["가공물이 식은 뒤 꺼냈고, 안에 남은 조각이 없다"],
}

SETUP_PROMPT = """
학생이 '{tool}'을(를) 쓰기 직전에 작업 준비를 마친 모습을 찍은 사진이다. 사진이 여러 장이면 모두 본다.
아래 [점검 항목] 중에서 사진으로 확인할 수 있는 것만 판단해줘. 보이지 않는 것을 추측하지 않는다.

각 항목을 한 줄씩, 아래 표시 중 하나로 시작해서 쓴다.
✅ 사진에서 문제없어 보임
❌ 사진에서 문제가 보임 (무엇이 어떻게 문제인지 한 문장)
❓ 사진으로는 알 수 없음

그다음 '### 그 밖에 보이는 위험' 아래에, 항목에 없더라도 사진에 보이는 분명한 위험을 적는다.
(예: 척에 꽂힌 채 남은 핸들, 테이블 위에 놓인 공구, 떼어 놓은 안전덮개, 바닥의 기름, 가까이 있는 불붙을 물건)
없으면 '없음'이라고 쓴다.

맨 마지막 줄은 정확히 아래 셋 중 하나로 쓴다.
판정: 이상 없음   (❌가 하나도 없고, 그 밖의 위험도 없을 때)
판정: 문제 발견   (❌가 하나라도 있거나, 그 밖의 위험이 있을 때)
판정: 확인 어려움 (사진이 '{tool}'이(가) 아니거나, 너무 흐리거나 멀어서 거의 판단할 수 없을 때)

[점검 항목]
{items}
"""

SYSTEM_PROMPT = f"""
너는 대학교 기계공학과 실습실의 도우미다.
상대는 실습이 처음인 1학년 학생이므로 쉬운 한국어로 짧고 분명하게 답한다.

규칙:
- 아래 [실습실 안전수칙]을 가장 우선해서 답한다.
- 사진에서 확실하지 않은 것은 추측하지 말고 "사진으로는 확인이 어렵다"고 말한다.
- 위험할 수 있는 작업은 반드시 조교나 교수님께 확인하라고 안내한다.
- 답은 정해진 형식을 지킨다.
- 존댓말(해요체)로 답하고, 형식에서 정한 표시(✅ ❌ ❓) 말고는 이모지를 쓰지 않는다.

[실습실 안전수칙]
{SAFETY_RULES}
"""

TOOL_PROMPT = """
사진 속 실습실 장비 또는 공구를 알려줘. 사진이 여러 장이면 같은 물건을 다른 각도에서 찍은 것이니 모두 보고 판단해. 아래 형식으로 답해.

### 이름
(한국어 이름 / 영어 이름)

### 어디에 쓰는지
(1~2문장)

### 주요 구조
(주요 부분 3~5개와 각각의 역할을 한 줄씩)

### 기본 사용법
(3단계 이내)

### 자주 나는 사고
(2~3개)

장비나 공구가 아니거나 알아볼 수 없으면 '### 이름' 아래에 '알 수 없음'이라고 쓰고, 다시 찍는 방법을 알려줘.

맨 마지막에는 정확히 아래 형식으로 세 줄을 덧붙여.
확신: 높음 또는 낮음
추가촬영: (확신이 낮을 때만, 어느 방향이나 어느 부분을 더 찍으면 좋을지 한 문장. 높으면 '없음')
과제장비: X
- 확신은 이름을 틀릴 가능성이 조금이라도 있으면 '낮음'으로 쓴다. 흐리거나, 일부만 보이거나, 비슷하게 생긴 다른 장비와 구별이 안 될 때가 그렇다.
- X는 다음 목록 중 사진 속 장비와 같은 것 하나를 글자 그대로 쓴다. 목록에 없으면 '없음'이라고 쓴다.
목록: {tools}
"""

OUTFIT_PROMPT = """
사진 속 사람이 '{work}' 작업을 하려고 한다. 복장과 보호구를 점검해줘.
사진이 여러 장이면 같은 사람을 다르게 찍은 것이니 모두 보고 판단해.
아래 항목을 각각 ✅(적합) / ❌(부적합) / ❓(사진으로 확인 어려움) 으로 표시하고 이유를 한 줄로 써.

- 보안경
- 장갑 (회전하는 기계에서는 장갑을 끼면 안 된다는 점을 작업 종류에 맞게 판단)
- 소매, 옷자락
- 머리카락
- 장신구 (반지, 시계, 목걸이, 이어폰)
- 신발

마지막 줄에 **작업 가능** 또는 **작업 전 수정 필요** 중 하나로 결론을 써.
"""


# ------------------------------------------------------------
# 2. 수업과 진행 기록 저장
#    classes.json 구조: {초대코드: {name, tools, pw, checks: {장비: [AI가 만든 점검 항목]},
#                                  teams: {"1조": {members: [이름], found: {장비: 기록}}}}}
#      기록 = {time, by, photo, end: {time, by}}
#        time, by : 사용 전 점검을 마친 시각과 사람
#        photo    : 준비 상태 사진 확인 결과 ("AI 확인" / "문제 발견 후 조치" / "사진 확인 없음")
#        end      : 마무리 점검을 마친 시각과 사람 (없으면 아직 작업 중)
#      checks[장비] = {items: [점검 항목], source: "prof"(교수가 수정) 또는 "ai"(AI가 만듦)}
#    점검 기록은 학생 개인이 아니라 조 단위로 남는다. (조원 한 명이 점검을 마치면 그 조가 점검한 것)
# ------------------------------------------------------------
@st.cache_resource
def file_lock():
    """여러 명이 동시에 저장해도 파일이 꼬이지 않게 하는 자물쇠."""
    return threading.Lock()


def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def change_data(change):
    """파일을 읽고 -> change(data)로 고치고 -> 다시 저장한다."""
    with file_lock():
        data = load_data()
        result = change(data)
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return result


def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def create_class(name: str, tools: list, pw: str, team_count: int) -> str:
    def change(data):
        while True:
            code = "MJ-" + str(random.randint(1000, 9999))
            if code not in data:
                break
        teams = {f"{i}조": {"members": [], "found": {}} for i in range(1, team_count + 1)}
        data[code] = {"name": name, "tools": tools, "pw": hash_pw(pw), "teams": teams}
        return code
    return change_data(change)


def join_class(code: str, team: str, name: str):
    """조원 명단에 이름을 올린다. (이미 있으면 그대로)"""
    def change(data):
        members = data[code]["teams"][team]["members"]
        if name not in members:
            members.append(name)
    change_data(change)


def now_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M")   # 어디서 돌려도 한국 시간으로 기록


def mark_checked(code: str, team: str, tool: str, name: str, photo: str) -> str:
    """이 조가 이 장비의 사용 전 점검을 마쳤다고 기록한다. (새 작업의 시작이므로 이전 마무리 기록은 지워진다)"""
    now = now_text()

    def change(data):
        data[code]["teams"][team]["found"][tool] = {"time": now, "by": name, "photo": photo}
    change_data(change)
    return now


def mark_end(code: str, team: str, tool: str, name: str) -> str:
    """이 조가 이 장비의 마무리 점검을 마쳤다고 기록한다."""
    now = now_text()

    def change(data):
        data[code]["teams"][team]["found"][tool]["end"] = {"time": now, "by": name}
    change_data(change)
    return now


def save_checklist(code: str, tool: str, items, source: str = "prof"):
    """수업의 점검표를 저장한다. items가 None이면 저장된 것을 지워서 기본 점검표로 되돌린다."""
    def change(data):
        checks = data[code].setdefault("checks", {})
        if items is None:
            checks.pop(tool, None)
        else:
            checks[tool] = {"items": items, "source": source}
    change_data(change)


# ------------------------------------------------------------
# 3. AI에게 사진을 보내고 답을 받는 부분
# ------------------------------------------------------------
def get_api_key() -> str:
    """키를 찾는 순서: 배포 설정(secrets) -> 이 컴퓨터에 저장한 파일."""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return key


@st.cache_data(ttl=600, show_spinner=False)
def list_models(api_key: str) -> list:
    """내 키로 쓸 수 있는 Gemini 모델 이름 목록. (실패하면 오류가 나고, 오류는 저장되지 않는다)"""
    skip = ["tts", "image", "live", "audio", "embedding", "native", "aqa", "robotics", "computer"]
    found = []
    client = genai.Client(api_key=api_key)   # 목록을 다 읽을 때까지 연결을 유지해야 한다.
    for m in client.models.list():
        name = (m.name or "").replace("models/", "")
        if "gemini" in name and not any(w in name for w in skip):
            found.append(name)
    return sorted(set(found), reverse=True)


def model_order(api_key: str) -> list:
    """시도할 모델 순서: 관리자가 고른 모델 -> lite 모델 -> 기본 모델 -> 다른 flash 모델.
    무료 사용량은 모델마다 따로 세기 때문에, 하나를 다 쓰면 다음 모델로 넘어가면 된다."""
    try:
        found = list_models(api_key)
    except Exception:
        found = []
    picked = [MODEL_FILE.read_text(encoding="utf-8").strip()] if MODEL_FILE.exists() else []
    lite = [n for n in found if "flash-lite" in n]
    flash = [n for n in found if "flash" in n and "lite" not in n]
    order = []
    for name in picked + lite[:3] + [MODEL] + flash[:3]:
        if name and name not in order:
            order.append(name)
    return order


@st.cache_resource
def answer_cache() -> dict:
    """같은 사진과 같은 질문은 AI에게 다시 묻지 않고 지난 답을 돌려주기 위한 저장소. (사용량 절약)"""
    return {}


def ask_ai(images: list, prompt: str) -> str:
    """images는 (사진 데이터, 종류) 묶음의 목록."""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("API 키가 등록되지 않았습니다. 첫 화면의 '설정' 탭에서 키를 등록해 주세요.")
    fingerprint = hashlib.sha256(prompt.encode("utf-8") + b"".join(b for b, _ in images)).hexdigest()
    cache = answer_cache()
    if fingerprint in cache:
        return cache[fingerprint]
    client = genai.Client(api_key=api_key)
    tried, last_error = [], None
    for model in model_order(api_key):
        tried.append(model)
        for _ in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[types.Part.from_bytes(data=b, mime_type=m) for b, m in images] + [prompt],
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
                )
                if not response.text:
                    raise RuntimeError("AI가 답을 보내지 않았습니다. 다른 사진으로 다시 시도해 주세요.")
                if len(cache) >= 300:          # 너무 많이 쌓이면 비운다
                    cache.clear()
                cache[fingerprint] = response.text
                return response.text
            except Exception as e:
                last_error = e
                text = str(e)
                if "429" in text:                    # 이 모델의 사용량을 다 씀: 바로 다음 모델로
                    break
                if "503" in text:                    # 붐빔: 잠깐 쉬고 한 번 더
                    time.sleep(3)
                    continue
                if "404" in text or "400" in text:   # 이 모델은 못 씀: 다음 모델로
                    break
                raise
    if "429" in str(last_error):
        raise RuntimeError("오늘 사용할 수 있는 AI 요청 횟수를 모두 사용했습니다. 내일 다시 시도하거나 관리자에게 알려 주세요. "
                           f"(시도한 모델: {', '.join(tried)})")
    raise RuntimeError(f"AI 요청에 실패했습니다. (시도한 모델: {', '.join(tried)}) {last_error}")


def analyze(photos: list, prompt: str):
    """사진(1장 이상)을 분석해서 답을 돌려준다. 실패하면 None."""
    if not photos:
        st.warning("사진을 먼저 추가해 주세요.")
        return None
    with st.spinner("사진을 확인하는 중입니다..."):
        try:
            return ask_ai([(p.getvalue(), p.type or "image/jpeg") for p in photos], prompt)
        except Exception as e:
            st.error(f"요청을 처리하지 못했습니다. {e}")
            return None


def get_photo(key: str, multi: bool = False) -> list:
    """사진을 받아서 목록으로 돌려준다. multi=True면 최대 3장까지 받는다."""
    how = st.radio("사진 추가 방법", ["사진 선택", "카메라로 촬영"], horizontal=True, key=f"{key}_how",
                   label_visibility="collapsed")
    if how == "카메라로 촬영":
        shot = st.camera_input("촬영", key=f"{key}_cam", label_visibility="collapsed")
        photos = [shot] if shot else []
    else:
        label = "사진 1장"
        if multi:
            label = "사진 최대 3장 (여러 각도에서 찍으면 더 정확합니다)"
        picked = st.file_uploader(label, type=["jpg", "jpeg", "png", "webp"],
                                  accept_multiple_files=multi, key=f"{key}_file")
        photos = list(picked or []) if multi else ([picked] if picked else [])
    if len(photos) > 3:
        st.warning("사진은 3장까지만 사용합니다.")
        photos = photos[:3]
    if photos:
        st.image(photos, width=200)
    return photos


def read_answer(answer: str, tools: list):
    """AI 답 끝의 '확신 / 추가촬영 / 과제장비' 줄을 읽는다.
    돌려주는 것: (화면에 보여줄 답, 일치한 과제 장비 또는 None, 확신이 높은지, 추가 촬영 안내)"""
    def line(label):
        found = re.search(label + r"\s*[:：]\s*(.+)", answer)
        return found.group(1).strip(" *`") if found else ""

    shown = re.sub(r"\n?.*(확신|추가\s*촬영|과제\s*장비)\s*[:：].*", "", answer).strip()
    sure = "높음" in line("확신")
    tip = line(r"추가\s*촬영")
    if tip in ("없음", ""):
        tip = "전체 모양이 보이도록 다른 방향에서 한 장 더 촬영해 주세요."
    said = re.sub(r"[\s*`'\"\[\]()]", "", line(r"과제\s*장비"))
    matched = next((t for t in tools if t.replace(" ", "") == said), None)
    return shown, matched, sure, tip


def get_checklist(code: str, tool: str, allow_ai: bool = True):
    """장비의 사용 전 점검 항목과 출처를 돌려준다. (공통 항목은 빼고)
    찾는 순서: 1) 이 수업에 저장된 점검표(교수가 수정했거나 AI가 만든 것)  2) 미리 만들어 둔 점검표
              3) AI에게 새로 요청  4) 기본 항목
    출처: "prof" 교수가 수정 / "ai" AI가 만듦 / "basic" 미리 만들어 둔 것 / "generic" 기본 항목"""
    saved = load_data().get(code, {}).get("checks", {}).get(tool)
    if isinstance(saved, list):          # 예전 형식
        saved = {"items": saved, "source": "ai"}
    if saved and saved.get("items"):
        return saved["items"], saved.get("source", "prof")
    if tool in CHECKLISTS:
        return CHECKLISTS[tool], "basic"
    if allow_ai:
        try:
            with st.spinner(f"{tool} 점검표를 준비하는 중입니다..."):
                text = ask_ai([], CHECK_PROMPT.format(tool=tool))
            items = [line.strip()[1:].strip() for line in text.splitlines() if line.strip().startswith("-")][:6]
            if len(items) >= 3:
                save_checklist(code, tool, items, "ai")   # 같은 수업의 모든 조가 같은 점검표를 보도록 저장
                return items, "ai"
        except Exception:
            pass
    return GENERIC_CHECKS, "generic"


def read_verdict(answer: str) -> str:
    """준비 상태 사진 확인 답의 마지막 '판정' 줄을 읽는다."""
    found = re.search(r"판정\s*[:：]\s*(.+)", answer)
    said = found.group(1) if found else ""
    if "이상 없음" in said:
        return "이상 없음"
    if "문제" in said:
        return "문제 발견"
    return "확인 어려움"



# ------------------------------------------------------------
# 4. 화면 꾸미기 (글꼴, 색, 카드 모양)
#    색: 흰색 · 검정 · 파랑(#2F6BD0) · 초록(#2E8A3C)
#    글꼴: 애플 시스템 글꼴(SF Pro, Apple SD Gothic Neo), 없으면 Pretendard
# ------------------------------------------------------------
BLUE, GREEN, RED, YELLOW = "#2F6BD0", "#3FA34D", "#E0483E", "#E3B23C"

STYLE = """
<style>
/* 디자인 기준
   - 글꼴: 애플 시스템 글꼴, 크기는 1.25배 간격(13 · 16 · 20 · 25 · 31px)
   - 여백: 4의 배수(4 · 8 · 12 · 16 · 24 · 32px)
   - 회색: 파랑이 살짝 섞인 회색, 글자 대비 4.5:1 이상
   - 그림자 · 그라데이션 · 카드 겹치기 없이, 흰 면과 얇은 선으로만 구분 */
:root {
  --bg: #F2F4F8; --surface: #FFFFFF; --line: #E2E6ED; --fill: #E8ECF2;
  --text: #161A22; --text2: #4A5363; --text3: #5F6878;
  --blue: #2F6BD0; --blue-d: #2558B0; --blue-soft: #E8EFFB;
  --green: #2E8A3C; --green-soft: #E6F3E8; --red: #C9372D; --red-soft: #FBE9E7;
  --amber: #9A6F00; --amber-soft: #FBF1D6;
}
.stApp, .stApp p, .stApp label, .stApp li, .stApp td, .stApp th, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5,
.stApp button, .stApp input, .stApp textarea, .stMarkdown, .stMarkdown div, .stMarkdown span:not([data-testid]) {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Apple SD Gothic Neo', 'Pretendard', system-ui, 'Noto Sans KR', sans-serif;
  -webkit-font-smoothing: antialiased; letter-spacing: -0.01em;
}
.num { font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.stApp { background: var(--bg); color: var(--text); }
.stApp p { line-height: 1.5; }
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"], footer,
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
.block-container { max-width: 560px; padding: 24px 16px 64px 16px; }
*:focus-visible { outline: 2px solid var(--blue) !important; outline-offset: 2px; }

/* 흰 면 */
.card, .st-key-entry, [data-testid="stExpander"] {
  background: var(--surface); border-radius: 16px; border: none; box-shadow: none; }
.card { padding: 16px; margin-bottom: 16px; }
.st-key-entry { padding: 16px 16px 24px 16px; }
[data-testid="stExpander"] details { border: none; }
[data-testid="stExpander"] summary { padding: 12px 16px; min-height: 48px; font-weight: 600; }
.ctitle { font-weight: 600; font-size: 1rem; }
.muted { color: var(--text3); font-size: 0.8rem; line-height: 1.4; }
.label { color: var(--text3); font-size: 0.8rem; font-weight: 600; margin: 24px 4px 8px 4px; }

/* 맨 위: 이름 */
.st-key-head { margin: 0 0 16px 0; }
.st-key-head [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 12px; }
.st-key-head [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; flex: 0 0 auto !important; }
.st-key-head [data-testid="stColumn"]:first-child { flex: 1 1 auto !important; }
.st-key-head [data-testid="stMarkdownContainer"], .st-key-head [data-testid="stMarkdown"],
.st-key-head [data-testid="stElementContainer"] { margin: 0 !important; }
.st-key-head .stButton > button { min-height: 44px; padding: 0 12px; font-size: 0.9rem; font-weight: 600;
  background: transparent; border: none; color: var(--blue); }
.who { display: flex; align-items: center; gap: 12px; }
.avatar { width: 44px; height: 44px; border-radius: 50%; flex: none; display: flex; align-items: center;
  justify-content: center; line-height: 1; color: #fff; font-weight: 600; font-size: 1.1rem; background: var(--blue); }
.who-name { font-weight: 700; font-size: 1.25rem; line-height: 1.25; word-break: keep-all; letter-spacing: -0.02em; }
.who-sub { color: var(--text3); font-size: 0.8rem; margin-top: 2px; }

/* 첫 화면 */
.hello { padding: 32px 4px 24px 4px; }
.hello-icon { width: 56px; height: 56px; border-radius: 14px; background: var(--blue);
  display: flex; align-items: center; justify-content: center; margin-bottom: 16px; }
.hello h1 { color: var(--text); font-size: 1.95rem !important; font-weight: 700 !important; line-height: 1.2;
  margin: 0 0 8px 0; padding: 0 !important; letter-spacing: -0.03em; }
.hello-desc { color: var(--text2); font-size: 1rem; line-height: 1.5; word-break: keep-all; }

/* 색 타일 두 개 */
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0 0 16px 0; }
.tile { border-radius: 16px; padding: 16px; color: #fff; min-height: 104px;
  display: flex; flex-direction: column; justify-content: space-between; }
.tile.g { background: var(--green); }
.tile.b { background: var(--blue); }
.tile-top { display: flex; align-items: center; gap: 6px; font-size: 0.8rem; font-weight: 600; }
.tile-num { font-size: 1.95rem; font-weight: 700; line-height: 1; }
.tile-num small { font-size: 1rem; font-weight: 600; opacity: 0.85; }

/* 진행률 */
.pct { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.big { font-size: 2.44rem; font-weight: 700; line-height: 1; }
.pill { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 0.8rem; font-weight: 600;
  background: var(--amber-soft); color: var(--amber); white-space: nowrap; }
.pill.ok { background: var(--green-soft); color: var(--green); }
.track { height: 8px; background: var(--fill); border-radius: 99px; margin-top: 16px; overflow: hidden; }
.fill { height: 100%; border-radius: 99px; background: var(--blue); }

/* 숫자 4칸: 한 면을 선으로 나눔 */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); background: var(--surface); border-radius: 16px;
  margin: 0 0 16px 0; padding: 12px 0; }
.stat { text-align: center; padding: 4px; }
.stat + .stat { border-left: 1px solid var(--line); }
.stat b { display: block; font-size: 1.56rem; font-weight: 700; line-height: 1.2; }
.stat span { font-size: 0.8rem; color: var(--text3); }
.stat.red b { color: var(--red); } .stat.grn b { color: var(--green); } .stat.yel b { color: var(--amber); }

/* 세로 막대 */
.bars { display: flex; gap: 8px; overflow-x: auto; padding: 16px 0 0 0; }
.bar { flex: 1; min-width: 40px; text-align: center; }
.bnum { font-weight: 600; font-size: 0.8rem; margin-bottom: 4px; }
.btrack { height: 112px; background: var(--fill); border-radius: 8px; display: flex; align-items: flex-end; overflow: hidden; }
.bfill { width: 100%; border-radius: 8px; min-height: 4px; }
.blab { font-size: 0.8rem; color: var(--text3); margin-top: 4px; }

/* 목록: 한 면 안에서 얇은 선으로 나눔 */
.group { background: var(--surface); border-radius: 16px; overflow: hidden; margin-bottom: 16px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 16px; min-height: 56px; }
.row + .row { border-top: 1px solid var(--line); }
.row-l { display: flex; align-items: center; gap: 12px; min-width: 0; }
.ic { width: 32px; height: 32px; border-radius: 50%; background: var(--blue-soft); color: var(--blue); flex: none;
  display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 0.8rem; }
.row-name { font-weight: 600; }
.row-meta { color: var(--text3); font-size: 0.8rem; margin-top: 2px; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 8px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.badge.done { background: var(--green-soft); color: var(--green); }
.badge.work { background: var(--red-soft); color: var(--red); }
.badge.none { background: var(--fill); color: var(--text3); }
.dots { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; max-width: 58%; }
.dot { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #C9D0DB; background: var(--surface); }
.dot.done { background: #3FA34D; border-color: #3FA34D; }
.dot.work { background: #E0483E; border-color: #E0483E; }
.legend { display: flex; gap: 16px; font-size: 0.8rem; color: var(--text3); margin: 0 4px 8px 4px; align-items: center; }
.legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: 1px; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.chip { background: var(--blue-soft); color: var(--blue-d); border-radius: 8px; padding: 4px 8px; font-size: 0.8rem; font-weight: 600; }

/* 단계 제목 */
.step { display: flex; align-items: center; gap: 8px; margin: 24px 0 8px 0; }
.step-n { width: 24px; height: 24px; border-radius: 50%; background: var(--text); color: #fff; font-weight: 600;
  font-size: 0.8rem; display: flex; align-items: center; justify-content: center; flex: none; }
.step-title { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.25; }

/* 탭: 애플 세그먼트 */
[role="tablist"] { background: var(--fill) !important; border-radius: 10px; padding: 2px; gap: 2px; margin-bottom: 8px;
  border: none !important; box-shadow: none !important; display: flex; }
[role="tablist"]::before, [role="tablist"]::after { display: none !important; }
[role="tab"] { flex: 1; display: flex; justify-content: center; align-items: center; border-radius: 8px; height: 36px;
  padding: 0 8px !important; margin: 0 !important; background: transparent; border: none !important;
  transition: background-color 150ms ease-out; }
[role="tab"] p { font-weight: 600 !important; font-size: 0.9rem !important; color: var(--text2) !important; }
[role="tab"][aria-selected="true"] { background: var(--surface); box-shadow: 0 1px 2px rgba(22, 26, 34, 0.12); }
[role="tab"][aria-selected="true"] p { color: var(--text) !important; }
.react-aria-SelectionIndicator, [data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none !important; }

/* 버튼 · 입력칸 */
.stButton > button, .stDownloadButton > button, .stLinkButton > a { border-radius: 12px; font-weight: 600; min-height: 48px;
  transition: background-color 150ms ease-out; }
[data-testid="stElementContainer"]:has([data-testid="stBaseButton-primary"]),
[data-testid="stElementContainer"]:has(.stLinkButton) { width: 100% !important; }
.stButton:has([data-testid="stBaseButton-primary"]), .stLinkButton { width: 100%; }
[data-testid="stBaseButton-primary"] { width: 100%; border: none; background: var(--blue); box-shadow: none; }
[data-testid="stBaseButton-primary"]:hover { background: var(--blue-d); }
[data-testid="stBaseButton-primary"]:disabled { background: var(--fill); color: var(--text3); }
.stMarkdown p, .row-meta, .muted { word-break: keep-all; }
[data-testid="stBaseButton-secondary"] { background: var(--surface); border: 1px solid var(--line); color: var(--blue); }
.stLinkButton > a { width: 100%; background: var(--blue-soft) !important; border: none !important; color: var(--blue-d) !important; }
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
  border-radius: 12px !important; background: var(--bg) !important; border-color: transparent !important; min-height: 48px; }
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea { background: transparent !important; }
[data-testid="stFileUploaderDropzone"] { border-radius: 16px; background: var(--surface); border: 1px dashed #B9C4D4; }

/* 점검 항목: 한 면 안의 목록 */
.st-key-checks { background: var(--surface); border-radius: 16px; overflow: hidden; gap: 0 !important; }
.st-key-checks [data-testid="stElementContainer"] { width: 100% !important; margin: 0 !important; }
.st-key-checks [data-testid="stCheckbox"] { width: 100%; padding: 12px 16px; min-height: 52px; display: flex; align-items: center;
  transition: background-color 150ms ease-out; }
.st-key-checks [data-testid="stElementContainer"] + [data-testid="stElementContainer"] [data-testid="stCheckbox"] {
  border-top: 1px solid var(--line); }
.st-key-checks [data-testid="stCheckbox"]:has(input:checked) { background: #F3F9F4; }
.st-key-checks [data-testid="stCheckbox"]:has(input:checked) p { color: var(--text2); }
[data-testid="stProgress"] > div > div { border-radius: 99px; }
[data-testid="stAlert"] { border-radius: 12px; }
.foot { color: var(--text3); font-size: 0.8rem; margin-top: 40px; text-align: center; }
</style>
"""

def _svg(path: str, size: int = 20, color: str = "#fff", width: float = 2.2) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{path}</svg>')

CHECK = '<path d="M5 12.5l4.5 4.5L19 7.5"/>'
WRENCH = ('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3.5 17.3a1.8 1.8 0 0 0 2.6 2.6l5.8-5.8a4 4 0 0 0 5.2-5.4'
          'l-2.5 2.5-2.3-.6-.6-2.3z"/>')
CLOCK = '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'
LIST = '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/>'


def html(text: str):
    st.markdown(text, unsafe_allow_html=True)


def who(initial: str, title: str, sub: str):
    """프로필 카드 왼쪽: 동그란 아바타 + 이름 + 소속"""
    html(f'<div class="who"><div class="avatar">{initial}</div><div>'
         f'<div class="who-name">{title}</div>'
         f'<div class="who-sub">{sub}</div></div></div>')


def head(initial: str, title: str, sub: str, buttons: list):
    """화면 맨 위 흰 카드. buttons: [(글자, 누르면 할 일), ...]"""
    with st.container(key="head"):
        cols = st.columns([4] + [1.3] * len(buttons), vertical_alignment="center")
        with cols[0]:
            who(initial, title, sub)
        for col, (label, fn) in zip(cols[1:], buttons):
            col.button(label, on_click=fn, key=f"head_{label}")


def step(label: str, title: str):
    """단계 제목. 예: step("STEP 1", "사용할 장비를 선택하세요")"""
    if label.startswith("STEP"):
        html(f'<div class="step"><div class="step-n">{label.split()[-1]}</div><div class="step-title">{title}</div></div>')
    else:
        html(f'<div class="label">{title}</div>')


def stats(boxes: list):
    """숫자 상자 4개. boxes: [(숫자, 이름, 색 클래스), ...]"""
    html('<div class="stats">' + "".join(f'<div class="stat {c}"><b class="num">{n}</b><span>{lab}</span></div>'
                                         for n, lab, c in boxes) + "</div>")


def pct_card(percent: int, title: str, detail: str):
    pill = '<span class="pill ok">완료</span>' if percent >= 100 else '<span class="pill">진행 중</span>'
    html(f'<div class="card"><div class="pct"><div><div class="big num">{percent}%</div>'
         f'<div class="muted" style="margin-top:8px">{title}</div></div>{pill}</div>'
         f'<div class="track"><div class="fill" style="width:{min(percent, 100)}%"></div></div>'
         f'<div class="muted" style="margin-top:8px">{detail}</div></div>')


def bar_color(ratio: float) -> str:
    if ratio >= 1:
        return GREEN
    if ratio >= 0.5:
        return YELLOW
    if ratio > 0:
        return "#E9842A"
    return RED


# ------------------------------------------------------------
# 5. 화면: 첫 화면 (학생 / 교수 / 설정)
# ------------------------------------------------------------
def logout():
    for key in ["role", "code", "team", "name"]:
        st.session_state.pop(key, None)
    st.query_params.clear()


def entry_screen():
    html(f'<div class="hello"><div class="hello-icon">{_svg(WRENCH, 28, "#fff", 2)}</div>'
         f'<h1>기계공학 실습 도우미</h1>'
         f'<div class="hello-desc">실습 장비를 쓰기 전, 조별로 안전 점검을 하고 기록을 남깁니다.</div></div>')
    data = load_data()

    with st.container(key="entry"):
        tab_s, tab_p, tab_a = st.tabs(["학생", "교수", "설정"])

        with tab_s:
            code = st.text_input("초대 코드", value=st.query_params.get("c", ""), placeholder="MJ-0000").strip().upper()
            teams = list(data.get(code, {}).get("teams", {}))
            if code and not teams:
                st.caption("초대 코드를 정확히 입력하면 조를 선택할 수 있습니다.")
            team = st.selectbox("조", teams, disabled=not teams, placeholder="초대 코드를 먼저 입력해 주세요")
            name = st.text_input("이름").strip()
            if st.button("입장하기", type="primary"):
                if not teams:
                    st.error("초대 코드를 다시 확인해 주세요.")
                elif not name:
                    st.error("이름을 입력해 주세요.")
                else:
                    join_class(code, team, name)
                    st.session_state.update(role="student", code=code, team=team, name=name)
                    st.query_params.update(c=code, t=team, n=name)   # 새로고침해도 로그인 유지
                    st.rerun()

        with tab_p:
            mode = st.radio("메뉴", ["새 수업 만들기", "기존 수업 열기"], horizontal=True, label_visibility="collapsed")
            if mode == "새 수업 만들기":
                cname = st.text_input("수업 이름", placeholder="MRO실습 101반 5주차").strip()
                tools = st.multiselect("이번 실습에서 사용할 장비", DEFAULT_TOOLS, default=DEFAULT_TOOLS[:4])
                extra = st.text_input("목록에 없는 장비 추가 (쉼표로 구분)", placeholder="유압 잭, 호이스트")
                team_count = st.number_input("조 수", min_value=1, max_value=30, value=6, step=1)
                pw = st.text_input("교수용 비밀번호", type="password")
                if st.button("수업 만들기", type="primary"):
                    tools = tools + [t.strip() for t in extra.split(",") if t.strip()]
                    if not cname or not tools or not pw:
                        st.error("수업 이름, 장비, 비밀번호를 모두 입력해 주세요.")
                    else:
                        code = create_class(cname, tools, pw, int(team_count))
                        st.session_state.update(role="prof", code=code)
                        st.rerun()
            else:
                code = st.text_input("초대 코드 ", placeholder="MJ-0000").strip().upper()
                pw = st.text_input("교수용 비밀번호 ", type="password")
                if st.button("수업 현황 열기", type="primary"):
                    if code in data and "teams" in data[code] and data[code]["pw"] == hash_pw(pw):
                        st.session_state.update(role="prof", code=code)
                        st.rerun()
                    else:
                        st.error("초대 코드 또는 비밀번호가 맞지 않습니다.")

        with tab_a:
            st.caption("운영자가 Gemini API 키를 한 번 등록하면, 접속한 모든 사람이 키 없이 사용할 수 있습니다.")
            if get_api_key():
                st.success("API 키가 등록되어 있습니다.")
                if KEY_FILE.exists() and st.button("등록된 키 삭제"):
                    KEY_FILE.unlink()
                    st.rerun()
            else:
                new_key = st.text_input("Gemini API 키", type="password")
                if st.button("이 컴퓨터에 저장") and new_key.strip():
                    KEY_FILE.write_text(new_key.strip(), encoding="utf-8")
                    st.rerun()
                st.caption("키는 이 폴더의 api_key.txt에 저장됩니다. 이 파일은 다른 사람에게 보내거나 깃허브에 올리면 안 됩니다.")

            if get_api_key():
                st.markdown("##### AI 모델")
                try:
                    names = list_models(get_api_key())
                except Exception as e:
                    names = []
                    st.warning(f"모델 목록을 불러오지 못했습니다. {e}")
                st.caption("사용 순서: " + " → ".join(model_order(get_api_key())))
                st.caption("한 모델의 하루 사용량을 다 쓰면 다음 모델로 자동으로 넘어갑니다.")
                if names:
                    pick = st.selectbox("가장 먼저 사용할 모델", ["자동"] + names)
                    if st.button("모델 저장"):
                        if pick == "자동":
                            MODEL_FILE.unlink(missing_ok=True)
                        else:
                            MODEL_FILE.write_text(pick, encoding="utf-8")
                        st.rerun()


# ------------------------------------------------------------
# 6. 화면: 학생
# ------------------------------------------------------------
def team_numbers(found: dict, tools: list):
    """완료 / 작업 중 / 미점검 장비 수"""
    done = len([t for t in tools if t in found and "end" in found[t]])
    work = len([t for t in tools if t in found and "end" not in found[t]])
    return done, work, len(tools) - done - work


def student_screen(code: str, team: str, name: str):
    data = load_data()
    room = data[code]
    me = room["teams"][team]      # 우리 조의 기록
    tools = room["tools"]

    head(name[:1], name, f"{room['name']} · {team}", [("나가기", logout)])
    done, work, left = team_numbers(me["found"], tools)
    html(f'<div class="tiles">'
         f'<div class="tile g"><div class="tile-top">{_svg(CHECK, 16, "#fff", 2.6)}사용 전 점검</div>'
         f'<div class="tile-num num">{done + work}<small> / {len(tools)}</small></div></div>'
         f'<div class="tile b"><div class="tile-top">{_svg(CLOCK, 16, "#fff", 2.2)}마무리 점검 대기</div>'
         f'<div class="tile-num num">{work}</div></div></div>')

    tab1, tab3, tab4 = st.tabs(["점검", "복장", "기록"])

    with tab1:
        nothing = "장비 선택"
        options = [nothing] + tools

        # 방금 점검을 마쳤으면 완료 메시지를 보여주고 선택을 비운다.
        if "flash" in st.session_state:
            st.success(st.session_state.pop("flash"))
            st.session_state["pick"] = nothing
        # 사진으로 찾은 장비가 있으면 아래 선택 상자에 반영한다.
        if "scan_tool" in st.session_state:
            st.session_state["pick"] = st.session_state.pop("scan_tool")
        if st.session_state.get("pick") not in options:
            st.session_state["pick"] = nothing

        step("STEP 1", "사용할 장비를 선택하세요")
        tool = st.selectbox("장비", options, key="pick", label_visibility="collapsed")
        with st.expander("장비 이름을 모르면 사진으로 찾기"):
            st.caption("장비 하나만 화면 가운데에 크게, 밝은 곳에서 촬영해 주세요.")
            photos = get_photo("tool", multi=True)
            if st.button("사진으로 찾기", key="tool_btn"):
                answer = analyze(photos, TOOL_PROMPT.format(tools=", ".join(tools)))
                if answer:
                    shown, matched, sure, tip = read_answer(answer, tools)
                    if matched and sure:
                        st.session_state["scan_tool"] = matched
                        st.session_state["scan_info"] = {"tool": matched, "text": shown}
                        st.rerun()
                    elif matched or "알 수 없음" in shown:
                        st.warning(f"사진만으로는 확실하지 않습니다. {tip}")
                    else:
                        st.warning("이번 실습 장비 목록에 없는 장비로 보입니다. 위에서 직접 선택해 주세요.")
                        with st.expander("사진 분석 내용 보기"):
                            st.markdown(shown)

        if tool != nothing:
            info = st.session_state.get("scan_info")
            if info and info["tool"] == tool:
                with st.expander(f"{tool} 설명 보기 (구조, 사용법, 자주 나는 사고)"):
                    st.markdown(info["text"])
            query = urllib.parse.quote(f"{tool} 사용법")
            st.link_button(f"'{tool} 사용법' 영상 찾아보기",
                           f"https://www.youtube.com/results?search_query={query}")

            turn = st.session_state.get("turn", 0)   # 점검을 마칠 때마다 체크박스를 새로 비우기 위한 번호
            record = me["found"].get(tool)
            working = bool(record) and "end" not in record

            if working:
                # ---------- 작업 중: 마무리 점검 ----------
                st.info(f"{record['time']}에 사용 전 점검을 마쳤습니다 (점검자 {record['by']}). "
                        "작업이 끝나면 마무리 점검을 해 주세요.")
                step("STEP 2", f"{tool} 마무리 점검")
                end_items = END_CHECKS + END_EXTRA.get(tool, [])
                with st.container(key="checks"):
                    ticks = [st.checkbox(item, key=f"end_{turn}_{tool}_{i}") for i, item in enumerate(end_items)]
                st.progress(sum(ticks) / len(end_items), text=f"{sum(ticks)} / {len(end_items)} 확인")
                if st.button("마무리 점검 완료", key="end_btn", type="primary", disabled=not all(ticks)):
                    when = mark_end(code, team, tool, name)
                    st.session_state["turn"] = turn + 1
                    st.session_state["flash"] = f"{team} · {tool} 마무리 점검을 완료했습니다. ({when})"
                    st.rerun()
            else:
                # ---------- 사용 전 점검 ----------
                step("STEP 2", f"{tool} 사용 전 점검")
                items, source = get_checklist(code, tool)
                items = items + COMMON_CHECKS
                if source == "ai":
                    st.caption("이 장비의 점검표는 AI가 작성한 초안입니다. 처음 사용할 때는 조교나 교수님께 내용을 확인받으세요.")
                with st.container(key="checks"):
                    ticks = [st.checkbox(item, key=f"chk_{turn}_{tool}_{i}") for i, item in enumerate(items)]
                st.progress(sum(ticks) / len(items), text=f"{sum(ticks)} / {len(items)} 확인")

                photo_result, ready = "", False
                if not all(ticks):
                    st.caption("모든 항목을 확인해야 다음 단계로 넘어갑니다. "
                               "확인할 수 없는 항목이 있으면 작업을 시작하지 말고 조교나 교수님께 알려 주세요.")
                else:
                    # ---------- 준비 상태 사진을 AI가 확인 ----------
                    step("STEP 3", "준비 상태 사진 확인")
                    st.caption("작업 준비를 마친 장비를 촬영해 주세요. 공작물을 고정한 부분과 주변이 함께 보이면 좋습니다.")
                    setup_key = f"setup_{turn}_{tool}"
                    photos = get_photo("setup", multi=True)
                    if st.button("사진 확인 요청", key="setup_btn"):
                        numbered = "\n".join(f"- {item}" for item in items)
                        answer = analyze(photos, SETUP_PROMPT.format(tool=tool, items=numbered))
                        if answer:
                            st.session_state[setup_key] = {"verdict": read_verdict(answer), "text": answer}
                    result = st.session_state.get(setup_key)
                    if result:
                        with st.container(border=True):
                            st.markdown(result["text"])
                    verdict = result["verdict"] if result else ""
                    if verdict == "이상 없음":
                        st.success("사진에서 확인되는 문제는 없습니다. 사진에 보이지 않는 부분은 직접 확인한 내용을 따릅니다.")
                        photo_result, ready = "AI 확인", True
                    elif verdict == "문제 발견":
                        st.error("사진에서 문제가 확인됐습니다. 조치한 뒤 다시 촬영하거나, 조교나 교수님께 확인받으세요.")
                        if st.checkbox("문제를 조치했고, 조교나 교수님께 확인받았습니다", key=f"fixed_{turn}_{tool}"):
                            photo_result, ready = "문제 발견 후 조치", True
                    else:
                        if verdict == "확인 어려움":
                            st.warning("사진만으로는 판단하기 어렵습니다. 장비가 잘 보이도록 다시 촬영해 주세요.")
                        if st.checkbox("사진 확인 없이 진행합니다 (사진 확인을 사용할 수 없을 때만)",
                                       key=f"skip_{turn}_{tool}"):
                            photo_result, ready = "사진 확인 없음", True

                if st.button("점검 완료 · 작업 시작", key="done_btn", type="primary", disabled=not ready):
                    when = mark_checked(code, team, tool, name, photo_result)
                    st.session_state["turn"] = turn + 1
                    st.session_state["flash"] = (f"{team} · {tool} 사용 전 점검을 완료했습니다. ({when}) "
                                                 "작업이 끝나면 같은 장비를 선택해 마무리 점검을 해 주세요.")
                    st.rerun()

    with tab3:
        step("복장", "작업 전에 복장과 보호구를 확인합니다")
        work_tool = st.selectbox("사용할 장비", tools, key="outfit_work")
        with st.expander("촬영 예시", expanded=True):
            if GUIDE_FILE.exists():
                svg = base64.b64encode(GUIDE_FILE.read_bytes()).decode()
                html(f'<img src="data:image/svg+xml;base64,{svg}" style="width:100%; border-radius:12px;">')
            st.caption("머리부터 신발까지 보이도록 2~3m 떨어져서, 양손을 앞으로 내밀고 촬영해 주세요.")
        photo = get_photo("outfit", multi=True)
        if st.button("복장 확인 요청", key="outfit_btn", type="primary"):
            answer = analyze(photo, OUTFIT_PROMPT.format(work=work_tool))
            if answer:
                with st.container(border=True):
                    st.markdown(answer)
                if "❓" in answer:
                    # 사진에 안 보여서 판단 못 한 항목이 있으면 추가 촬영을 요청한다.
                    st.warning("❓로 표시된 항목은 사진에 보이지 않아 확인하지 못했습니다. "
                               "해당 부분이 보이는 사진을 추가해(최대 3장) 다시 요청해 주세요.")

    with tab4:
        me = load_data()[code]["teams"][team]   # 방금 기록한 것까지 반영
        done, work, left = team_numbers(me["found"], tools)
        percent = round(100 * (done + work) / len(tools)) if tools else 0
        chips = "".join(f'<span class="chip">{m}</span>' for m in me["members"])
        html(f'<div class="card"><div class="ctitle">{team} 조원</div><div class="chips">{chips}</div>'
             f'<div class="muted" style="margin-top:8px">조원 한 명이 점검을 마치면 조 전체의 기록으로 남습니다.</div></div>')
        pct_card(percent, "사용 전 점검 진행률", f"점검한 장비 {done + work} / {len(tools)}")
        stats([(len(tools), "전체", ""), (work, "작업 중", "red"), (done, "완료", "grn"), (left, "미점검", "yel")])

        step("기록", "장비별 점검 현황")
        if done + work == 0:
            st.info("아직 점검한 장비가 없습니다. 점검 탭에서 사용할 장비를 고르면 시작할 수 있습니다.")
        rows_html = ""
        for i, tool in enumerate(tools, 1):
            record = me["found"].get(tool)
            if not record:
                badge, meta = '<span class="badge none">미점검</span>', "아직 점검하지 않았습니다"
            elif "end" in record:
                badge = '<span class="badge done">완료</span>'
                meta = f"시작 {record['time'][-5:]} {record['by']} · 마무리 {record['end']['time'][-5:]} {record['end']['by']}"
            else:
                badge = '<span class="badge work">작업 중</span>'
                meta = f"시작 {record['time'][-5:]} {record['by']} · 마무리 점검 필요"
            rows_html += (f'<div class="row"><div class="row-l"><div class="ic">{i}</div><div>'
                          f'<div class="row-name">{tool}</div><div class="row-meta">{meta}</div></div></div>{badge}</div>')
        html(f'<div class="group">{rows_html}</div>')


# ------------------------------------------------------------
# 7. 화면: 교수
# ------------------------------------------------------------
def cell_text(record) -> str:
    """교수 표의 한 칸: 점검 상태를 짧게 보여준다."""
    if not record:
        return "-"
    mark = {"AI 확인": " · 사진 확인", "문제 발견 후 조치": " · 조치 후 진행"}.get(record.get("photo", ""), "")
    if "end" in record:
        return f"완료 {record['time'][-5:]}~{record['end']['time'][-5:]}{mark}"
    return f"작업 중 {record['time'][-5:]}{mark}"


def prof_screen(code: str):
    room = load_data()[code]
    tools, teams = room["tools"], room["teams"]

    head("교", room["name"], f"초대 코드 {code}", [("나가기", logout)])
    tab_now, tab_edit = st.tabs(["현황", "점검표 수정"])

    with tab_now:
        rows = []
        for team, t in teams.items():
            done = len([tool for tool in tools if tool in t["found"]])
            row = {"조": team, "조원": ", ".join(t["members"]) or "-", "진행": f"{done}/{len(tools)}"}
            for tool in tools:
                row[tool] = cell_text(t["found"].get(tool))
            rows.append(row)

        working = [f"{team} {tool}" for team, t in teams.items() for tool in tools
                   if tool in t["found"] and "end" not in t["found"][tool]]
        total = len(teams) * len(tools)
        checked = sum(len([tool for tool in tools if tool in t["found"]]) for t in teams.values())
        finished = sum(len([tool for tool in tools if tool in t["found"] and "end" in t["found"][tool]])
                       for t in teams.values())
        joined = len([t for t in teams.values() if t["members"]])

        pct_card(round(100 * checked / total) if total else 0, "전체 점검률",
                 f"입장한 조 {joined} / {len(teams)} · 점검한 칸 {checked} / {total}")
        stats([(len(teams), "전체 조", ""), (len(working), "작업 중", "red"),
               (finished, "마무리 완료", "grn"), (total - checked, "미점검", "yel")])

        # 조별 막대 그래프
        bars = ""
        for team, t in teams.items():
            n = len([tool for tool in tools if tool in t["found"]])
            ratio = n / len(tools) if tools else 0
            bars += (f'<div class="bar"><div class="bnum num">{n}</div><div class="btrack">'
                     f'<div class="bfill" style="height:{max(ratio * 100, 5):.0f}%; background:{bar_color(ratio)}"></div>'
                     f'</div><div class="blab">{team}</div></div>')
        html(f'<div class="card"><div class="ctitle">조별 점검 현황</div>'
             f'<div class="muted">사용 전 점검을 마친 장비 수 (장비 {len(tools)}개 중)</div><div class="bars">{bars}</div></div>')

        # 조별 목록 (점 하나 = 장비 하나)
        step("조별", "장비별 점검 상태")
        html(f'<div class="legend"><span><i style="background:{GREEN}"></i>완료</span>'
             f'<span><i style="background:{RED}"></i>작업 중</span>'
             f'<span><i style="background:#fff; border:2px solid #D5DCE6"></i>미점검</span></div>')
        rows_html = ""
        for team, t in teams.items():
            dots = ""
            for tool in tools:
                r = t["found"].get(tool)
                cls = "" if not r else ("done" if "end" in r else "work")
                dots += f'<span class="dot {cls}" title="{tool}"></span>'
            members = ", ".join(t["members"]) or "미입장"
            rows_html += (f'<div class="row"><div class="row-l"><div class="ic">{team.replace("조", "")}</div><div>'
                          f'<div class="row-name">{team}</div><div class="row-meta">{members}</div></div></div>'
                          f'<div class="dots">{dots}</div></div>')
        html(f'<div class="group">{rows_html}</div>')
        html(f'<div class="muted" style="margin:-8px 4px 16px 4px">점 순서: {" · ".join(tools)}</div>')

        # 장비별 진행
        lines = ""
        for tool in tools:
            n = len([t for t in teams.values() if tool in t["found"]])
            ratio = n / len(teams) if teams else 0
            lines += (f'<div style="margin-top:12px"><div style="display:flex; justify-content:space-between">'
                      f'<span style="font-weight:600">{tool}</span><span class="muted">{n} / {len(teams)}조</span></div>'
                      f'<div class="track" style="margin-top:6px"><div class="fill" style="width:{ratio * 100:.0f}%"></div></div></div>')
        html(f'<div class="card"><div class="ctitle">장비별 진행</div>{lines}</div>')

        if working:
            st.warning("마무리 점검을 아직 하지 않은 곳: " + ", ".join(working))

        with st.expander("표로 보기"):
            st.dataframe(rows, hide_index=True)
            st.caption("작업 중: 사용 전 점검을 마치고 작업하는 중 · 완료: 마무리 점검까지 마침(시작~마무리 시각) · "
                       "사진 확인: 준비 상태 사진을 AI가 확인 · 조치 후 진행: 사진에서 문제가 발견돼 조치한 뒤 진행")
        with st.expander("점검 기록 전체"):
            log = []
            for team, t in teams.items():
                for tool in tools:
                    r = t["found"].get(tool)
                    if r:
                        end = f" · 마무리 {r['end']['time']} {r['end']['by']}" if "end" in r else " · 작업 중"
                        log.append(f"- {team} · {tool} · 시작 {r['time']} {r['by']} · 사진: {r.get('photo', '-')}{end}")
            st.markdown("\n".join(log) if log else f"아직 점검 기록이 없습니다. 학생들에게 초대 코드 {code}를 알려 주세요.")

        st.button("현황 새로고침", use_container_width=True)
        header = ["조", "조원", "진행"] + tools
        csv = "\n".join([",".join(header)] + [",".join('"' + str(r[h]) + '"' for h in header) for r in rows])
        st.download_button("엑셀 파일로 내려받기 (CSV)", "﻿" + csv, file_name=f"{code}_조별안전점검.csv",
                           mime="text/csv", use_container_width=True)

    with tab_edit:
        st.caption("장비별 사용 전 점검표를 이 수업에 맞게 고칠 수 있습니다. 저장하면 학생 화면에 바로 반영됩니다.")
        tool = st.selectbox("장비", tools, key="edit_tool")
        items, source = get_checklist(code, tool, allow_ai=False)
        label = {"prof": "교수가 수정한 점검표", "ai": "AI가 작성한 초안 (내용을 확인해 주세요)",
                 "basic": "기본 점검표", "generic": "공통 기본 항목 (이 장비 전용 점검표가 아직 없습니다)"}[source]
        st.write(f"현재 적용: **{label}**")
        ver = st.session_state.get("edit_ver", 0)
        text = st.text_area("점검 항목 (한 줄에 하나)", "\n".join(items), height=240, key=f"edit_{ver}_{tool}")
        st.caption("모든 장비에 자동으로 추가되는 항목: " + " / ".join(COMMON_CHECKS))
        col1, col2 = st.columns(2)
        if col1.button("점검표 저장", type="primary"):
            new_items = [line.strip(" -\t") for line in text.splitlines() if line.strip(" -\t")]
            if not new_items:
                st.error("항목을 하나 이상 입력해 주세요.")
            else:
                save_checklist(code, tool, new_items, "prof")
                st.session_state["edit_ver"] = ver + 1
                st.session_state["edit_msg"] = f"{tool} 점검표를 저장했습니다. ({len(new_items)}개 항목)"
                st.rerun()
        if source in ("prof", "ai") and col2.button("기본 점검표로 되돌리기"):
            save_checklist(code, tool, None)
            st.session_state["edit_ver"] = ver + 1
            st.session_state["edit_msg"] = f"{tool} 점검표를 기본으로 되돌렸습니다."
            st.rerun()
        if "edit_msg" in st.session_state:
            st.success(st.session_state.pop("edit_msg"))


# ------------------------------------------------------------
# 8. 어떤 화면을 보여줄지 정하기
# ------------------------------------------------------------
st.set_page_config(page_title="기계공학 실습 도우미", page_icon="✅", initial_sidebar_state="collapsed")
st.markdown(STYLE, unsafe_allow_html=True)

# 새로고침했을 때 주소에 남아 있는 코드, 조, 이름으로 학생 로그인을 되살린다.
all_data = load_data()
if "role" not in st.session_state:
    c, t, n = st.query_params.get("c", ""), st.query_params.get("t", ""), st.query_params.get("n", "")
    if c and n and t in all_data.get(c, {}).get("teams", {}):
        st.session_state.update(role="student", code=c, team=t, name=n)

role = st.session_state.get("role")
room_now = all_data.get(st.session_state.get("code", ""), {})
if role == "student" and st.session_state.get("team") in room_now.get("teams", {}):
    student_screen(st.session_state["code"], st.session_state["team"], st.session_state["name"])
elif role == "prof" and "teams" in room_now:
    prof_screen(st.session_state["code"])
else:
    entry_screen()

html('<div class="foot">참고용 도구입니다. 실제 작업 전에는 반드시 조교나 교수님의 안내를 따르세요.</div>')
