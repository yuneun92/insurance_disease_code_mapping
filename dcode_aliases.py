import streamlit as st
from neo4j import GraphDatabase
from vertexai.language_models import TextGenerationModel
import json
import os
import time
from typing import Union, Dict, Any
from dataclasses import dataclass
from litellm import completion

import streamlit as st

import streamlit as st
import subprocess
import os
import json
from pathlib import Path
import webbrowser
import time

def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        try:
            input_username = st.session_state["username"]
            input_password = st.session_state["password"]
            stored_username = st.secrets["login_id"]
            stored_password = st.secrets["login_pw"]
            
            # 디버깅용 출력
            st.write("입력된 아이디:", input_username)
            st.write("저장된 아이디:", stored_username)
            st.write("입력된 비밀번호:", input_password)
            st.write("저장된 비밀번호:", stored_password)
            
            if (input_username == stored_username and 
                input_password == stored_password):
                st.session_state["password_correct"] = True
            else:
                st.session_state["password_correct"] = False
                
        except Exception as e:
            st.error(f"오류 발생: {str(e)}")
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show inputs for username + password.
        st.text_input("아이디", on_change=password_entered, key="username")
        st.text_input(
            "비밀번호", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input("아이디", on_change=password_entered, key="username")
        st.text_input(
            "비밀번호", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 아이디 또는 비밀번호가 올바르지 않습니다")
        return False
    else:
        # Password correct.
        return True

@dataclass
class Task:
    pass

class DiseaseNameProcessor:
    def __init__(self, uri, auth, database):
        self.driver = GraphDatabase.driver(uri, auth=auth)
        self.database = database

    def execute_task(self, task: Task, input_data: str) -> Union[Dict[str, Any], str]:
        max_retries = 5
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                model = "claude-3-5-sonnet@20240620"
                response = completion(
                    model=f"vertex_ai/{model}",
                    messages=[{"role": "user", "content": input_data}],
                    temperature=0.7,
                    vertex_ai_project="loader-434606",
                    vertex_ai_location="us-east5",
                )
                return response.choices[0].message.content
            except Exception as e:
                error_message = str(e)
                if "429" in error_message or "RESOURCE_EXHAUSTED" in error_message:
                    print(f"Attempt {attempt + 1}: Resource exhausted. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print(f"Error in execute_task: {error_message}")
                    raise

    def get_disease_data(self):
        with self.driver.session(database=self.database) as session:
            result = session.run("""
                MATCH (d:disease_code)
                WHERE d.code STARTS WITH 'C' OR d.code STARTS WITH 'D'
                RETURN d.code as code, 
                       d.include_names as include_names,
                       d.name_ko as name_ko,
                       d.name_en as name_en,
                       d.aliases as aliases
                ORDER BY d.code
            """)
            return [dict(record) for record in result]
    def extract_names_with_claude(self, disease_data):
        prompt = f"""
    <Task> 
        Extract simplified Korean disease names from the medical terminology data.
    </Task>
    
    <Requirements>
        - ALWAYS extract at least one Korean name for the disease
        - For cancer (code starts with C), always include a name ending with "암"
        - For non-cancer diseases (code starts with D), use common medical terms
        - If multiple names exist in include_names, select the most commonly used one
        - If name_ko exists, it should be included in the output
        - Never return an empty list
        - Format output as a JSON array of strings
        - Keep names concise (usually 2-4 characters)
    </Requirements>
    
    <Guidelines>
        1. If it's a cancer (code C):
           - Primary format: "[부위]암"
           - Example: "위암", "폐암", "간암"

        2. If it's a benign tumor/disease (code D):
           - Primary format: "[상태][부위]" or "[부위][상태]"
           - Example: "양성종양", "낭종"

        3. Priority for name selection:
           1) Use name_ko if it's concise and common
           2) Select from include_names if they're more commonly used
           3) Simplify name_en if no Korean names are available
    </Guidelines>
    
    <Input data>
        {json.dumps(disease_data, ensure_ascii=False, indent=2)}
    </Input data>
    
    <Expected output format>
        ["간암"] // For single name
        ["위암", "진행성위암"] // For multiple names if clearly distinct
        Make sure your output must be valid list(json) format
    </Expected output format>
    """
        try:
            response = self.execute_task(Task(), prompt)
            extracted_names = json.loads(response)
            if not extracted_names:
                if disease_data.get('name_ko'):
                    extracted_names = [disease_data['name_ko']]
                else:
                    code_start = disease_data['code'][0]
                    if code_start == 'C':
                        extracted_names = ["상세불명의 암"]
                    else:
                        extracted_names = ["상세불명의 종양"]
            return extracted_names, response
        except json.JSONDecodeError:
            return ["상세불명의 질환"], response
        
    def update_name_ko(self, code: str, name_ko: str):
        with self.driver.session(database=self.database) as session:
            session.run("""
                MATCH (d:disease_code {code: $code})
                SET d.name_ko = $name_ko
            """, code=code, name_ko=name_ko)

    def update_name_en(self, code: str, name_en: str):
        with self.driver.session(database=self.database) as session:
            session.run("""
                MATCH (d:disease_code {code: $code})
                SET d.name_en = $name_en
            """, code=code, name_en=name_en)

    def update_include_names(self, code: str, include_names: list):
        with self.driver.session(database=self.database) as session:
            session.run("""
                MATCH (d:disease_code {code: $code})
                SET d.include_names = $include_names
            """, code=code, include_names=include_names)

    def update_aliases(self, code: str, aliases: list):
        with self.driver.session(database=self.database) as session:
            session.run("""
                MATCH (d:disease_code {code: $code})
                SET d.aliases = $aliases
            """, code=code, aliases=aliases)

    def close(self):
        self.driver.close()

def main():
    st.set_page_config(layout="wide")
    st.title("질병 코드 관리 시스템")

    # Initialize processor
    uri = 'neo4j://121.134.230.246:57867'
    auth = ('neo4j', 'infocz4ever')
    database = "kblife-poc-1.2"

    processor = DiseaseNameProcessor(
        uri=uri,
        auth=auth,
        database=database
    )
    # Streamlit secrets 확인
    if 'login_id' not in st.secrets or 'login_pw' not in st.secrets:
        st.error("Secrets에 로그인 정보가 설정되지 않았습니다!")
        st.stop()

    # 로그인 확인
    if not check_password():
        st.stop()

    # 로그아웃 버튼
    if st.sidebar.button("로그아웃"):
        for key in ["password_correct", "username", "password"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

                
    # Get diseases data
    if 'diseases' not in st.session_state:
        st.session_state.diseases = processor.get_disease_data()
        st.session_state.total_count = len(st.session_state.diseases)

    # Navigation buttons
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if st.button("← 이전", disabled=st.session_state.current_index <= 0):
            st.session_state.current_index -= 1
            st.session_state.editing = {'name_ko': False, 'name_en': False, 'include_names': False}
            st.rerun()
    with col3:
        if st.button("다음 →", disabled=st.session_state.current_index >= st.session_state.total_count - 1):
            st.session_state.current_index += 1
            st.session_state.editing = {'name_ko': False, 'name_en': False, 'include_names': False}
            st.rerun()
    
    # Display progress
    st.progress((st.session_state.current_index + 1) / st.session_state.total_count)
    st.write(f"진행상황: {st.session_state.current_index + 1} / {st.session_state.total_count}")

    # Current disease data
    current_disease = st.session_state.diseases[st.session_state.current_index]
    
    # Display disease code
    st.header(f"질병 코드: {current_disease['code']}")

    # Korean name section
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.editing['name_ko']:
            name_ko = st.text_input("한글명칭", value=current_disease.get('name_ko', ''))
            if st.button("한글명칭 저장"):
                processor.update_name_ko(current_disease['code'], name_ko)
                st.session_state.editing['name_ko'] = False
                st.session_state.diseases = processor.get_disease_data()
                st.success("한글명칭이 저장되었습니다!")
                st.rerun()
        else:
            st.info("한글명칭")
            st.write(current_disease.get('name_ko', '정보없음'))
    with col2:
        if not st.session_state.editing['name_ko']:
            if st.button("한글명칭 수정"):
                st.session_state.editing['name_ko'] = True
                st.rerun()

    # English name section
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.editing['name_en']:
            name_en = st.text_input("영어명칭", value=current_disease.get('name_en', ''))
            if st.button("영어명칭 저장"):
                processor.update_name_en(current_disease['code'], name_en)
                st.session_state.editing['name_en'] = False
                st.session_state.diseases = processor.get_disease_data()
                st.success("영어명칭이 저장되었습니다!")
                st.rerun()
        else:
            st.info("영어명칭")
            st.write(current_disease.get('name_en', '정보없음'))
    with col2:
        if not st.session_state.editing['name_en']:
            if st.button("영어명칭 수정"):
                st.session_state.editing['name_en'] = True
                st.rerun()

    # Include names section
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.editing['include_names']:
            current_include_names = current_disease.get('include_names', [])
            if isinstance(current_include_names, str):
                try:
                    current_include_names = json.loads(current_include_names)
                except:
                    current_include_names = [current_include_names]
            include_names = st.text_area(
                "포함 (각 줄에 하나씩 입력)",
                value='\n'.join(current_include_names) if current_include_names else ''
            )
            if st.button("포함 저장"):
                include_names_list = [name.strip() for name in include_names.split('\n') if name.strip()]
                processor.update_include_names(current_disease['code'], include_names_list)
                st.session_state.editing['include_names'] = False
                st.session_state.diseases = processor.get_disease_data()
                st.success("포함 목록이 저장되었습니다!")
                st.rerun()
        else:
            st.info("포함")
            include_names = current_disease.get('include_names', [])
            if isinstance(include_names, str):
                try:
                    include_names = json.loads(include_names)
                except:
                    include_names = [include_names]
            st.write(include_names if include_names else '정보없음')
    with col2:
        if not st.session_state.editing['include_names']:
            if st.button("포함 수정"):
                st.session_state.editing['include_names'] = True
                st.rerun()

    # Claude processing for aliases
    disease_key = current_disease['code']
    if disease_key not in st.session_state.claude_response:
        with st.spinner('Claude가 응답을 생성 중입니다...'):
            extracted_names, full_response = processor.extract_names_with_claude(current_disease)
            st.session_state.claude_response[disease_key] = {
                'names': extracted_names,
                'full_response': full_response
            }

    # Display and edit extracted names
    st.subheader("추출된 질병명")
    aliases = st.text_input(
        "질병명 목록 (쉼표로 구분)",
        value=", ".join(st.session_state.claude_response[disease_key]['names'])
    )
    if st.button("별칭 저장"):
        aliases_list = [name.strip() for name in aliases.split(',') if name.strip()]
        processor.update_aliases(current_disease['code'], aliases_list)
        st.success("별칭이 저장되었습니다!")
        st.session_state.diseases = processor.get_disease_data()
        st.rerun()

    # Display current aliases
    st.subheader("현재 저장된 별칭")
    current_aliases = current_disease.get('aliases', [])
    if current_aliases:
        st.write(current_aliases)
    else:
        st.write("저장된 별칭 없음")

    # Display Claude's full response
    with st.expander("Claude의 전체 응답 보기"):
        st.text(st.session_state.claude_response[disease_key]['full_response'])

    # Cleanup
    processor.close()

if __name__ == "__main__":
    main()
