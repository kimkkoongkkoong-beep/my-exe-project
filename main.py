import flet as ft
import webbrowser
import requests
import datetime
import threading
import time
import traceback
import csv
import urllib3
import pyperclip
import math
import platform # 운영체제 확인용
import subprocess # 맥 명령어 실행용

# [수정] 윈도우용 알림 라이브러리 (없어도 에러 안 나게 처리)
try:
    from plyer import notification
except ImportError:
    notification = None
import re # [추가] 정규표현식 모듈
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote  # [수정] quote 추가
# [추가] JSON 파일 저장용 모듈
import json 
import os

# SSL 경고 무시
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# [수정] 요금 관리 매니저 (사용자 요금표 반영)
# ==========================================
class RateManager:
    def __init__(self, filename="rates.json"):
        self.filename = filename
        # 사용자가 제공한 요금표 기준 데이터
        self.default_rates = {
            "internet": {
                "기가라이트(500M)": 33000, 
                "1기가(1G)": 38500, 
                "광랜(100M)": 22000, 
                "선택안함": 0
            },
            "wifi": {
                "선택안함": 0, 
                "광랜와이파이": 1100, # 조건부 계산 필요
                "기가와이파이": 1100
            },
            "discount": {
                "선택안함": {"100M": 0, "500M": 0, "1G": 0},
                "요즘우리집결합": {"100M": -1100, "500M": -5500, "1G": -5500},
                "요즘가족결합(본인)": {"100M": -4400, "500M": -11000, "1G": -13200},
                "요즘가족결합(가족)": {"100M": -4400, "500M": -11000, "1G": -13200},
                "온가족할인": {"100M": -1100, "500M": -5500, "1G": -5500},
                "패밀리결합": {"100M": -5500, "500M": -11100, "1G": -11000}
            },
            "iptv": {
                "선택안함": 0, 
                "BTV스탠다드": 13200, "BTV ALL": 16500, "BTV 이코노미": 9900, 
                "BTV ALL플러스": 22000, "BTV스탠다드플러스": 18700
            },
            "stb": { 
                "선택안함": 0, 
                "Smart": 4400, "Smart mini": 4400, 
                "AI2": 6600, "AI4": 8800, "APPLE TV": 4400
            },
            "multitv": { 
                "선택안함": 0, "BTV스탠다드": 7700, "BTV ALL": 9350, "BTV 이코노미": 6050, 
                "BTV ALL플러스": 14850, "BTV스탠다드플러스": 13200
            },
            "multistb": { 
                "선택안함": 0, "Smart": 2200, "Smart mini": 2200, "AI2": 0, "AI4": 0, "APPLE TV": 4400
            },
            "addon": {
                "선택안함": 0, "안심": 2200, "더안심": 3300, "안심쉐어": 3300, "더안심쉐어": 4400
            },
            "pop": {
                "선택안함": 0, "POP230": 12100, "POP180": 11000, "POP100": 11000
            }
        }
        self.load_rates()

    def load_rates(self):
        # 파일이 없거나 에러나면 기본값 사용
        self.data = self.default_rates 
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.data.update(loaded) # 병합
            except: pass

    def save_rates(self, new_data):
        self.data = new_data
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

    def calculate(self, s):
        # s = selections 딕셔너리
        total = 0
        
        # 1. 인터넷 요금
        inet = s.get('internet', '선택안함')
        total += self.data['internet'].get(inet, 0)

        # 2. IPTV 존재 여부 확인
        has_iptv = s.get('iptv', '선택안함') != '선택안함'

        # 3. 와이파이 (조건부 요금)
        wifi = s.get('wifi', '선택안함')
        wifi_fee = self.data['wifi'].get(wifi, 0)
        
        if wifi == "광랜와이파이":
            # 광랜와이파이: 단독 1100, TV있으면 2200 (오퍼1 설명 참조)
            # *주의: 프롬프트에는 "SKB_IPTV가 있을 경우 = 2,200" 이라고 되어 있으나,
            # 보통 결합 시 와이파이가 무료가 되거나 할인이 되는 경우가 많습니다.
            # 여기서는 요청하신 텍스트 그대로 "TV 있으면 2200"으로 계산합니다.
            if has_iptv: wifi_fee = 2200 
            else: wifi_fee = 1100
        
        total += wifi_fee

        # 4. 할인 (인터넷 속도에 따라 다름)
        disc = s.get('discount', '선택안함')
        if disc != "선택안함":
            speed = "100M"
            if "500M" in inet: speed = "500M"
            elif "1G" in inet: speed = "1G"
            
            disc_fee = self.data['discount'][disc].get(speed, 0)
            
            # 요즘가족결합(본인/가족) + IPTV 결합 시 추가 할인 (-1100)
            if "요즘가족결합" in disc and has_iptv:
                disc_fee -= 1100
            
            total += disc_fee

        # 5. IPTV
        iptv = s.get('iptv', '선택안함')
        total += self.data['iptv'].get(iptv, 0)

        # 6. 셋탑박스 (조건부 할인 AI2/AI4)
        stb = s.get('stb', '선택안함')
        stb_fee = self.data['stb'].get(stb, 0)
        
        if "AI2" in stb: # AI2 할인 조건
            if "ALL" in iptv: stb_fee -= 2200 # ALL, ALL+ 모두 "ALL" 문자열 포함됨
        elif "AI4" in stb: # AI4 할인 조건
            if iptv == "BTV ALL": stb_fee -= 2200
            elif iptv == "BTV ALL플러스": stb_fee -= 4400
            
        total += stb_fee

        # 7. 다셋탑
        mtv = s.get('multitv', '선택안함')
        total += self.data['multitv'].get(mtv, 0)
        
        mstb = s.get('multistb', '선택안함')
        total += self.data['multistb'].get(mstb, 0)

        # 8. 부가서비스 (Wings + 오퍼5 중복 할인)
        has_wings = s.get('addon_wings', False)
        addon_safe = s.get('addon_safe', '선택안함')
        
        wings_fee = 1650 if has_wings else 0
        safe_fee = self.data['addon'].get(addon_safe, 0)
        
        # Wings + 안심 동시 적용 시 -550 할인
        if has_wings and addon_safe != "선택안함":
            wings_fee -= 550
            
        total += wings_fee
        total += safe_fee

        # 9. POP
        pop = s.get('pop', '선택안함')
        total += self.data['pop'].get(pop, 0)

        return total

# ==========================================
# [신규/수정] Firebase Firestore REST Handler
# ==========================================
class FirestoreManager:
    def __init__(self):
        # [수정됨] 사용자님이 제공한 새로운 설정값 적용
        self.project_id = "druk-b3912" 
        self.api_key = "AIzaSyDl4Y6r-llnhGJGeWOUYTbGgb1iVpQfM5o"
        
        # Firestore REST API Base URL
        self.base_url = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents"

    def _to_firestore_data(self, data):
        """파이썬 딕셔너리를 Firestore REST 포맷으로 변환"""
        fields = {}
        for k, v in data.items():
            if isinstance(v, str): 
                fields[k] = {"stringValue": v}
            # [수정됨] bool 체크를 int보다 반드시 먼저 해야 합니다!
            elif isinstance(v, bool): 
                fields[k] = {"booleanValue": v}
            elif isinstance(v, int): 
                fields[k] = {"integerValue": str(v)}
            elif isinstance(v, float): 
                fields[k] = {"doubleValue": v}
            elif v is None: 
                fields[k] = {"nullValue": None}
        return {"fields": fields}

    def _from_firestore_data(self, document):
        """Firestore 응답을 파이썬 딕셔너리로 변환"""
        data = {}
        if 'fields' in document:
            for k, v in document['fields'].items():
                if 'stringValue' in v: data[k] = v['stringValue']
                elif 'integerValue' in v: data[k] = int(v['integerValue'])
                elif 'booleanValue' in v: data[k] = v['booleanValue']
                elif 'doubleValue' in v: data[k] = float(v['doubleValue'])
                elif 'timestampValue' in v: data[k] = v['timestampValue']
        
        # 문서 ID 포함
        full_path = document.get('name', '')
        data['doc_id'] = full_path.split('/')[-1] if full_path else ""
        return data

    def add_todo(self, todo_data):
        """할 일 추가"""
        url = f"{self.base_url}/todos?key={self.api_key}"
        payload = self._to_firestore_data(todo_data)
        try:
            r = requests.post(url, json=payload)
            if r.status_code != 200:
                print(f"Firestore Error: {r.text}") # 디버깅용 로그
            return r.status_code == 200
        except Exception as e:
            print(f"Network Error: {e}")
            return False

    def get_todos(self):
        """할 일 목록 조회"""
        url = f"{self.base_url}/todos?pageSize=100&key={self.api_key}"
        try:
            r = requests.get(url)
            todos = []
            if r.status_code == 200:
                res_json = r.json()
                if 'documents' in res_json:
                    for doc in res_json['documents']:
                        todos.append(self._from_firestore_data(doc))
            else:
                print(f"Firestore Get Error: {r.text}")
            return todos
        except: return []

    def update_todo_status(self, doc_id, is_done):
        """상태 업데이트"""
        url = f"{self.base_url}/todos/{doc_id}?updateMask.fieldPaths=is_done&key={self.api_key}"
        payload = {"fields": {"is_done": {"booleanValue": is_done}}}
        try: requests.patch(url, json=payload)
        except: pass

    def add_comment(self, todo_id, comment_data):
        """댓글 추가"""
        url = f"{self.base_url}/todos/{todo_id}/comments?key={self.api_key}"
        payload = self._to_firestore_data(comment_data)
        try: requests.post(url, json=payload)
        except: pass

    def get_comments(self, todo_id):
        """댓글 조회"""
        url = f"{self.base_url}/todos/{todo_id}/comments?pageSize=50&key={self.api_key}"
        try:
            r = requests.get(url)
            comments = []
            if r.status_code == 200:
                res_json = r.json()
                if 'documents' in res_json:
                    for doc in res_json['documents']:
                        comments.append(self._from_firestore_data(doc))
            # 날짜순 정렬
            comments.sort(key=lambda x: x.get('created_at', ''), reverse=False)
            return comments
        except: return []

   # --------------------------------------------------
    # [업그레이드] QnA 게시판 메서드 (카테고리/탭/FAQ/이력 지원)
    # --------------------------------------------------
    def get_qna_list(self):
        """QnA 목록 조회"""
        url = f"{self.base_url}/qna_posts?pageSize=100&key={self.api_key}"
        try:
            r = requests.get(url)
            posts = []
            if r.status_code == 200:
                res = r.json()
                if 'documents' in res:
                    for doc in res['documents']:
                        posts.append(self._from_firestore_data(doc))
            # 최신순 정렬
            posts.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return posts
        except: return []

    def add_qna(self, data):
        """QnA 등록 (탭/카테고리 포함)"""
        url = f"{self.base_url}/qna_posts?key={self.api_key}"
        
        # 탭 리스트를 Firestore 포맷으로 변환
        tabs_values = []
        for t in data.get('tabs', []):
            tabs_values.append({
                "mapValue": {
                    "fields": {
                        "name": {"stringValue": t['name']},
                        "content": {"stringValue": t['content']}
                    }
                }
            })

        payload = {
            "fields": {
                "title": {"stringValue": data['title']},
                "category": {"stringValue": data.get('category', '일반')},
                "faq_content": {"stringValue": data.get('faq_content', '')},
                "writer": {"stringValue": data['writer']},
                "created_at": {"stringValue": data['created_at']},
                "updated_at": {"stringValue": ""},
                "history": {"arrayValue": {"values": []}},
                "tabs": {"arrayValue": {"values": tabs_values}} # 탭 데이터
            }
        }
        try: return requests.post(url, json=payload).status_code == 200
        except: return False

    def update_qna(self, doc_id, data, history_data):
        """QnA 수정 (탭/카테고리/FAQ 포함)"""
        # 업데이트할 필드 마스크 설정
        fields = "title&updateMask.fieldPaths=category&updateMask.fieldPaths=faq_content&updateMask.fieldPaths=tabs&updateMask.fieldPaths=updated_at&updateMask.fieldPaths=history"
        url = f"{self.base_url}/qna_posts/{doc_id}?updateMask.fieldPaths={fields}&key={self.api_key}"
        
        # History 배열 구성
        history_values = []
        for h in history_data:
            history_values.append({
                "mapValue": {
                    "fields": {
                        "date": {"stringValue": h['date']},
                        "editor": {"stringValue": h['editor']},
                        "prev_content": {"stringValue": h['prev_content']} # 제목만 저장하거나 간략화
                    }
                }
            })

        # Tabs 배열 구성
        tabs_values = []
        for t in data.get('tabs', []):
            tabs_values.append({
                "mapValue": {
                    "fields": {
                        "name": {"stringValue": t['name']},
                        "content": {"stringValue": t['content']}
                    }
                }
            })

        payload = {
            "fields": {
                "title": {"stringValue": data['title']},
                "category": {"stringValue": data.get('category', '일반')},
                "faq_content": {"stringValue": data.get('faq_content', '')},
                "tabs": {"arrayValue": {"values": tabs_values}},
                "updated_at": {"stringValue": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
                "history": {"arrayValue": {"values": history_values}}
            }
        }
        try: return requests.patch(url, json=payload).status_code == 200
        except: return False

    def delete_qna(self, doc_id):
        url = f"{self.base_url}/qna_posts/{doc_id}?key={self.api_key}"
        try: return requests.delete(url).status_code == 200
        except: return False    

# ==========================================
# [엔진 로직] (기존 로직 100% 유지 - 절대 수정 없음)
# ==========================================
class DruwaEngine:
    def __init__(self):
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=3)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        self.base_url = 'https://druwaint.co.kr'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://druwaint.co.kr/manager/login_form.asp',
            'Origin': 'https://druwaint.co.kr'
        }

    def login(self, user_id, user_pw):
        try:
            print(f"LOG: 로그인 시도... {user_id}")
            login_url = f"{self.base_url}/manager/login_form.asp"
            r = self.session.get(login_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(r.text, 'html.parser')
            form = soup.find('form')
            
            action = form.get('action') if form else ''
            post_url = urljoin(login_url, action)
            
            login_data = {}
            if form:
                for inp in form.find_all('input'):
                    name = inp.get('name')
                    if not name: continue
                    if inp.get('type') == 'hidden': login_data[name] = inp.get('value', '')
                    elif 'id' in name.lower(): login_data[name] = user_id
                    elif 'pw' in name.lower() or 'pass' in name.lower(): login_data[name] = user_pw

            self.session.post(post_url, data=login_data, headers=self.headers, timeout=10, verify=False)
            print("LOG: 로그인 요청 완료")
            return True
        except Exception as e:
            print(f"LOG: 로그인 에러 - {e}")
            return False

    def get_data_list(self, sdate, edate, selected_agencies, keyword_mode, keyword, log_callback=None):
        try:
            if log_callback: log_callback(f"📡 조회 시작: {sdate} ~ {edate}")
            target_url = f"{self.base_url}/manager/system_data/search_list.asp"
            payload = {
                'sortcode': 'a.wdate/desc',
                'sdate': sdate, 'edate': edate, 'goodsgubun': '인터넷',
                'perpages': '2000',
                'status_number': '1, 13, 14, 9, 28, 31, 23, 20, 17, 29, 33, 30, 32',
                'datemode': 'applydate', 'sortmode': 'a.number desc',
                'keywordmode': keyword_mode, 'keyword': keyword 
            }
            res = self.session.post(target_url, data=payload, headers=self.headers, timeout=60, verify=False)
            res.encoding = 'utf-8'
            
            soup = BeautifulSoup(res.text, 'html.parser')
            all_rows = soup.find_all('tr')
            if log_callback: log_callback(f"📊 {len(all_rows)}개 행 분석 중...")
            
            data_rows = []
            
            i = 0
            while i < len(all_rows):
                row = all_rows[i]
                
                internal_id_input = row.find('input', {'name': 'number'})
                if not internal_id_input:
                    i += 1
                    continue
                
                internal_id = internal_id_input.get('value')
                cells = row.find_all(['td', 'th'])
                if len(cells) < 12: 
                    i += 1
                    continue

                try:
                    # [수정] 날짜 및 신청대리점(상어통신 등)
                    cell1_parts = list(cells[1].stripped_strings)
                    apply_date = ""
                    apply_agency = "" # 신청 대리점 (예: 상어통신)
                    if len(cell1_parts) >= 1: apply_date = cell1_parts[0]
                    if len(cell1_parts) >= 2: apply_agency = cell1_parts[1]

                    # [핵심 수정] 고객명 및 지역 추출 로직 변경
                    # HTML 구조: <td><span>고객명</span><br>지역</td>
                    # separator='|'를 사용하여 줄바꿈(<br>)을 구분자로 텍스트를 추출합니다.
                    cell2_text = cells[2].get_text(separator='|')
                    cell2_parts = cell2_text.split('|')
                    
                    txt_customer_raw = cell2_parts[0].strip()
                    # 파이프(|)로 나눴을 때 2번째 요소가 있으면 지역 정보로 저장, 없으면 빈 문자열
                    txt_region_raw = cell2_parts[1].strip() if len(cell2_parts) > 1 else "" 

                    # 접수처 (골든대구 등)
                    txt_receipt_place = cells[3].get_text().strip() 

                    # sub_info: 날짜 저장용 (대시보드 날짜 비교에 사용)
                    txt_sub_info = apply_date 

                    txt_receipt_num = cells[4].get_text().strip()
                    txt_status = cells[11].get_text().strip()
                    
                    first_product = cells[6].get_text(strip=True)
                    product_list = [first_product]

                    rowspan_val = 1
                    if cells[0].has_attr('rowspan'):
                        try: rowspan_val = int(cells[0]['rowspan'])
                        except: rowspan_val = 1
                    
                    if rowspan_val > 1:
                        for offset in range(1, rowspan_val):
                            if i + offset < len(all_rows):
                                next_row = all_rows[i + offset]
                                next_cells = next_row.find_all('td')
                                if len(next_cells) >= 4:
                                    sub_product = next_cells[3].get_text(strip=True)
                                    if sub_product: product_list.append(sub_product)

                    final_product_str = " + ".join(product_list)

                    # [수정] 딕셔너리에 'region' 키 추가
                    data_rows.append({
                        'receipt_num': txt_receipt_num, 
                        'product': final_product_str, 
                        'customer': txt_customer_raw, 
                        'region': txt_region_raw,      # [신규 추가] 지역 정보 (서울 마포 등)
                        'sub_info': txt_sub_info,
                        'status': txt_status,
                        'internal_id': internal_id,
                        'agency': apply_agency,        
                        'receipt_place': txt_receipt_place 
                    })
                    
                    i += rowspan_val
                                       
                    
                except Exception as e:
                    print(f"Row Parse Error: {e}")
                    i += 1
                    continue

            return data_rows
            
        except Exception as e:
            if log_callback: log_callback(f"❌ 조회 오류: {e}", "#FF8A80") 
            return None

    def scan_replay_demand(self):
        try:
            # 1. 날짜 계산 (오늘 ~ 3일 전)
            today = datetime.date.today()
            today_str = today.strftime('%Y-%m-%d')
            
            # 3일 전 날짜 계산
            start_date = today - datetime.timedelta(days=3)
            sdate_str = start_date.strftime('%Y-%m-%d')

            target_url = f"{self.base_url}/manager/system_data/search_list.asp"
            
            payload = {
                'sortcode': 'a.wdate/desc',
                'sdate': sdate_str,  # [수정] 3일 전 날짜부터
                'edate': today_str,  # [수정] 오늘까지 조회
                'goodsgubun': '인터넷',
                'perpages': '500',
                'status_number': '1, 13, 14, 9, 28, 31, 23, 20, 17, 29, 33, 30, 32',
                'datemode': 'applydate', 'sortmode': 'a.number desc'
            }
            res = self.session.post(target_url, data=payload, headers=self.headers, timeout=20, verify=False)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            detected_items = []
            for row in soup.find_all('tr'):
                # 회신요망 아이콘(replaydemand.gif)이 있는 행만 추출
                img_tag = row.find('img', src=lambda s: s and 'replaydemand.gif' in s)
                if img_tag:
                    internal_id_input = row.find('input', {'name': 'number'})
                    if internal_id_input:
                        internal_id = internal_id_input.get('value')
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 5:
                            customer = cells[2].get_text(separator='|').split('|')[0].strip()
                            receipt = cells[4].get_text().strip()
                            detected_items.append({'id': internal_id, 'customer': customer, 'receipt': receipt})
            return detected_items
        except: return []

    def fetch_detail_info(self, internal_id, verbose=True):
        try:
            if verbose: print(f"DEBUG: 상세 정보 조회 시작 - {internal_id}")
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            
            # [한글 깨짐 방지]
            res.encoding = 'utf-8' 
            
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 1. 폼 데이터 추출
            container = soup.find('form')
            if not container: container = soup.find('body')
            
            info_dict = {}
            company_options = []

            if container:
                for element in container.find_all(['input', 'select', 'textarea']):
                    name = element.get('name')
                    if not name: continue
                    val = ''
                    if element.name == 'input':
                        if element.get('type') in ['radio', 'checkbox']:
                            if not element.get('checked'): continue
                        val = element.get('value', '')
                    elif element.name == 'select':
                        if name == 'companycode':
                            for opt in element.find_all('option'):
                                opt_val = opt.get('value', '')
                                opt_txt = opt.get_text().strip()
                                if opt_val and opt_txt:
                                    company_options.append({'value': opt_val, 'text': opt_txt})

                        selected_opt = element.find('option', selected=True)
                        if selected_opt:
                            val = selected_opt.get_text().strip()
                            if not val and selected_opt.has_attr('value'): val = selected_opt['value']
                    elif element.name == 'textarea':
                        val = element.get_text().strip()
                    info_dict[name] = val

            # [핵심 수정] applynumber가 폼 안에 없으면 페이지 전체에서 다시 찾기
            if 'applynumber' not in info_dict or not info_dict['applynumber']:
                ap_input = soup.find('input', {'name': 'applynumber'})
                if ap_input:
                    info_dict['applynumber'] = ap_input.get('value', '')

            info_dict['company_options'] = company_options 

            # 2. 상품 목록 추출
            products_list = []
            product_cells = soup.find_all('td', class_='tal-c b')
            for cell in product_cells:
                try:
                    p_name = cell.get_text(strip=True)
                    if not p_name: continue
                    parent_row = cell.find_parent('tr')
                    if not parent_row: continue
                    row_selects = parent_row.find_all('select')
                    current_options = []
                    for sel in row_selects:
                        sel_name = sel.get('name', '')
                        first_opt = sel.find('option')
                        if not first_opt: continue
                        final_val = first_opt.get('value', '').strip()
                        if final_val == '' and not first_opt.has_attr('value'):
                            if first_opt.contents: final_val = str(first_opt.contents[0]).strip()
                        if 'oper' in str(sel_name).lower():
                            if not final_val or "::" in final_val: continue 
                            current_options.append(final_val)
                    products_list.append({'name': p_name, 'options': current_options})
                except Exception: continue

            info_dict['products_list'] = products_list
            return info_dict
        except Exception as e:
            print(f"Detail Fetch Error: {e}")
            return None

    def update_gift_info(self, internal_id, new_text):
        try:
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form: return False

            post_data = []
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['button', 'reset', 'image']: continue
                    if ipt_type in ['radio', 'checkbox']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''

                if name == 'servicesrdata_txt': val = new_text
                post_data.append((name, val))

            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(target_url, form.get('action', 'edit.asp'))
            headers = self.headers.copy()
            headers['Referer'] = target_url
            res_post = self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)
            return res_post.status_code == 200
        except Exception: return False

    def update_agency(self, internal_id, new_code):
        try:
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form: return False

            post_data = []
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['button', 'reset', 'image']: continue
                    if ipt_type in ['radio', 'checkbox']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''

                # [핵심] companycode 값을 사용자가 선택한 값으로 변경
                if name == 'companycode': val = new_code
                
                post_data.append((name, val))

            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(target_url, form.get('action', 'edit.asp'))
            headers = self.headers.copy()
            headers['Referer'] = target_url
            res_post = self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)
            return res_post.status_code == 200
        except Exception: return False

    def update_customer_name(self, internal_id, new_name):
        try:
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form: return False
            post_data = []
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['button', 'reset', 'image']: continue
                    if ipt_type in ['radio', 'checkbox']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''
                if name == 'uname': val = new_name
                post_data.append((name, val))
            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(target_url, form.get('action', 'edit.asp'))
            headers = self.headers.copy()
            headers['Referer'] = target_url
            res_post = self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)
            return res_post.status_code == 200
        except Exception: return False

    def fetch_products_for_completion(self, internal_id):
        try:
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form: return None
            products = []
            customnum_inputs = form.find_all('input', {'name': 'customnum'})
            for idx, inp in enumerate(customnum_inputs):
                real_goods_name = f"상품 {idx+1}"
                try:
                    current_tr = inp.find_parent('tr')
                    if current_tr:
                        prev_tr = current_tr.find_previous_sibling('tr')
                        if prev_tr:
                            name_td = prev_tr.find('td', class_='tal-c b')
                            if name_td: real_goods_name = name_td.get_text(strip=True)
                except Exception: pass
                products.append({'index': idx, 'current_val': inp.get('value', ''), 'goods_name': real_goods_name})
            return products, form.get('action', 'edit.asp') 
        except Exception as e: return None, None

    def submit_receipt_completion(self, internal_id, new_receipt_nums, target_index=None):
        try:
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form: return False
            post_data = []
            current_nums = list(new_receipt_nums)
            status_count = 0 
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['button', 'reset', 'image']: continue 
                    if ipt_type in ['radio', 'checkbox']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''

                if name == 'customnum':
                    if len(current_nums) > 0: val = current_nums.pop(0)
                elif name == 'status':
                    if target_index is None: val = '14' 
                    elif status_count == target_index: val = '14'
                    status_count += 1
                post_data.append((name, val))
            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(target_url, form.get('action', 'edit.asp'))
            headers = self.headers.copy()
            headers['Referer'] = target_url
            res_post = self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)
            return res_post.status_code == 200
        except Exception: return False

    def process_assignment(self, receipt_num, assigned_date, log_callback):
        try:
            today = datetime.date.today()
            s_date = (today - datetime.timedelta(days=70)).strftime('%Y-%m-%d')
            e_date = (today + datetime.timedelta(days=5)).strftime('%Y-%m-%d')
            
            search_url = f"{self.base_url}/manager/system_data/search_list.asp"
            payload = {
                'perpages': '15', 'sdate': s_date, 'edate': e_date,
                'datemode': 'applydate', 'sortmode': 'a.number desc',
                'status_number': '1, 13, 14, 9, 28, 31, 23, 20, 17, 29, 33, 30, 32',
                'keywordmode': 'aa.customnum', 'keyword': receipt_num
            }
            headers = self.headers.copy()
            headers['Referer'] = f'{self.base_url}/manager/system_data/list.asp'
            res_search = self.session.post(search_url, data=payload, headers=headers, timeout=10, verify=False)
            soup_search = BeautifulSoup(res_search.text, 'html.parser')
            
            internal_id = None
            for tr in soup_search.find_all('tr'):
                chk = tr.find('input', {'name': 'number'})
                if chk and receipt_num in tr.get_text():
                    internal_id = chk.get('value')
                    break
            
            if not internal_id:
                log_callback(f"❌ 실패: {receipt_num} (검색 실패)", "#FF8A80")
                return False

            edit_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res_form = self.session.get(edit_url, headers=headers, timeout=10, verify=False)
            soup_form = BeautifulSoup(res_form.text, 'html.parser')
            form = soup_form.find('form')
            if not form:
                log_callback(f"❌ 실패: {receipt_num} (폼 없음)", "#FF8A80")
                return False

            post_data = []
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['checkbox', 'radio']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''

                if name == 'wantdate': val = assigned_date
                post_data.append((name, val))

            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(edit_url, form.get('action', 'edit.asp'))
            headers['Referer'] = edit_url 
            res_save = self.session.post(save_url, data=post_data, headers=headers, timeout=10, verify=False)
            
            if res_save.status_code == 200:
                if "오류" in res_save.text or "실패" in res_save.text:
                      log_callback(f"⚠️ 경고: {receipt_num} (서버 에러 메시지)", "#FFCC80")
                else:
                    log_callback(f"🎉 성공: {receipt_num} -> {assigned_date}", "#A5D6A7")
                return True
            else:
                log_callback(f"❌ 실패: {receipt_num} (HTTP {res_save.status_code})", "#FF8A80")
                return False
        except Exception as e:
            log_callback(f"❌ 에러: {receipt_num} ({e})", "#FF8A80")
            return False

    def process_opening(self, receipt_num, install_date, log_callback):
        try:
            today = datetime.date.today()
            s_date = (today - datetime.timedelta(days=70)).strftime('%Y-%m-%d')
            e_date = (today + datetime.timedelta(days=5)).strftime('%Y-%m-%d')
            
            search_url = f"{self.base_url}/manager/system_data/search_list.asp"
            payload = {
                'perpages': '15', 'sdate': s_date, 'edate': e_date,
                'datemode': 'applydate', 'sortmode': 'a.number desc',
                'status_number': '1, 13, 14, 9, 28, 31, 23, 20, 17, 29, 33, 30, 32',
                'keywordmode': 'aa.customnum', 'keyword': receipt_num
            }
            headers = self.headers.copy()
            headers['Referer'] = f'{self.base_url}/manager/system_data/list.asp'
            res_search = self.session.post(search_url, data=payload, headers=headers, timeout=10, verify=False)
            soup_search = BeautifulSoup(res_search.text, 'html.parser')
            
            internal_id = None
            for tr in soup_search.find_all('tr'):
                chk = tr.find('input', {'name': 'number'})
                if chk and receipt_num in tr.get_text():
                    internal_id = chk.get('value')
                    break
            
            if not internal_id:
                log_callback(f"❌ 실패: {receipt_num} (검색 실패)", "#FF8A80")
                return False

            edit_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res_form = self.session.get(edit_url, headers=headers, timeout=10, verify=False)
            soup_form = BeautifulSoup(res_form.text, 'html.parser')
            form = soup_form.find('form')
            if not form:
                log_callback(f"❌ 실패: {receipt_num} (폼 없음)", "#FF8A80")
                return False

            post_data = []
            target_keywords = ['SKB인터넷', 'SKB_IPTV', 'SKB_POPTV', 'SKB_다셋탑', 'SKB_다셋탑2', 'SKB_다셋탑3','SKB소호인터넷', 'SKB소호_TV', 'SKB소호_다셋탑', 'SKB소호_다셋탑2',]

            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                current_val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['checkbox', 'radio']:
                        if not el.get('checked'): continue
                    current_val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    current_val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    current_val = el.string if el.string else ''

                is_target_product = False
                try:
                    row = el.find_parent('tr')
                    if row:
                        header = row.find('th')
                        if header:
                            header_text = header.get_text()
                            if any(k in header_text for k in target_keywords): is_target_product = True
                            
                        if not is_target_product:
                            prev_row = row.find_previous_sibling('tr')
                            if prev_row:
                                prev_header = prev_row.find('th')
                                if prev_header:
                                    prev_header_text = prev_header.get_text()
                                    if any(k in prev_header_text for k in target_keywords): is_target_product = True
                except: pass

                final_val = current_val
                if name == 'installdate':
                    if is_target_product: final_val = install_date
                elif name == 'status':
                    if is_target_product: final_val = '29' 
                post_data.append((name, final_val))

            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(edit_url, form.get('action', 'edit.asp'))
            headers['Referer'] = edit_url 
            res_save = self.session.post(save_url, data=post_data, headers=headers, timeout=10, verify=False)
            
            if res_save.status_code == 200:
                log_callback(f"🎉 성공: {receipt_num} -> {install_date} (완료)", "#81D4FA")
                return True
            else:
                log_callback(f"❌ 실패: {receipt_num} (HTTP {res_save.status_code})", "#FF8A80")
                return False
        except Exception as e:
            log_callback(f"❌ 에러: {receipt_num} ({e})", "#FF8A80")
            return False

    def fetch_memo_data(self, internal_id):
        try:
            print(f"DEBUG: Fetching memo for ID {internal_id}")
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            res.encoding = 'utf-8' 
            soup = BeautifulSoup(res.text, 'html.parser')
            
            apply_number = ""
            for inp in soup.find_all('input'):
                if inp.get('name') == 'applynumber':
                    apply_number = inp.get('value', '')
                    break
            
            memo_list = []
            all_rows = soup.find_all('tr')
            for row in all_rows:
                content_td = row.find('td', class_='tal-l')
                if not content_td: continue
                cols = row.find_all('td')
                if len(cols) >= 6:
                    try:
                        writer_text = cols[1].get_text(strip=True)
                        writer_clean = writer_text.replace("(", "").replace(")", "").replace("관리자", "").strip()
                        content_text = content_td.get_text(separator=" ", strip=True)
                        date_text = cols[5].get_text(strip=True)
                        if '-' in date_text:
                             memo_list.append({
                                'writer': writer_clean if writer_clean else "관리자",
                                'content': content_text,
                                'date': date_text
                            })
                    except Exception as ex: continue
            return apply_number, memo_list
        except Exception as e:
            print(f"Memo Fetch Error: {e}")
            return None, []

    def submit_new_memo(self, apply_number, content, writer, is_secret=False, is_reply_request=False):
        try:
            target_url = f'{self.base_url}/manager/system_data/apply_memo_edit.asp'
            payload = {
                'applynumber': apply_number, 'mode': 'insert',
                'writer': writer, 'gubun': '관리자',
                'content': content,
                'secretcode': 'Y' if is_secret else '',
                'replaydemandYN': 'Y' if is_reply_request else ''
            }
            headers = self.headers.copy()
            headers['Referer'] = f'{self.base_url}/manager/system_data/edit_form.asp'
            res = self.session.post(target_url, data=payload, headers=headers, timeout=10, verify=False)
            return res.status_code == 200
        except Exception as e:
            print(f"Memo Submit Error: {e}")
            return False

    def submit_return_status(self, internal_id, new_receipt_nums, target_index=None):
        try:
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form: return False
            post_data = []
            current_nums = list(new_receipt_nums)
            status_count = 0 
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['button', 'reset', 'image']: continue 
                    if ipt_type in ['radio', 'checkbox']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''

                if name == 'customnum':
                    if len(current_nums) > 0: val = current_nums.pop(0)
                elif name == 'status':
                    if target_index is None: val = '32'
                    elif status_count == target_index: val = '32'
                    status_count += 1
                post_data.append((name, val))
            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(target_url, form.get('action', 'edit.asp'))
            headers = self.headers.copy()
            headers['Referer'] = target_url
            res_post = self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)
            return res_post.status_code == 200
        except Exception: return False

# [수정] 채무불이행 처리: 상태변경(17) + 메모등록 API 호출
    def submit_debt_default(self, internal_id, user_id):
        try:
            # 1. 폼 데이터 로딩
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            
            # [중요] 메모 등록을 위해 applynumber(접수번호) 추출
            apply_number = ""
            ap_input = soup.find('input', {'name': 'applynumber'})
            if ap_input: apply_number = ap_input.get('value', '')

            # 2. 상태값 변경 (모든 상품 status -> 17)
            if form:
                post_data = []
                for el in form.find_all(['input', 'select', 'textarea']):
                    name = el.get('name')
                    if not name: continue
                    val = ''
                    
                    if el.name == 'input':
                        ipt_type = el.get('type', 'text').lower()
                        if ipt_type in ['button', 'reset', 'image']: continue
                        if ipt_type in ['radio', 'checkbox']:
                            if not el.get('checked'): continue
                        val = el.get('value', '')
                    elif el.name == 'select':
                        opt = el.find('option', selected=True)
                        val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                    elif el.name == 'textarea':
                        val = el.string if el.string else ''

                    # [핵심] 상태를 17(개통불가)로 변경
                    if name == 'status': 
                        val = '17'
                    
                    post_data.append((name, val))

                if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
                save_url = urljoin(target_url, form.get('action', 'edit.asp'))
                headers = self.headers.copy()
                headers['Referer'] = target_url
                
                # 상태 변경 전송
                self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)

            # 3. 메모 별도 등록 ("채무불이행 고객입니다.")
            if apply_number:
                # 기존에 정의된 submit_new_memo 메서드 재활용
                self.submit_new_memo(apply_number, "채무불이행 고객입니다.", user_id)
            
            return True
        except Exception as e:
            print(f"Debt Default Error: {e}")
            return False

    def set_products_status_investigation(self, internal_id):
        try:
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')
            if not form: return False
            post_data = []
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['button', 'reset', 'image']: continue
                    if ipt_type in ['radio', 'checkbox']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''

                if name == 'status': val = '33'
                post_data.append((name, val))
            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            save_url = urljoin(target_url, form.get('action', 'edit.asp'))
            headers = self.headers.copy()
            headers['Referer'] = target_url
            res_post = self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)
            return res_post.status_code == 200
        except Exception as e:
            print(f"Update Status Error: {e}")
            return False    

    # ==============================================================================
    # [코딩마스타 추가] 퀵메뉴(부재, 계좌오류, 영업불량, 공사, 미인증) 통합 상태 변경 메서드
    # ==============================================================================
    def update_product_status(self, internal_id, status_text):
        try:
            # 1. 상태 텍스트를 시스템 코드(숫자)로 변환
            # (시스템 분석 결과: 17=개통불가, 9=확인요망, 1=신청, 30=공사확인중)
            status_map = {
                "개통불가": "17",
                "확인요망": "9",
                "부재": "9",      # 부재 시 확인요망 처리
                "계좌오류": "9",  # 계좌오류 시 확인요망 처리
                "영업불량": "17", # 영업불량 시 개통불가 처리
                "접수중": "13",
                "공사확인중": "30" # [신규 추가] 공사확인중 코드
            }
                  
            target_code = status_map.get(status_text, "9") # 기본값 9

            # 2. 폼 데이터 로딩
            target_url = f'{self.base_url}/manager/system_data/edit_form.asp?number={internal_id}'
            res = self.session.get(target_url, headers=self.headers, timeout=10, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            form = soup.find('form')

            if not form: return False

            # 3. 데이터 패킹 및 상태값 변경
            post_data = []
            for el in form.find_all(['input', 'select', 'textarea']):
                name = el.get('name')
                if not name: continue
                val = ''
                
                if el.name == 'input':
                    ipt_type = el.get('type', 'text').lower()
                    if ipt_type in ['button', 'reset', 'image']: continue
                    if ipt_type in ['radio', 'checkbox']:
                        if not el.get('checked'): continue
                    val = el.get('value', '')
                elif el.name == 'select':
                    opt = el.find('option', selected=True)
                    val = opt.get('value', '') if opt else (el.find('option').get('value', '') if el.find('option') else '')
                elif el.name == 'textarea':
                    val = el.string if el.string else ''

                # [핵심] 상태값 강제 변경
                if name == 'status': 
                    val = target_code
                
                post_data.append((name, val))

            if not any(k == 'mode' for k, v in post_data): post_data.append(('mode', 'update'))
            
            # 4. 서버 전송
            save_url = urljoin(target_url, form.get('action', 'edit.asp'))
            headers = self.headers.copy()
            headers['Referer'] = target_url
            
            res_post = self.session.post(save_url, data=post_data, headers=headers, timeout=20, verify=False)
            
            if res_post.status_code == 200:
                print(f"LOG: 상태 변경 성공 ID:{internal_id} -> {status_text}({target_code})")
                return True
            else:
                return False

        except Exception as e:
            print(f"Update Status Error: {e}")
            return False

# 전역 변수
data_store = []
doyoon_details = {"return": [], "proc": [], "check": [], "apply": [], "unopened": []}
ITEMS_PER_PAGE = 30
current_page = 1

# ==================================================================
# [핵심 수정] app_state를 전역 변수로 선언 (어디서든 접근 가능하게)
# ==================================================================
app_state = {"active_copy_handler": None}


# ==========================================
# [UI 메인 - Modern SaaS Design Refactor]
# ==========================================
def main(page: ft.Page):
    # 1. Page Configuration
    page.title = "Doyoon Workspace"
    page.window.width = 1200  # Wide format by default
    page.window.height = 800
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#F7F9FC"  # Modern Light Grey BG
    page.padding = 0  # Full width layout
    page.fonts = {"Pretendard": "https://github.com/orioncactus/pretendard/blob/master/packages/pretendard/dist/public/static/alternative/Pretendard-Regular.otf?raw=true"}
    page.theme = ft.Theme(font_family="Pretendard", color_scheme_seed="#5E35B1")
    
    # [수정됨] 키보드 이벤트 핸들러 (app_state 사용)
    def on_keyboard_event(e: ft.KeyboardEvent):
        if e.key == "F2":
            # 우리가 만든 딕셔너리에서 핸들러를 가져옵니다.
            active_handler = app_state.get("active_copy_handler")
            if active_handler:
                active_handler(None)

    page.on_keyboard_event = on_keyboard_event
    # ==================================================================

    # [추가] 제목 표시줄 숨기기 (UI 확장) & 기본 버튼(최소화/닫기)은 유지
    page.window.title_bar_hidden = False
    page.window.title_bar_buttons_hidden = False

    # 2. Modern Color Palette
    class Colors:
        BG_MAIN = "#F7F9FC"
        BG_SIDEBAR = "#FFFFFF"
        BG_CARD = "#FFFFFF"
        PRIMARY = "#5E35B1"      # Deep Purple
        PRIMARY_LIGHT = "#EDE7F6"
        ACCENT = "#7E57C2"
        TEXT_MAIN = "#1A1C1E"
        TEXT_SUB = "#6C757D"
        BORDER = "#E0E0E0"
        SUCCESS = "#00C853"      # Vivid Green
        WARNING = "#FFAB00"      # Amber
        ERROR = "#D50000"        # Red
        INFO = "#2962FF"         # Blue

    engine = DruwaEngine()
    
    # [추가] Firebase 인스턴스 생성
    fs_manager = FirestoreManager()
    rate_manager = RateManager() # 요금 계산기 인스턴스
    
    # To-Do UI 상태 변수
    todo_list_view = ft.ListView(expand=True, spacing=10, padding=10)
    
    # ---------------------------------------------------
    # [수정] 저장된 로그인 정보 불러오기 (JSON 방식 - 에러 해결)
    # ---------------------------------------------------
    CONFIG_FILE = "login_info.json"
    
    # 기본값 초기화
    saved_id_val = ""
    saved_pw_val = ""
    is_checked = False

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                saved_id_val = data.get("id", "")
                saved_pw_val = data.get("pw", "")
                # 값이 있으면 체크박스 체크
                if saved_id_val: is_checked = True
        except: pass

    # ---------------------------------------------------
    # [수정] Login Controllers (불러온 값 적용)
    # ---------------------------------------------------
    tf_id = ft.TextField(
        label="ID", 
        value=saved_id_val,  # 불러온 ID 적용
        width=300, 
        border_radius=8, 
        bgcolor="white", 
        filled=True,
        # 한글 입력 방지 (영문/숫자/특수문자만 허용)
        input_filter=ft.InputFilter(regex_string=r"^[a-zA-Z0-9!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]*$")
    )
    
    tf_pw = ft.TextField(
        label="PW", 
        value=saved_pw_val,  # 불러온 PW 적용
        password=True, 
        width=300, 
        border_radius=8, 
        bgcolor="white", 
        filled=True, 
        can_reveal_password=True
    )
    
    # 불러온 상태에 따라 체크박스 값 설정
    chk_save_pw = ft.Checkbox(label="정보 저장", value=is_checked, active_color=Colors.PRIMARY)
    
    prog_login = ft.ProgressBar(visible=False, color=Colors.PRIMARY, width=300)

    # ---------------------------------------------------
    # [3] State Variables & Controllers
    # ---------------------------------------------------
    notification_items = [] 
    is_alarm_active = False 

    # [수정] Login Controllers (영문 입력 제한 + 저장 체크박스 추가)
    tf_id = ft.TextField(
        label="ID", 
        width=300, 
        border_radius=8, 
        bgcolor="white", 
        filled=True,
        # [핵심] 한글 입력 방지 (영문, 숫자, 특수문자만 허용하는 정규식)
        input_filter=ft.InputFilter(regex_string=r"^[a-zA-Z0-9!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]*$")
    )
    
    tf_pw = ft.TextField(
        label="PW", 
        password=True, 
        width=300, 
        border_radius=8, 
        bgcolor="white", 
        filled=True, 
        can_reveal_password=True
    )
    
    # [추가] 정보 저장 체크박스
    chk_save_pw = ft.Checkbox(label="정보 저장", value=False, active_color=Colors.PRIMARY)
    
    prog_login = ft.ProgressBar(visible=False, color=Colors.PRIMARY, width=300)

    # ---------------------------------------------------
    # [3.1] 뽀모도로 타이머 로직 (Overlay 팝업 + PubSub 갱신)
    # ---------------------------------------------------
    
    # 1. 상태 변수
    pomo_state = {
        "focus_min": 25, "break_min": 5,
        "current_left": 25 * 60,
        "is_running": False,
        "mode": "focus", 
        "total_time": 25 * 60
    }

    # 2. UI 컴포넌트
    txt_pomo_time = ft.Text("25:00", size=14, weight="bold", color=Colors.PRIMARY)
    bar_pomo_progress = ft.ProgressBar(width=100, value=0, color=Colors.PRIMARY, bgcolor="#E1BEE7", height=6)
    
    def on_click_pomo_wrapper(e):
        pomo_state["is_running"] = not pomo_state["is_running"]
        # 화면 갱신 요청 (PubSub)
        page.pubsub.send_all({'topic': 'pomo_tick', 'payload': None})

    btn_pomo_action = ft.FilledButton(
        "업무시작", 
        width=80, 
        height=30, 
        style=ft.ButtonStyle(padding=0, shape=ft.RoundedRectangleBorder(radius=6), bgcolor=Colors.PRIMARY), 
        on_click=on_click_pomo_wrapper
    )
    
    # 3. 설정 입력창
    tf_set_focus = ft.TextField(label="집중(분)", value="25", width=80, text_size=12, height=35, content_padding=10)
    tf_set_break = ft.TextField(label="휴식(분)", value="5", width=80, text_size=12, height=35, content_padding=10)

    # 4. 설정 저장 함수
    def on_save_pomo_setting(e):
        try:
            f_min = int(tf_set_focus.value)
            b_min = int(tf_set_break.value)
            pomo_state["focus_min"] = f_min
            pomo_state["break_min"] = b_min
            
            pomo_state["is_running"] = False
            pomo_state["mode"] = "focus"
            pomo_state["current_left"] = f_min * 60
            pomo_state["total_time"] = f_min * 60
            
            # [핵심 복구] 팝업 닫기
            dlg_pomo_setting.open = False
            page.update()
            
            # 갱신 신호 전송
            page.pubsub.send_all({'topic': 'pomo_tick', 'payload': None})
            
            page.snack_bar = ft.SnackBar(ft.Text("설정이 저장되었습니다."), bgcolor=Colors.SUCCESS)
            page.snack_bar.open = True
            page.update()
        except: pass

    # 5. 다이얼로그 미리 생성
    dlg_pomo_setting = ft.AlertDialog(
        modal=True,
        title=ft.Text("타이머 설정"),
        content=ft.Row([tf_set_focus, tf_set_break], alignment="center", height=60),
        actions=[
            # 취소 버튼: 닫기 + 업데이트
            ft.TextButton("취소", on_click=lambda e: setattr(dlg_pomo_setting, 'open', False) or page.update()),
            ft.TextButton("저장", on_click=on_save_pomo_setting)
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # [핵심 복구] 팝업 열기 함수 (Overlay 방식)
    def open_pomo_setting(e):
        # 오버레이에 없으면 추가
        if dlg_pomo_setting not in page.overlay:
            page.overlay.append(dlg_pomo_setting)
        
        # 열기
        dlg_pomo_setting.open = True
        page.update()

    # 6. 타이머 쓰레드
    def start_pomo_thread():
        def _run():
            while True:
                if pomo_state["is_running"]:
                    if pomo_state["current_left"] > 0:
                        pomo_state["current_left"] -= 1
                    else:
                        pomo_state["is_running"] = False
                        if pomo_state["mode"] == "focus":
                            pomo_state["mode"] = "break"
                            pomo_state["current_left"] = pomo_state["break_min"] * 60
                            pomo_state["total_time"] = pomo_state["break_min"] * 60
                            page.pubsub.send_all({'topic': 'toast', 'payload': {'msg': '☕ 집중 끝! 휴식하세요.', 'color': Colors.SUCCESS}})
                            try:
                                if platform.system() == 'Windows' and notification:
                                    notification.notify(title="도윤 타이머", message="집중 끝! 휴식하세요.", timeout=5)
                            except: pass
                        else:
                            pomo_state["mode"] = "focus"
                            pomo_state["current_left"] = pomo_state["focus_min"] * 60
                            pomo_state["total_time"] = pomo_state["focus_min"] * 60
                            page.pubsub.send_all({'topic': 'toast', 'payload': {'msg': '🔥 휴식 끝! 업무 시작하세요.', 'color': Colors.PRIMARY}})
                            try:
                                if platform.system() == 'Windows' and notification:
                                    notification.notify(title="도윤 타이머", message="휴식 끝! 업무 시작!", timeout=5)
                            except: pass
                    
                    # 갱신 신호 전송
                    page.pubsub.send_all({'topic': 'pomo_tick', 'payload': None})
                
                time.sleep(1)
        
        threading.Thread(target=_run, daemon=True).start()

    # 7. 최종 컨테이너
    container_pomo = ft.Container(
        content=ft.Row([
            ft.Column([
                txt_pomo_time,
                bar_pomo_progress
            ], spacing=2, alignment="center"),
            btn_pomo_action,
            ft.IconButton(
                icon=ft.Icons.SETTINGS, 
                icon_size=16, 
                icon_color=Colors.TEXT_SUB, 
                on_click=open_pomo_setting, 
                tooltip="시간 설정"
            )
        ], vertical_alignment="center", spacing=10),
        padding=ft.Padding(10, 5, 10, 5),
        bgcolor="white",
        border_radius=8,
        border=ft.Border.all(1, "#EEEEEE")
    )

    # Dashboard & Data Controllers
    txt_dash_update = ft.Text("업데이트 대기중...", size=11, color=Colors.TEXT_SUB)
    
    # Stat Placeholders
    txt_cnt_apply = ft.Text("-", size=28, weight="bold", color=Colors.SUCCESS)
    txt_cnt_proc = ft.Text("-", size=28, weight="bold", color=Colors.WARNING)
    txt_cnt_done = ft.Text("-", size=28, weight="bold", color=Colors.INFO)
    
    txt_m_cnt_apply = ft.Text("-", size=28, weight="bold", color=Colors.ERROR)
    txt_m_cnt_proc = ft.Text("-", size=28, weight="bold", color=Colors.WARNING)
    txt_m_cnt_done = ft.Text("-", size=28, weight="bold", color=Colors.INFO)
    
    txt_dy_return = ft.Text("-", size=28, weight="bold", color=Colors.ERROR)
    txt_dy_proc = ft.Text("-", size=28, weight="bold", color=Colors.WARNING)
    txt_dy_check = ft.Text("-", size=28, weight="bold", color=Colors.ACCENT)
    txt_dy_apply = ft.Text("-", size=28, weight="bold", color=Colors.SUCCESS) 
    txt_dy_unopened = ft.Text("-", size=28, weight="bold", color="#5D4037")

    # Inputs for Work Tabs
    tf_input_assign = ft.TextField(multiline=True, min_lines=10, hint_text="[접수번호] [날짜] 형식으로 입력하세요", text_size=13, border_radius=8, bgcolor="white", expand=True, border_color=Colors.BORDER)
    tf_input_opening = ft.TextField(multiline=True, min_lines=10, hint_text="[접수번호] [날짜] 형식으로 입력하세요", text_size=13, border_radius=8, bgcolor="white", expand=True, border_color=Colors.BORDER)

    # Progress Bars
    prog_assign = ft.ProgressBar(visible=False, color=Colors.PRIMARY)
    prog_opening = ft.ProgressBar(visible=False, color=Colors.PRIMARY)
    prog_search = ft.ProgressBar(visible=False, color=Colors.PRIMARY)
    prog_complete = ft.ProgressBar(visible=False, color=Colors.PRIMARY)

    # Result Lists
    result_list = ft.ListView(expand=True, spacing=5, padding=2) # Compact Padding
    result_list_complete = ft.ListView(expand=True, spacing=10, padding=10)
    
    # Logs
    log_area_search = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    log_area_assign = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    log_area_opening = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    log_area_complete = ft.ListView(expand=True, spacing=2, auto_scroll=True)

    # Pagination Controls
    txt_page_info = ft.Text("1 / 1", size=12, weight="bold")
    btn_prev_page = ft.IconButton(ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_size=14, disabled=True)
    btn_next_page = ft.IconButton(ft.Icons.ARROW_FORWARD_IOS_ROUNDED, icon_size=14, disabled=True)

    def open_bottom_sheet_subscription(internal_id, customer_name):
        current_user_id = tf_id.value
        win_w = page.width if page.width else 1200
        bs_sub_panel.width = (win_w - 100) * 0.95
        
        # 1. UI 초기화
        bs_sub_column.controls.clear()
        
        # [레이아웃 분할]
        left_info_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=6)
        right_calc_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=4)
        
        btn_close = ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: close_sub_sheet(), icon_color=Colors.TEXT_SUB)

        # --------------------------------------------------------------
        # [우측] 요금 계산기 (검증 로직 제거됨)
        # --------------------------------------------------------------
        try:
            rates = rate_manager.data if 'rate_manager' in locals() or 'rate_manager' in globals() else {}
        except: rates = {}

        calc_state = {
            'internet': '선택안함', 'wifi': '선택안함', 'discount': '선택안함',
            'iptv': '선택안함', 'stb': '선택안함',
            'multitv': '선택안함', 'multistb': '선택안함',
            'addon_safe': '선택안함', 'pop': '선택안함',
            'pre_inet': '선택안함', 'pre_iptv': '선택안함', 'pre_mtv': '선택안함'
        }

        # 데이터 저장소
        fetched_calc_data = {'original_price': 0} 
        latest_rec_amounts = {'inet': 0, 'iptv': 0, 'mtv': 0, 'total': 0} # 추천 금액 저장

        txt_result = ft.Text("0 원", size=24, weight="bold", color=Colors.PRIMARY)
        txt_recommend = ft.Text("데이터 로딩 대기...", size=11, color=Colors.TEXT_MAIN, weight="bold", no_wrap=False)
        container_recommend = ft.Container(content=txt_recommend, bgcolor="#FFF3E0", padding=ft.Padding(10,5,10,5), border_radius=6, visible=False, expand=True)

        # [함수] 재계산 및 추천 생성
        def recalc(e=None):
            try:
                if not rates: return
                
                # 1. 요금 계산
                sels = calc_state.copy()
                sels['addon_wings'] = chk_wings.value 
                base_total = rate_manager.calculate(sels)
                
                def get_pre_val(key):
                    v_str = calc_state.get(key, '선택안함')
                    if v_str == '선택안함': return 0
                    return int(v_str.replace('원','').replace(',',''))
                
                total_prepaid = get_pre_val('pre_inet') + get_pre_val('pre_iptv') + get_pre_val('pre_mtv')
                final_total = base_total - total_prepaid
                
                txt_result.value = f"{final_total:,} 원"
                txt_result.update()

                # 2. 선납권 추천 로직
                original_price = fetched_calc_data.get('original_price', 0)
                
                # 값 초기화
                latest_rec_amounts['inet'] = 0; latest_rec_amounts['iptv'] = 0
                latest_rec_amounts['mtv'] = 0; latest_rec_amounts['total'] = 0

                if original_price > 0:
                    container_recommend.visible = True
                    gap = base_total - original_price 
                    
                    if gap > 0:
                        import math
                        needed = math.ceil(gap / 1100) * 1100
                        rem_needed = needed
                        
                        rec_inet = 0; rec_iptv = 0; rec_mtv = 0
                        
                        # 상품 선택 여부에 따라 최대 7700원씩 배정
                        if calc_state['internet'] != '선택안함': rec_inet = min(rem_needed, 7700); rem_needed -= rec_inet
                        if calc_state['iptv'] != '선택안함': rec_iptv = min(rem_needed, 7700); rem_needed -= rec_iptv
                        if calc_state['multitv'] != '선택안함': rec_mtv = min(rem_needed, 7700); rem_needed -= rec_mtv
                        
                        # [중요] 계산 결과를 변수에 저장 (버튼 동작용)
                        latest_rec_amounts['inet'] = rec_inet
                        latest_rec_amounts['iptv'] = rec_iptv
                        latest_rec_amounts['mtv'] = rec_mtv
                        latest_rec_amounts['total'] = rec_inet + rec_iptv + rec_mtv
                            
                        rec_parts = []
                        if rec_inet > 0: rec_parts.append(f"인{rec_inet:,}")
                        if rec_iptv > 0: rec_parts.append(f"티{rec_iptv:,}")
                        if rec_mtv > 0: rec_parts.append(f"다{rec_mtv:,}")
                        rec_str = " + ".join(rec_parts) if rec_parts else "한도초과"
                        
                        if rem_needed > 0:
                            msg = f"⚠️ 인상분 {gap:,}원\n👉 최대: {rec_str} (부족: {rem_needed:,})"
                            container_recommend.bgcolor = "#FFEBEE"; txt_recommend.color = "#C62828"
                        else:
                            if total_prepaid >= needed:
                                msg = f"✅ 인상분 {gap:,}원 해결"; container_recommend.bgcolor = "#E8F5E9"; txt_recommend.color = "#2E7D32"
                            else:
                                msg = f"💡 인상분 {gap:,}원\n👉 추천: [{rec_str}]"; container_recommend.bgcolor = "#FFF8E1"; txt_recommend.color = "#F57F17"
                    else:
                        msg = f"👍 기존({original_price:,}원)보다 저렴/동일"; container_recommend.bgcolor = "#E3F2FD"; txt_recommend.color = "#1565C0"
                    
                    txt_recommend.value = msg; txt_recommend.update(); container_recommend.update()
                else:
                    container_recommend.visible = False; container_recommend.update()

            except Exception as ex:
                print(f"Recalc Error: {ex}")

        # UI 생성 헬퍼
        def mk_select_btn(label, key, options_dict):
            keys = list(options_dict.keys()) if options_dict else []
            display_text = ft.Text(calc_state[key], size=11, color=Colors.TEXT_MAIN, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
            def on_select(e):
                calc_state[key] = e.control.data; display_text.value = e.control.data; display_text.update(); recalc()
            menu_items = [ft.PopupMenuItem(content=ft.Text(k, size=12), data=k, on_click=on_select, height=30) for k in keys]
            content_ui = ft.Container(content=ft.Row([display_text, ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=16, color=Colors.TEXT_SUB)], alignment="spaceBetween"), bgcolor="white", padding=ft.Padding(10,0,5,0), border=ft.Border.all(1, Colors.BORDER), border_radius=4, height=30)
            return ft.Column([ft.Text(label, size=11, weight="bold", color=Colors.TEXT_SUB), ft.PopupMenuButton(content=content_ui, items=menu_items)], spacing=2, expand=True)

        ui_inet = mk_select_btn("인터넷", 'internet', rates.get('internet', {}))
        ui_wifi = mk_select_btn("와이파이", 'wifi', rates.get('wifi', {}))
        ui_disc = mk_select_btn("결합", 'discount', rates.get('discount', {}))
        ui_iptv = mk_select_btn("IPTV", 'iptv', rates.get('iptv', {}))
        ui_stb = mk_select_btn("셋탑", 'stb', rates.get('stb', {}))
        ui_mtv = mk_select_btn("다셋탑(TV)", 'multitv', rates.get('multitv', {}))
        ui_mstb = mk_select_btn("다셋탑(STB)", 'multistb', rates.get('multistb', {}))
        ui_safe = mk_select_btn("부가서비스", 'addon_safe', rates.get('addon', {}))
        
        prepaid_opts = {'선택안함': 0}
        for i in range(1, 8): prepaid_opts[f"{i*1100:,}원"] = i*1100
        ui_pre_inet = mk_select_btn("선납(인터넷)", 'pre_inet', prepaid_opts)
        ui_pre_iptv = mk_select_btn("선납(IPTV)", 'pre_iptv', prepaid_opts)
        ui_pre_mtv = mk_select_btn("선납(다셋탑)", 'pre_mtv', prepaid_opts)
        
        chk_wings = ft.Checkbox(label="Wings", value=False, on_change=lambda e: recalc())

        # 시뮬레이터 UI 강제 업데이트 함수
        def update_sim_link(key, val, ui_ctrl):
            if key and val:
                calc_state[key] = val
                try: ui_ctrl.controls[1].content.content.controls[0].value = val; ui_ctrl.update()
                except: pass
                recalc()

        def on_click_load_info(e):
            data = fetched_calc_data.get('data')
            if not data: return
            def set_v(key, ui):
                val = "선택안함"
                if key in data:
                    opts = list(rate_manager.data.get(key, {}).keys()) if key != 'internet' else list(rate_manager.data['internet'].keys())
                    for k in opts:
                        if k == data[key] or (data[key] in k and data[key] != "선택안함"): val = k; break
                update_sim_link(key, val, ui)
            set_v('internet', ui_inet); set_v('wifi', ui_wifi); set_v('discount', ui_disc)
            set_v('iptv', ui_iptv); set_v('stb', ui_stb); set_v('addon', ui_safe)
            set_v('multitv', ui_mtv); set_v('multistb', ui_mstb)
            if 'wings' in data: chk_wings.value = data['wings']; chk_wings.update()
            update_sim_link('pre_inet', '선택안함', ui_pre_inet)
            update_sim_link('pre_iptv', '선택안함', ui_pre_iptv)
            update_sim_link('pre_mtv', '선택안함', ui_pre_mtv)
            page.snack_bar = ft.SnackBar(ft.Text("상품 정보 적용 완료"), bgcolor=Colors.SUCCESS); page.snack_bar.open=True; page.update()

        btn_load_info = ft.FilledButton("상품정보 가져오기", icon=ft.Icons.DOWNLOAD_ROUNDED, on_click=on_click_load_info, height=30, style=ft.ButtonStyle(padding=5))

        right_calc_col.controls = [
            ft.Container(
                content=ft.Column([
                    ft.Row([ft.Text("💰 업셀링 요금 시뮬레이터", size=14, weight="bold"), btn_load_info], alignment="spaceBetween"),
                    ft.Divider(height=10, color=Colors.BORDER),
                    ui_inet, ft.Row([ui_wifi, ui_disc], spacing=10),
                    ft.Divider(height=10, color="transparent"),
                    ft.Row([ui_iptv, ui_stb], spacing=10),
                    ft.Row([ui_mtv, ui_mstb], spacing=10),
                    ft.Divider(height=10, color="transparent"),
                    ft.Row([ui_safe, ft.Container(content=chk_wings, padding=ft.Padding(0,15,0,0))], spacing=10),
                    ft.Row([ui_pre_inet, ui_pre_iptv, ui_pre_mtv], spacing=5, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Divider(height=15),
                    ft.Container(content=ft.Column([ft.Text("월 예상 금액", size=13, color=Colors.TEXT_SUB, weight="bold"), ft.Row([txt_result, ft.Container(width=10), container_recommend], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER)], spacing=5, horizontal_alignment=ft.CrossAxisAlignment.CENTER), bgcolor="#E3F2FD", padding=15, border_radius=8)
                ], spacing=8), padding=15, bgcolor="#FAFAFA", border_radius=12, border=ft.Border.all(1, "#EEEEEE")
            )
        ]

        step_copy_container = ft.Container(alignment=ft.Alignment(1.0, 0))

        bs_sub_column.controls = [
            ft.Row([ft.Row([ft.Text(f"청약서 정보 - {customer_name}", size=18, weight="bold", color=Colors.PRIMARY), ft.Container(width=10)]), ft.Row([step_copy_container, btn_close])], alignment="spaceBetween"),
            ft.Divider(color=Colors.BORDER),
            ft.Container(content=ft.Row([ft.Container(content=left_info_col, expand=6), ft.VerticalDivider(width=1, color="#EEEEEE"), ft.Container(content=right_calc_col, expand=4)], expand=True, alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START), expand=True)
        ]
        sub_layer.visible=True; sub_layer.opacity=1; sub_layer.update()

        # ----------------------------------------------------------------------
        # [데이터 로딩 비동기 함수]
        # ----------------------------------------------------------------------
        def _bg_load():
            time.sleep(0.1)
            try:
                info = engine.fetch_detail_info(internal_id, verbose=True)
                if not info: left_info_col.controls=[ft.Text("Load Error", color="red")]; left_info_col.update(); return

                uname = info.get('uname', ''); jumin = info.get('jumin', ''); mobile = info.get('mobile', '')
                addr1 = info.get('address', ''); full_addr = f"{addr1} {info.get('address2', '')}".strip()
                cardname = info.get('cardname', ''); cardnum = info.get('cardnum', '')
                cardexpire = info.get('cardexpire', '')
                apply_number = info.get('applynumber', '')
                
                custom_price_str = info.get('customprice', '0')
                try: c_price = int(str(custom_price_str).replace(',', '').strip())
                except: c_price = 0
                fetched_calc_data['original_price'] = c_price
                
                products_list = info.get('products_list', [])
                gift_txt = info.get('servicesrdata_txt', ''); content_txt = info.get('content', '')
                search_addr = addr1.strip(); apt_name = ""
                if '(' in search_addr and ')' in search_addr:
                    try: start = search_addr.rfind('(') + 1; end = search_addr.rfind(')'); apt_name = search_addr[start:end].strip()
                    except: pass

                # [파싱]
                try:
                    init_calc = {}
                    tv_items = []
                    prod_texts = []
                    for p in products_list:
                        p_name = p.get('name', '').strip()
                        p_opts = " ".join(p.get('options', [])).strip()
                        p_full = f"{p_name} {p_opts}"
                        prod_texts.append(p_full)
                        if "BTV" in p_full.upper(): tv_items.append(p_full.upper())

                    raw_prod_full = " ".join(prod_texts)
                    val_oper1 = info.get('oper1', ''); val_oper2 = info.get('oper2', '')
                    val_oper4 = info.get('oper4', ''); val_oper5 = info.get('oper5', '')
                    full_text = f"{raw_prod_full} {content_txt} {val_oper1} {val_oper2} {val_oper4} {val_oper5}"

                    if "기가라이트" in raw_prod_full or "500M" in raw_prod_full: init_calc['internet'] = "기가라이트(500M)"
                    elif "1기가" in raw_prod_full or "1G" in raw_prod_full: init_calc['internet'] = "1기가(1G)"
                    elif "광랜" in raw_prod_full or "100M" in raw_prod_full: init_calc['internet'] = "광랜(100M)"
                    
                    if "ALL플러스" in raw_prod_full or "ALL+" in raw_prod_full: init_calc['iptv'] = "BTV ALL플러스"
                    elif "ALL" in raw_prod_full: init_calc['iptv'] = "BTV ALL"
                    elif "이코노미" in raw_prod_full: init_calc['iptv'] = "BTV 이코노미"
                    elif "스탠다드" in raw_prod_full: 
                        if "플러스" in raw_prod_full: init_calc['iptv'] = "BTV스탠다드플러스"
                        else: init_calc['iptv'] = "BTV스탠다드"

                    if "기가와이파이" in full_text: init_calc['wifi'] = "기가와이파이"
                    elif "광랜와이파이" in full_text: init_calc['wifi'] = "광랜와이파이"
                    
                    if 'internet' in init_calc and 'iptv' in init_calc: init_calc['discount'] = "요즘우리집결합"
                    if "요즘가족" in full_text:
                        if "본인" in full_text or "(본)" in full_text: init_calc['discount'] = "요즘가족결합(본인)"
                        else: init_calc['discount'] = "요즘가족결합(가족)"
                    elif "온가족" in full_text: init_calc['discount'] = "온가족할인"
                    elif "패밀리" in full_text: init_calc['discount'] = "패밀리결합"

                    stb_src = val_oper1 + " " + raw_prod_full
                    if "AI4" in stb_src or "NUGU" in stb_src: init_calc['stb'] = "AI4"
                    elif "AI2" in stb_src: init_calc['stb'] = "AI2"
                    elif "SMART" in stb_src.upper(): init_calc['stb'] = "Smart"
                    elif "APPLE" in stb_src.upper(): init_calc['stb'] = "APPLE TV"

                    if "더안심" in full_text: init_calc['addon'] = "더안심"
                    elif "안심" in full_text: init_calc['addon'] = "안심"
                    if "WINGS" in full_text.upper() or "윙스" in full_text: init_calc['wings'] = True

                    if len(tv_items) >= 2:
                        mtv_str = tv_items[1]
                        if "ALL플러스" in mtv_str or "ALL+" in mtv_str: init_calc['multitv'] = "BTV ALL플러스"
                        elif "ALL" in mtv_str: init_calc['multitv'] = "BTV ALL"
                        elif "이코노미" in mtv_str: init_calc['multitv'] = "BTV 이코노미"
                        elif "스탠다드" in mtv_str: 
                            if "플러스" in mtv_str: init_calc['multitv'] = "BTV스탠다드플러스"
                            else: init_calc['multitv'] = "BTV스탠다드"
                        if "AI4" in mtv_str or "NUGU" in mtv_str: init_calc['multistb'] = "AI4"
                        elif "AI2" in mtv_str: init_calc['multistb'] = "AI2"
                        elif "SMART" in mtv_str: init_calc['multistb'] = "Smart"
                        elif "APPLE" in mtv_str: init_calc['multistb'] = "APPLE TV"
                    fetched_calc_data['data'] = init_calc
                except: pass

                # ------------------------------------------------------
                # [좌측 상세정보 UI]
                # ------------------------------------------------------
                info_controls = []

                def run_quick_action(e, memo_text, status_text, is_debt=False, is_reply=False):
                    if e: e.control.disabled = True; e.control.content = ft.Text("...", size=11, color="white"); e.control.update()
                    success = False
                    if is_debt: success = engine.submit_debt_default(internal_id, current_user_id)
                    else:
                        m_ok = True
                        if memo_text and apply_number: m_ok = engine.submit_new_memo(apply_number, memo_text, current_user_id, is_reply_request=is_reply)
                        if m_ok and engine.update_product_status(internal_id, status_text): success = True
                    if success:
                        page.snack_bar = ft.SnackBar(ft.Text(f"✅ 완료: {status_text}"), bgcolor=Colors.SUCCESS)
                        page.pubsub.send_all({'topic': 'force_refresh', 'payload': None}); close_sub_sheet()
                    else:
                        page.snack_bar = ft.SnackBar(ft.Text("❌ 실패"), bgcolor=Colors.ERROR)
                        if e: e.control.disabled = False; e.control.content = ft.Text("처리", size=11, color="white"); e.control.update()
                    page.snack_bar.open = True; page.update()

                def open_unverified_popup(e):
                    def close_p(e): dlg_uv.open = False; page.update()
                    def sel(txt): dlg_uv.open=False; page.update(); run_quick_action(e, f"{txt}대리점으로 인증해주세요 미인증상태입니다", "확인요망", is_reply=True)
                    tf_etc = ft.TextField(label="기타", height=40, text_size=12, expand=True)
                    dlg_uv = ft.AlertDialog(title=ft.Text("미인증 대리점"), content=ft.Column([
                        ft.OutlinedButton("골든케어(대구) E04243", on_click=lambda e: sel("골든케어(대구) E04243"), width=250),
                        ft.OutlinedButton("골든케어 E03448", on_click=lambda e: sel("골든케어 E03448"), width=250),
                        ft.OutlinedButton("레드텔레콤 E03756", on_click=lambda e: sel("레드텔레콤 E03756"), width=250),
                        ft.Row([tf_etc, ft.IconButton(ft.Icons.SEND, on_click=lambda e: sel(tf_etc.value) if tf_etc.value else None)])
                    ], tight=True), actions=[ft.TextButton("취소", on_click=close_p)])
                    page.overlay.append(dlg_uv); dlg_uv.open=True; page.update()

                btns = [
                    ft.FilledButton("접수중", style=ft.ButtonStyle(bgcolor="#0288D1", padding=10), height=35, on_click=lambda e: run_quick_action(e, "", "접수중")),
                    ft.FilledButton("채무불이행", style=ft.ButtonStyle(bgcolor="#B71C1C", padding=10), height=35, on_click=lambda e: run_quick_action(e, "", "개통불가", is_debt=True)),
                    ft.FilledButton("부재", style=ft.ButtonStyle(bgcolor="#EF6C00", padding=10), height=35, on_click=lambda e: run_quick_action(e, "가입자 통화 실패", "확인요망", is_reply=True)),
                    ft.FilledButton("계좌오류", style=ft.ButtonStyle(bgcolor="#F9A825", padding=10), height=35, on_click=lambda e: run_quick_action(e, "계좌번호/생년월일 불일치", "확인요망", is_reply=True)),
                    ft.FilledButton("영업불량", style=ft.ButtonStyle(bgcolor="#424242", padding=10), height=35, on_click=lambda e: run_quick_action(e, "1년뒤 이동안내/접수불가", "개통불가")),
                    ft.FilledButton("공사진행", style=ft.ButtonStyle(bgcolor="#795548", padding=10), height=35, on_click=lambda e: run_quick_action(e, "공사 후 진행됩니다", "공사확인중")),
                    ft.FilledButton("미인증", style=ft.ButtonStyle(bgcolor="#607D8B", padding=10), height=35, on_click=open_unverified_popup)
                ]
                info_controls.append(ft.Text("회신 퀵메뉴", weight="bold", color=Colors.PRIMARY)); info_controls.append(ft.Row(btns, scroll=ft.ScrollMode.AUTO, spacing=8)); info_controls.append(ft.Divider())

                s_List = ["000", "레드기업", "레드텔레콤", "골든대구", "골든대전", "대승아이앤씨", "에이케이넷", "새로", "ZD", "두웰", "해빛", "월드", "준유통", "그린파머", "아진정보", "라이크유", "디코비즈", "에스디앤", "에스디앤서울", "K스타", "줌네트워크", "SN"]
                cur_ag = info.get('companycode', '000')
                dd_ag = ft.Dropdown(options=[ft.dropdown.Option(k) for k in s_List], value=cur_ag, width=250, height=40, text_size=12, content_padding=10)
                def save_ag(e):
                    if engine.update_agency(internal_id, dd_ag.value): page.snack_bar=ft.SnackBar(ft.Text("대리점 변경 완료"), bgcolor=Colors.SUCCESS)
                    else: page.snack_bar=ft.SnackBar(ft.Text("실패"), bgcolor=Colors.ERROR)
                    page.snack_bar.open=True; page.update()
                info_controls.append(ft.Text("대리점 관리", weight="bold", color=Colors.PRIMARY)); info_controls.append(ft.Row([dd_ag, ft.FilledButton("변경", height=40, on_click=save_ag)])); info_controls.append(ft.Divider())

                copy_st = [0]
                def on_step(e):
                    copy_st[0] = (copy_st[0] % 6) + 1; idx = copy_st[0]
                    final_name = uname.replace("이사/", "").split('/')[0] if "이사/" in uname else uname.split('/')[0]
                    final_etc = txt_content_display.value if 'txt_content_display' in locals() else content_txt
                    d_map = {1: ("고객명", final_name.strip()), 2: ("식별번호", jumin), 3: ("연락처", mobile), 4: ("주소", addr1), 5: ("계좌", cardnum), 6: ("기타", final_etc)}
                    lbl, val = d_map[idx]
                    pyperclip.copy(str(val).strip()); page.snack_bar=ft.SnackBar(ft.Text(f"✅ {lbl} 복사 ({idx}/6)"), bgcolor=Colors.SUCCESS, duration=1000); page.snack_bar.open=True
                    btn_step.content = ft.Row([ft.Icon(ft.Icons.COPY if idx<6 else ft.Icons.REPLAY, size=14, color="white"), ft.Text(f"다음: {d_map[(idx%6)+1][0] if idx<6 else '다시시작'} ({idx if idx<6 else 'End'}/6)", size=12, color="white")])
                    btn_step.style.bgcolor = "black" if idx==6 else Colors.INFO
                    btn_step.update(); page.update()
                
                app_state["active_copy_handler"] = on_step
                btn_step = ft.FilledButton(content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=14), ft.Text("순차 복사 시작 [F2]", size=12)]), style=ft.ButtonStyle(bgcolor="black", padding=12), height=35, on_click=on_step)
                step_copy_container.content = btn_step; step_copy_container.update()

                tf_nm = ft.TextField(value=uname, width=300, height=35, text_size=13, content_padding=10, bgcolor="#F5F5F5", border_radius=6, border_width=0)
                def on_add_suffix(e):
                    if not tf_nm.value.endswith("/윤"): tf_nm.value += "/윤"; tf_nm.update()
                btn_add_suffix = ft.FilledButton("접수자등록", height=35, style=ft.ButtonStyle(bgcolor=Colors.TEXT_SUB, padding=5), on_click=on_add_suffix)
                def save_nm(e): 
                    engine.update_customer_name(internal_id, tf_nm.value)
                    page.snack_bar=ft.SnackBar(ft.Text("수정완료"), bgcolor=Colors.SUCCESS); page.snack_bar.open=True; page.update()
                info_controls.append(ft.Text("기본 정보", weight="bold", color=Colors.PRIMARY)); info_controls.append(ft.Text("고객(상호명)", size=11, color="grey"))
                info_controls.append(ft.Row([tf_nm, btn_add_suffix, ft.FilledButton("수정", height=35, on_click=save_nm)], spacing=5))
                
                def row_ui(l, v): return ft.Column([ft.Text(l, size=11, color="grey"), ft.Container(ft.Text(v or "-", selectable=True), bgcolor="#F5F5F5", padding=8, border_radius=6, width=180)])
                info_controls.append(row_ui("식별번호", jumin)); info_controls.append(row_ui("휴대전화", mobile)); info_controls.append(ft.Container(height=10))
                info_controls.append(ft.Text("설치 주소", weight="bold", color=Colors.PRIMARY))
                info_controls.append(ft.Container(ft.Text(full_addr, size=14, selectable=True), bgcolor="#F5F5F5", padding=10, width=550, border_radius=6))
                
                def map_click(u): webbrowser.open(u.format(addr=quote(addr1)), new=2)
                def on_click_land(e):
                    if apt_name: webbrowser.open(f"https://new.land.naver.com/search?sk={quote(apt_name)}", new=2)
                    else: map_click("https://new.land.naver.com/search?sk={addr}")
                def on_set_investigation(e):
                    if engine.set_products_status_investigation(internal_id): page.snack_bar = ft.SnackBar(ft.Text("실사중 변경"), bgcolor=Colors.SUCCESS); e.control.text="완료"; e.control.disabled=True
                    else: page.snack_bar = ft.SnackBar(ft.Text("실패"), bgcolor=Colors.ERROR)
                    page.snack_bar.open=True; page.update(); e.control.update()

                btn_copy_req = ft.FilledButton(content=ft.Text("실사 요청", size=11), style=ft.ButtonStyle(bgcolor=Colors.ERROR, padding=10), height=35, on_click=lambda e: pyperclip.copy(f"[실사 요청]\n고객명: {uname}\n연락처: {mobile}\n주소: {full_addr}\n위 주소지 실사요청..."))
                btn_ing_req = ft.FilledButton(content=ft.Text("실사중", size=11), style=ft.ButtonStyle(bgcolor=Colors.WARNING, padding=10), height=35, on_click=on_set_investigation)
                btn_naver = ft.FilledButton(content=ft.Row([ft.Image(src="assets/navermap.jpeg", width=14, height=14, fit="contain"), ft.Text("네이버지도", size=11)], spacing=5), style=ft.ButtonStyle(bgcolor="#03C75A", padding=10), height=35, on_click=lambda e: map_click("https://map.naver.com/v5/search/{addr}"))
                btn_kakao = ft.FilledButton(content=ft.Row([ft.Image(src="assets/kakaomap.png", width=14, height=14, fit="contain"), ft.Text("카카오지도", size=11, color="black")], spacing=5), style=ft.ButtonStyle(bgcolor="#FEE500", padding=10), height=35, on_click=lambda e: map_click("https://map.kakao.com/link/search/{addr}"))
                btn_land = ft.FilledButton(content=ft.Row([ft.Icon(ft.Icons.DOMAIN, size=14), ft.Text("동,호수확인", size=11)], spacing=5), style=ft.ButtonStyle(bgcolor="#1976D2", padding=10), height=35, on_click=on_click_land)
                tf_date_display = ft.TextField(label="입주일(사용승인)", value="검색중...", text_size=12, width=140, height=35, content_padding=5, read_only=True, bgcolor="#E3F2FD", border_radius=6, border_width=0)
                info_controls.append(ft.Row([btn_copy_req, btn_ing_req, btn_naver, btn_kakao, btn_land, tf_date_display], scroll=ft.ScrollMode.AUTO, spacing=5))
                info_controls.append(ft.Divider())

                def run_crawling():
                    found_date = "확인불가"
                    if apt_name:
                        try:
                            r = requests.get(f"https://search.naver.com/search.naver?query={quote(apt_name)}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
                            soup_n = BeautifulSoup(r.text, 'html.parser')
                            match = re.search(r'(19|20)\d{2}\.(0[1-9]|1[0-2])\.', soup_n.get_text()); 
                            if match: found_date = match.group()
                        except: pass
                    else: found_date = "아파트명 없음"
                    tf_date_display.value = found_date; page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
                threading.Thread(target=run_crawling, daemon=True).start()

                if products_list:
                    info_controls.append(ft.Text("상품 정보", weight="bold"))
                    for p in products_list: info_controls.append(ft.Container(content=ft.Column([ft.Text(f"📦 {p['name']}", weight="bold"), ft.Text(f"옵션: {', '.join(p['options'])}", size=12)]), bgcolor="#F0F4C3", padding=10, border_radius=6))
                
                try: formatted_price = f"{int(c_price):,}" 
                except: formatted_price = custom_price_str
                info_controls.append(ft.Container(content=ft.Row([ft.Text("월 요금:", size=13, weight="bold", color=Colors.PRIMARY), ft.Row([ft.Text(f"{formatted_price} 원", size=14, weight="bold", color="black")])], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), bgcolor="#E8F5E9", padding=10, border_radius=6, margin=ft.margin.only(top=5), width=350))
                info_controls.append(ft.Divider())

                tf_gift = ft.TextField(label="추가 사은품 / 비고", value=gift_txt, multiline=False, height=40, text_size=13, width=300, bgcolor="#F5F5F5", border_radius=6)
                def save_gift_btn(e):
                    if engine.update_gift_info(internal_id, tf_gift.value): page.snack_bar=ft.SnackBar(ft.Text("저장 완료"), bgcolor=Colors.SUCCESS)
                    else: page.snack_bar=ft.SnackBar(ft.Text("실패"), bgcolor=Colors.ERROR)
                    page.snack_bar.open=True; page.update()
                
                tf_up = ft.TextField(label="업셀항목 추가", height=35, text_size=13, expand=True)

                # ... (선납권 개월 선택 로직은 기존 유지) ...
                sel_month = [9]
                txt_month_display = ft.Text(f"{sel_month[0]}개월", size=13)
                def on_change_month(e):
                    sel_month[0] = int(e.control.data)
                    txt_month_display.value = f"{sel_month[0]}개월"
                    txt_month_display.update()
                month_items = [ft.PopupMenuItem(content=ft.Text(f"{m}개월"), data=m, on_click=on_change_month) for m in range(1, 37)]
                ui_month_sel = ft.PopupMenuButton(content=ft.Container(content=ft.Row([txt_month_display, ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=16)], spacing=2), border=ft.Border.all(1, "grey"), border_radius=4, padding=5, bgcolor="white"), items=month_items)

                # ... (선납권 적용 로직 기존 유지) ...
                def apply_prepayment_rec(e):
                    total_rec = latest_rec_amounts.get('total', 0)
                    if total_rec <= 0:
                        page.snack_bar = ft.SnackBar(ft.Text("💡 추천할 선납권 금액이 없습니다."), bgcolor=Colors.ERROR); page.snack_bar.open=True; page.update(); return
                    
                    def ex_vat(val): return int(round(val / 1.1))
                    final_inet = ex_vat(latest_rec_amounts['inet'])
                    final_iptv = ex_vat(latest_rec_amounts['iptv'])
                    final_mtv = ex_vat(latest_rec_amounts['mtv'])
                    final_total = ex_vat(total_rec)
                    
                    m = sel_month[0]
                    add_txt = f"{final_total}*{m}"
                    tf_gift.value = f"{tf_gift.value} {add_txt}" if tf_gift.value else add_txt
                    tf_gift.update()
                    
                    parts = []
                    if tf_up.value: parts.append(tf_up.value)
                    if final_inet > 0: parts.append(f"인{final_inet}*{m}개월")
                    if final_iptv > 0: parts.append(f"티{final_iptv}*{m}개월")
                    if final_mtv > 0: parts.append(f"다{final_mtv}*{m}개월")
                    
                    detail_txt = "\n".join(parts)
                    if detail_txt:
                        current_val = txt_content_display.value if txt_content_display.value else ""
                        prefix = "\n" if current_val.strip() else ""
                        txt_content_display.value += f"{prefix}{detail_txt}"
                        txt_content_display.update()
                        page.snack_bar = ft.SnackBar(ft.Text("✅ 선납권 내역 입력 완료"), bgcolor=Colors.SUCCESS); page.snack_bar.open=True; page.update()

                btn_rec_pre = ft.FilledButton("선납권추천", height=40, style=ft.ButtonStyle(bgcolor="orange", padding=10), on_click=apply_prepayment_rec)

                info_controls.append(ft.Text("사은품 및 비고", weight="bold", color=Colors.PRIMARY))
                info_controls.append(ft.Row([tf_gift, ui_month_sel, btn_rec_pre, ft.FilledButton("저장", height=40, on_click=save_gift_btn)], spacing=5))
                info_controls.append(ft.Divider())

                info_controls.append(ft.Text("결제/기타", weight="bold"))
                info_controls.append(ft.Row([row_ui("은행", cardname), row_ui("계좌", cardnum), row_ui("유효기간", cardexpire)])); info_controls.append(ft.Container(height=10))
                info_controls.append(ft.Text("기타 사항", weight="bold", color=Colors.PRIMARY)) 
                txt_content_display = ft.Text(content_txt, size=13, selectable=True)
                info_controls.append(ft.Container(content=txt_content_display, bgcolor="#FFFDE7", padding=10, border_radius=6, width=550))

                def add_up(txt): tf_up.value = f"{tf_up.value} + {txt}" if tf_up.value else txt; tf_up.update()
                
                # [수정된 부분] 서버 전송 기능 구현
                # [수정] 전송 버튼 핸들러
                def send_upsell_data(e):
                    if not tf_up.value: return
                    
                    # 1. 서버 전송: [업셀] 머리말 포함 (비밀댓글)
                    engine.submit_new_memo(apply_number, f"[업셀] {tf_up.value}", current_user_id, True)
                    
                    # 2. 화면(기타사항) 표시: [업셀] 머리말 제거하고 내용만 표시
                    current_val = txt_content_display.value if txt_content_display.value else ""
                    prefix = "\n\n" if current_val.strip() else ""
                    
                    # [변경됨] 화면에는 텍스트 값만 추가
                    txt_content_display.value += f"{prefix}{tf_up.value}"
                    txt_content_display.update()
                    
                    # 3. 초기화 및 알림
                    tf_up.value = ""
                    tf_up.update()
                    page.snack_bar = ft.SnackBar(ft.Text("✅ 업셀 정보 전송 완료"), bgcolor=Colors.SUCCESS)
                    page.snack_bar.open=True; page.update()
                
                def on_upsell_click(e, txt):
                    add_up(txt)
                    if txt == "안심": update_sim_link('addon_safe', '안심', ui_safe)
                    elif txt == "기가": update_sim_link('internet', '1기가(1G)', ui_inet)
                    elif txt == "기가라이트": update_sim_link('internet', '기가라이트(500M)', ui_inet)
                    elif txt == "올": update_sim_link('iptv', 'BTV ALL', ui_iptv)
                    elif txt == "올플": update_sim_link('iptv', 'BTV ALL플러스', ui_iptv)
                    elif txt == "다셋올": update_sim_link('multitv', 'BTV ALL', ui_mtv)
                    elif txt == "다셋올플": update_sim_link('multitv', 'BTV ALL플러스', ui_mtv)

                upsell_items = ["안심", "기가", "기가라이트", "올", "올플", "다셋올", "다셋올플", "애플 TV", "OSS", "소상공인"]
                q_btns = [ft.OutlinedButton(t, height=30, style=ft.ButtonStyle(padding=10), on_click=lambda e,v=t: on_upsell_click(e,v)) for t in upsell_items]
                
                def on_multi_click(txt):
                    add_up(txt)
                    if "스탠다드" in txt: update_sim_link('multitv', 'BTV스탠다드', ui_mtv)
                    elif "이코노미" in txt: update_sim_link('multitv', 'BTV 이코노미', ui_mtv)

                multi_stb = ft.PopupMenuButton(content=ft.Container(content=ft.Row([ft.Text("다셋탑(기타)", size=12), ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=16)], spacing=2), padding=10, border=ft.Border.all(1, Colors.PRIMARY), border_radius=6, height=36), items=[ft.PopupMenuItem(content=ft.Text("다셋탑(스탠다드)"), on_click=lambda e: on_multi_click("다셋탑(스탠다드)")), ft.PopupMenuItem(content=ft.Text("다셋탑(이코노미)"), on_click=lambda e: on_multi_click("다셋탑(이코노미)"))])
                q_btns.append(multi_stb)
                
                # [수정] 버튼 이름 "전송"으로 변경 및 함수 연결
                info_controls.append(ft.Row([tf_up, ft.FilledButton("전송", height=35, on_click=send_upsell_data)]))
                info_controls.append(ft.Row(q_btns, wrap=True))

                left_info_col.controls = info_controls
                left_info_col.update()
                
                # 자동 시뮬레이터 세팅
                ui_map = {'internet': ui_inet, 'wifi': ui_wifi, 'discount': ui_disc, 'iptv': ui_iptv, 'stb': ui_stb, 'addon': ui_safe, 'multitv': ui_mtv, 'multistb': ui_mstb}
                for k, v in init_calc.items():
                    target = k if k != 'addon' else 'addon_safe'
                    if target in ui_map: update_sim_link(target, v, ui_map[target])
                if 'wings' in init_calc: chk_wings.value = True; chk_wings.update()
                
                try: recalc()
                except: pass
                
                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})

            except Exception as e:
                import traceback; traceback.print_exc()
                left_info_col.controls = [ft.Text(f"오류 발생: {e}", color="red", size=20)]; left_info_col.update()

        threading.Thread(target=_bg_load, daemon=True).start()
    
    # --------------------------------------------------------------------------
    # [누락된 함수 복구] 회신/메모 팝업 (퀵메뉴 포함)
    # --------------------------------------------------------------------------
    def open_bottom_sheet_memo(internal_id, customer_name):
        # 1. UI 크기 설정 (기존 바텀시트 사용 - 높이 85%)
        bs_content.height = (page.height or 800) * 0.85
        bs_content.width = None # 너비 제한 해제 (기본값)
        bs_content.update()
        
        # 2. UI 컴포넌트 초기화
        tf_memo_input = ft.TextField(hint_text="메모 입력...", text_size=13, height=40, content_padding=10, expand=True, bgcolor="#F5F5F5", border_radius=8, border_width=0)
        chk_sec = ft.Checkbox(label="비밀", value=False, active_color=Colors.PRIMARY)
        chk_rep = ft.Checkbox(label="회신", value=False, active_color=Colors.PRIMARY)
        memo_list_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        # ------------------------------------------------------------------
        # 퀵메뉴 로직 (청약 팝업과 동일 로직 사용)
        # ------------------------------------------------------------------
        def run_quick_action(e_control, memo_text, status_text, is_reply=False):
            if e_control:
                e_control.disabled = True
                original_content = e_control.content
                e_control.content = ft.Text("...", size=11, color="white")
                e_control.update()

            success = False
            
            # 1. 메모 전송
            target_apply_num = btn_reg.data
            if target_apply_num and memo_text:
                if engine.submit_new_memo(target_apply_num, memo_text, tf_id.value, is_reply_request=is_reply):
                    success = True
            elif not memo_text:
                success = True # 메모 없으면 성공 간주

            # 2. 상태 변경
            if success:
                if engine.update_product_status(internal_id, status_text):
                    page.snack_bar = ft.SnackBar(ft.Text(f"✅ 처리 완료 ({status_text})"), bgcolor=Colors.SUCCESS)
                    page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
                    bs_bottom_sheet.open = False
                else:
                    page.snack_bar = ft.SnackBar(ft.Text("❌ 상태 변경 실패"), bgcolor=Colors.ERROR)
            else:
                page.snack_bar = ft.SnackBar(ft.Text("❌ 메모 전송 실패"), bgcolor=Colors.ERROR)

            # 버튼 복구
            if e_control:
                e_control.disabled = False
                e_control.content = original_content
                e_control.update()
            
            page.snack_bar.open = True
            page.update()

        # 퀵메뉴 버튼들
        btn_quick_receipt = ft.FilledButton("접수중", style=ft.ButtonStyle(bgcolor="#0288D1", padding=5), height=30, on_click=lambda e: run_quick_action(e.control, "", "접수중"))
        btn_quick_check = ft.FilledButton("확인요망", style=ft.ButtonStyle(bgcolor="#F9A825", padding=5), height=30, on_click=lambda e: run_quick_action(e.control, "", "확인요망"))
        btn_construction = ft.FilledButton("공사진행", style=ft.ButtonStyle(bgcolor="#795548", padding=5), height=30, on_click=lambda e: run_quick_action(e.control, "공사 후 진행됩니다", "공사확인중"))
        
        # 미인증 팝업
        def open_unverified_popup(e):
            def close_p(e): dlg_uv.open=False; page.update(); page.overlay.remove(dlg_uv)
            def sel(txt): close_p(None); run_quick_action(btn_unverified, f"{txt}대리점으로 인증해주세요 미인증상태입니다", "확인요망", is_reply=True)
            tf_etc = ft.TextField(label="기타", height=40, text_size=12, expand=True)
            dlg_uv = ft.AlertDialog(title=ft.Text("미인증 대리점"), content=ft.Column([
                ft.OutlinedButton("골든케어(대구) E04243", on_click=lambda e: sel("골든케어(대구) E04243"), width=250),
                ft.OutlinedButton("골든케어 E03448", on_click=lambda e: sel("골든케어 E03448"), width=250),
                ft.OutlinedButton("레드텔레콤 E03756", on_click=lambda e: sel("레드텔레콤 E03756"), width=250),
                ft.Row([tf_etc, ft.IconButton(ft.Icons.SEND, on_click=lambda e: sel(tf_etc.value) if tf_etc.value else None)])
            ], tight=True), actions=[ft.TextButton("취소", on_click=close_p)])
            page.overlay.append(dlg_uv); dlg_uv.open=True; page.update()

        btn_unverified = ft.FilledButton("미인증", style=ft.ButtonStyle(bgcolor="#607D8B", padding=5), height=30, on_click=open_unverified_popup)

        quick_row = ft.Row([
            ft.Text("퀵메뉴:", size=12, weight="bold", color=Colors.PRIMARY),
            btn_quick_receipt, btn_quick_check, btn_construction, btn_unverified
        ], scroll=ft.ScrollMode.AUTO)

        # ------------------------------------------------------------------
        # 메모 등록 로직
        # ------------------------------------------------------------------
        def submit_action(e):
            if not tf_memo_input.value.strip(): return
            e.control.disabled = True; e.control.text = "..."; e.control.update()
            target_apply_num = btn_reg.data 
            if target_apply_num and engine.submit_new_memo(target_apply_num, tf_memo_input.value, tf_id.value, chk_sec.value, chk_rep.value):
                page.snack_bar = ft.SnackBar(ft.Text("메모 등록 완료"), bgcolor=Colors.SUCCESS); page.snack_bar.open=True
                bs_bottom_sheet.open = False; page.update()
            else:
                e.control.disabled = False; e.control.text = "등록"; e.control.update()
                page.snack_bar = ft.SnackBar(ft.Text("실패"), bgcolor=Colors.ERROR); page.snack_bar.open=True; page.update()

        btn_reg = ft.FilledButton("등록", on_click=submit_action, bgcolor=Colors.PRIMARY, color="white", data=None, height=40)
        
        # 레이아웃 조립
        bs_main_column.controls = [
            ft.Row([ft.Text(f"회신 및 메모 - {customer_name}", size=18, weight="bold"), ft.Container(expand=True)]),
            ft.Container(height=5),
            quick_row,
            ft.Divider(color=Colors.BORDER),
            ft.Container(content=memo_list_container, expand=True),
            ft.Divider(color=Colors.BORDER),
            ft.Row([tf_memo_input, btn_reg]),
            ft.Row([chk_sec, chk_rep])
        ]
        bs_bottom_sheet.open = True; bs_bottom_sheet.update()

        # 데이터 로딩
        def _bg_load():
            time.sleep(0.3)
            try:
                apply_num, memos = engine.fetch_memo_data(internal_id)
                btn_reg.data = apply_num
                list_controls = []
                if not memos: list_controls.append(ft.Text("등록된 메모가 없습니다.", size=12, color="grey"))
                else: 
                    for m in memos: 
                        list_controls.append(ft.Container(content=ft.Column([ft.Text(m['content'], size=13), ft.Row([ft.Text(m['writer'], size=11, weight="bold", color=Colors.TEXT_SUB), ft.Text(m['date'], size=11, color=Colors.TEXT_SUB)], alignment="spaceBetween")]), bgcolor=Colors.BG_MAIN, padding=12, border_radius=8, margin=ft.Margin(0,0,0,8)))
                memo_list_container.controls = list_controls
                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
            except Exception as e:
                memo_list_container.controls = [ft.Text(f"오류: {e}", color="red")]
                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
        threading.Thread(target=_bg_load, daemon=True).start()

    # --------------------------------------------------------------------------
    # [누락된 함수 복구] 반송 처리 팝업
    # --------------------------------------------------------------------------
    def open_bottom_sheet_return(internal_id, customer_name):
        # 1. UI 초기화 (기존 바텀시트 사용)
        bs_content.height = (page.height or 800) * 0.85
        bs_content.width = None # 너비 제한 해제
        bs_content.update()
        
        product_list_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        
        # 헤더 설정
        bs_main_column.controls = [
            ft.Text(f"반송 처리 - {customer_name}", size=18, weight="bold", color=Colors.ERROR),
            ft.Text("상품 목록 로딩중...", size=12, color="grey"),
            ft.Divider(color=Colors.BORDER),
            ft.Container(content=product_list_container, expand=True)
        ]
        bs_bottom_sheet.open = True
        bs_bottom_sheet.update()

        # 2. 데이터 로딩 (비동기)
        def _bg_load():
            time.sleep(0.3) 
            try:
                products, action_url = engine.fetch_products_for_completion(internal_id)
                
                # 로딩 문구 변경
                if len(bs_main_column.controls) > 1: 
                    bs_main_column.controls[1] = ft.Text("개별 상품 반송 가능", size=12, color=Colors.TEXT_SUB)
                
                rows_controls = []
                
                if not products:
                    rows_controls.append(ft.Text("상품 없음", color="grey"))
                else:
                    inputs_refs = []
                    # 입력 필드 생성
                    for p in products: 
                        inputs_refs.append(
                            ft.TextField(
                                label=f"{p['goods_name']}", 
                                value=p['current_val'], 
                                height=45, 
                                text_size=13, 
                                content_padding=10, 
                                expand=True, 
                                bgcolor="#F5F5F5", 
                                border_radius=8, 
                                border_width=0
                            )
                        )
                    
                    # 각 줄에 반송 버튼 추가
                    for idx, tf_ref in enumerate(inputs_refs):
                        # 클로저 (버튼 클릭 핸들러 생성기)
                        def make_click_handler(c_idx, c_refs):
                            def on_click_return(e):
                                current_vals = [r.value for r in c_refs]
                                
                                # 로딩 UI
                                e.control.disabled = True
                                e.control.content = ft.Text("...", size=12)
                                e.control.update()
                                
                                # 반송 처리 요청 (32번 상태)
                                if engine.submit_return_status(internal_id, current_vals, target_index=c_idx):
                                    page.snack_bar = ft.SnackBar(ft.Text(f"반송 처리 완료"), bgcolor=Colors.SUCCESS)
                                    e.control.content = ft.Text("완료", size=12)
                                    e.control.bgcolor = "grey"
                                else:
                                    page.snack_bar = ft.SnackBar(ft.Text("실패"), bgcolor=Colors.ERROR)
                                    e.control.disabled = False
                                    e.control.content = ft.Text("반송", size=13, weight="bold")
                                
                                page.snack_bar.open = True
                                page.update()
                                e.control.update()
                                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
                            return on_click_return

                        btn = ft.FilledButton(
                            content=ft.Text("반송", size=13, weight="bold"), 
                            bgcolor=Colors.ERROR, 
                            color="white", 
                            width=80, 
                            height=45, 
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)), 
                            on_click=make_click_handler(idx, inputs_refs)
                        )
                        rows_controls.append(ft.Row([tf_ref, btn], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER))
                
                product_list_container.controls = rows_controls
                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
            
            except Exception as e:
                product_list_container.controls = [ft.Text(f"오류: {e}", color="red")]
                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
        
        threading.Thread(target=_bg_load, daemon=True).start()

    def render_todos():
        todos = fs_manager.get_todos()
        todo_list_view.controls.clear()
        
        todos.sort(key=lambda x: x.get('target_date', '9999-12-31'))

        for task in todos:
            if task.get('owner_id') != tf_id.value and task.get('owner_id') != 'ALL':
                continue

            is_done = task.get('is_done', False)
            t_date = task.get('target_date', '')
            t_time = task.get('target_time', '')
            doc_id = task.get('doc_id')
            title = task.get('title', '')
            c_name = task.get('customer_name', '')
            
            card_color = "white"
            try:
                due = datetime.datetime.strptime(f"{t_date} {t_time}", "%Y-%m-%d %H:%M")
                if not is_done and due < datetime.datetime.now(): card_color = "#FFEBEE"
            except: pass
            if is_done: card_color = "#E0E0E0"

            # 삭제 로직
            def delete_item(e, d_id=doc_id):
                if fs_manager.delete_todo(d_id):
                    page.snack_bar = ft.SnackBar(ft.Text("삭제되었습니다."), bgcolor=Colors.INFO)
                    page.snack_bar.open = True
                    render_todos() # 새로고침
                else:
                    page.snack_bar = ft.SnackBar(ft.Text("삭제 실패"), bgcolor=Colors.ERROR)
                    page.snack_bar.open = True
                    page.update()

            # 수정 로직 (닫기 개선됨)
            def edit_item(e, d_id=doc_id, old_title=title, old_date=t_date, old_time=t_time):
                tf_edit_title = ft.TextField(label="내용", value=old_title)
                tf_edit_date = ft.TextField(label="날짜", value=old_date, width=130)
                tf_edit_time = ft.TextField(label="시간", value=old_time, width=100)

                def close_edit(e):
                    dlg_edit.open = False
                    if dlg_edit in page.overlay:
                        page.overlay.remove(dlg_edit)
                    page.update()

                def save_edit(e):
                    if fs_manager.update_todo_content(d_id, tf_edit_title.value, tf_edit_date.value, tf_edit_time.value):
                        page.snack_bar = ft.SnackBar(ft.Text("수정되었습니다."), bgcolor=Colors.SUCCESS)
                        page.snack_bar.open = True
                        render_todos()
                        close_edit(e)
                    else:
                        page.snack_bar = ft.SnackBar(ft.Text("수정 실패"), bgcolor=Colors.ERROR)
                        page.snack_bar.open = True
                        page.update()

                dlg_edit = ft.AlertDialog(
                    title=ft.Text("할 일 수정"),
                    content=ft.Column([tf_edit_title, ft.Row([tf_edit_date, tf_edit_time])], height=150, tight=True),
                    actions=[
                        ft.TextButton("취소", on_click=close_edit),
                        ft.FilledButton("수정", on_click=save_edit, style=ft.ButtonStyle(bgcolor=Colors.PRIMARY))
                    ]
                )
                page.overlay.append(dlg_edit)
                dlg_edit.open = True
                page.update()

            # UI 조립
            chk_done = ft.Checkbox(value=is_done, on_change=lambda e, did=doc_id: toggle_todo(did, e.control.value))
            
            action_buttons = ft.Row([
                ft.IconButton(ft.Icons.EDIT, icon_size=18, icon_color=Colors.ACCENT, tooltip="수정", on_click=edit_item),
                ft.IconButton(ft.Icons.DELETE, icon_size=18, icon_color=Colors.ERROR, tooltip="삭제", on_click=delete_item),
                ft.IconButton(ft.Icons.CHAT_BUBBLE_OUTLINE, icon_size=18, icon_color=Colors.PRIMARY, tooltip="댓글", on_click=lambda e, d=doc_id, n=c_name: show_comment_sheet(d, n))
            ], spacing=0)

            card = ft.Container(
                content=ft.Row([
                    ft.Row([
                        chk_done,
                        ft.Column([
                            ft.Text(
                                f"[{c_name}] {title}", 
                                weight="bold", 
                                size=14, 
                                style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH) if is_done else None
                            ),
                            ft.Text(f"마감: {t_date} {t_time} | 접수번호: {task.get('receipt_num', '-')}", size=11, color=Colors.TEXT_SUB)
                        ], spacing=2)
                    ]),
                    action_buttons
                ], alignment="spaceBetween"),
                bgcolor=card_color, padding=10, border_radius=8, border=ft.Border.all(1, Colors.BORDER)
            )
            todo_list_view.controls.append(card)
        
        todo_list_view.update()

    def toggle_todo(doc_id, value):
        fs_manager.update_todo_status(doc_id, value)
        render_todos() # 새로고침

    # 댓글 바텀시트
    bs_comments = ft.BottomSheet(content=ft.Container(padding=20, bgcolor="white"))
    page.overlay.append(bs_comments)

    def show_comment_sheet(todo_id, customer_name):
        # 1. 내용을 담을 컬럼 생성
        comments_col = ft.Column(scroll=ft.ScrollMode.AUTO, height=300)
        tf_comment = ft.TextField(hint_text="댓글 입력...", expand=True, height=40, text_size=13)
        
        # 2. 댓글 로딩 함수
        def load_comments():
            comments_col.controls.clear()
            c_list = fs_manager.get_comments(todo_id)
            for c in c_list:
                comments_col.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text(c.get('content'), size=13),
                            ft.Text(f"{c.get('writer')} | {c.get('created_at')}", size=10, color="grey")
                        ]),
                        bgcolor="#F5F5F5", padding=8, border_radius=6, margin=ft.Margin(0,0,0,5)
                    )
                )
            # [핵심] 화면에 붙어있을 때만 업데이트 수행
            try:
                comments_col.update()
            except:
                pass 

        # 3. 댓글 추가 함수
        def add_comment(e):
            if not tf_comment.value: return
            data = {
                "content": tf_comment.value,
                "writer": tf_id.value,
                "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            fs_manager.add_comment(todo_id, data)
            tf_comment.value = ""
            tf_comment.update()
            load_comments()

        # 4. [중요] 바텀시트에 먼저 내용을 할당합니다 (update 호출 전)
        bs_comments.content = ft.Container(
            content=ft.Column([
                ft.Text(f"메모 스레드 - {customer_name}", size=16, weight="bold"),
                ft.Divider(),
                comments_col,
                ft.Row([tf_comment, ft.IconButton(ft.Icons.SEND, on_click=add_comment)])
            ]),
            padding=20, bgcolor="white", border_radius=ft.BorderRadius.vertical(top=15)
        )
        
        # 5. 시트를 열고 화면을 갱신합니다.
        bs_comments.open = True
        bs_comments.update()
        
        # 6. 이제 화면에 붙었으니 데이터를 로드합니다.
        load_comments()

    # ------------------------------------------------------------------
    # [수정] 스케줄 등록 팝업 (취소 버튼 로직 수정 완료)
    # ------------------------------------------------------------------
    def open_schedule_popup(customer, r_num, i_id):
        try:
            # 1. 입력 필드 생성
            tf_todo_title = ft.TextField(label="할 일 내용", value="확인 필요", autofocus=True)
            tf_date_pick = ft.TextField(label="날짜(YYYY-MM-DD)", value=datetime.date.today().strftime("%Y-%m-%d"), width=150)
            tf_time_pick = ft.TextField(label="시간(HH:MM)", value="09:00", width=100)
            
            # 2. [핵심 수정] 닫기 함수 (순서를 다른 팝업과 동일하게 통일)
            def close_popup(e):
                dlg_schedule.open = False
                # 오버레이에 있으면 제거
                if dlg_schedule in page.overlay:
                    page.overlay.remove(dlg_schedule)
                # 제거 후 화면 갱신 (이 순서가 가장 안전합니다)
                page.update()
            
            # 3. 저장 로직
            def save_schedule(e):
                # 유효성 검사 (내용이 비었을 경우)
                if not tf_todo_title.value.strip():
                    tf_todo_title.error_text = "내용을 입력해주세요"
                    tf_todo_title.update()
                    return

                data = {
                    "owner_id": tf_id.value,
                    "customer_name": customer,
                    "receipt_num": r_num,
                    "internal_id": i_id,
                    "title": tf_todo_title.value,
                    "target_date": tf_date_pick.value,
                    "target_time": tf_time_pick.value,
                    "is_done": False,
                    "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                if fs_manager.add_todo(data):
                    page.snack_bar = ft.SnackBar(ft.Text("📅 스케줄 등록 완료"), bgcolor=Colors.SUCCESS)
                    page.snack_bar.open = True
                    # 목록 갱신이 필요하다면 아래 주석 해제 (단, 현재 탭이 할 일이 아닐 수 있음)
                    # render_todos() 
                    close_popup(e) # 저장 성공 시 닫기
                else:
                    page.snack_bar = ft.SnackBar(ft.Text("등록 실패"), bgcolor=Colors.ERROR)
                    page.snack_bar.open = True
                    page.update()

            # 4. 다이얼로그 UI 생성
            dlg_schedule = ft.AlertDialog(
                title=ft.Text(f"스케줄 등록 - {customer}"),
                content=ft.Column([
                    tf_todo_title, 
                    ft.Row([tf_date_pick, tf_time_pick])
                ], height=150, tight=True),
                actions=[
                    ft.TextButton("취소", on_click=close_popup),
                    ft.FilledButton("저장", on_click=save_schedule, style=ft.ButtonStyle(bgcolor=Colors.PRIMARY))
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )

            # 5. 오버레이에 추가하고 열기
            page.overlay.append(dlg_schedule)
            dlg_schedule.open = True
            page.update()
            
        except Exception as e:
            print(f"Popup Error: {e}")

    # ------------------------------------------------------------------
    # [수정] QnA 게시판 (검색창 추가 + 헤더 고정 + 이력 관리)
    # ------------------------------------------------------------------
    # [핵심 수정] 헤더 고정을 위해 여기서 scroll 옵션을 제거합니다. (내부 리스트만 스크롤)
    qna_main_col = ft.Column(expand=True) 
    
    def close_qna_board(e=None):
        qna_layer.visible = False
        qna_layer.update()

    qna_panel = ft.Container(
        content=qna_main_col,
        bgcolor="white",
        border_radius=ft.BorderRadius.vertical(top=20),
        padding=25,
        shadow=ft.BoxShadow(blur_radius=20, color="#4D000000"),
        on_click=lambda e: None
    )

    qna_layer = ft.Container(
        content=qna_panel,
        bgcolor="#80000000",
        visible=False,
        alignment=ft.Alignment(0, 1),
        padding=ft.padding.only(top=70, left=100), 
        on_click=lambda e: close_qna_board(),
        expand=True,
        animate_opacity=300
    )
    page.overlay.append(qna_layer)

    def open_qna_board(e):
        # 창 크기에 맞게 조절
        win_w = page.width if page.width else 1200
        qna_panel.width = (win_w - 100) * 0.95
        
        qna_layer.opacity = 1
        qna_layer.visible = True
        qna_layer.update()
        
        # UI 렌더링 함수
        def render_qna_ui(mode='list', target_data=None, search_keyword=""):
            qna_main_col.controls.clear()
            
            # ==============================================================
            # 1. 목록 화면 (List)
            # ==============================================================
            if mode == 'list':
                # 검색창
                tf_search = ft.TextField(hint_text="제목/작성자/카테고리 검색", value=search_keyword, height=35, text_size=13, content_padding=10, width=250, bgcolor="#F0F0F0", border_radius=8, border_width=0, on_submit=lambda e: render_qna_ui('list', search_keyword=e.control.value))
                btn_search = ft.IconButton(icon=ft.Icons.SEARCH, icon_size=20, on_click=lambda e: render_qna_ui('list', search_keyword=tf_search.value))

                header = ft.Row([
                    ft.Row([ft.Text("매뉴얼 & QnA", size=24, weight="bold", color=Colors.PRIMARY), ft.Container(width=10), tf_search, btn_search], vertical_alignment="center"),
                    ft.FilledButton("새 글 작성", icon=ft.Icons.EDIT, on_click=lambda e: render_qna_ui('write'))
                ], alignment="spaceBetween")
                
                all_posts = fs_manager.get_qna_list()
                filtered_posts = []
                
                kw = search_keyword.lower()
                for p in all_posts:
                    if not kw or kw in p.get('title', '').lower() or kw in p.get('writer', '').lower() or kw in p.get('category', '').lower():
                        filtered_posts.append(p)

                lv = ft.ListView(expand=True, spacing=10)
                if not filtered_posts:
                    lv.controls.append(ft.Container(content=ft.Text("등록된 글이 없습니다.", color="grey"), padding=20))
                else:
                    for p in filtered_posts:
                        is_edited = " (수정됨)" if p.get('history') else ""
                        cat = p.get('category', '일반')
                        
                        cat_color = Colors.PRIMARY if cat == "매뉴얼" else (Colors.ERROR if cat == "공지" else Colors.TEXT_SUB)
                        
                        card = ft.Container(
                            content=ft.Row([
                                ft.Column([
                                    ft.Row([
                                        ft.Container(content=ft.Text(cat, size=10, color="white", weight="bold"), bgcolor=cat_color, padding=ft.Padding(6,2,6,2), border_radius=4),
                                        ft.Text(f"{p.get('title')} {is_edited}", weight="bold", size=15),
                                    ], vertical_alignment="center"),
                                    ft.Text(f"작성자: {p.get('writer')} | {p.get('created_at')}", size=11, color="grey")
                                ], expand=True),
                                ft.Icon(ft.Icons.CHEVRON_RIGHT, color="grey")
                            ]),
                            padding=15, bgcolor="#F9F9F9", border_radius=10,
                            on_click=lambda e, d=p: render_qna_ui('detail', d), ink=True
                        )
                        lv.controls.append(card)
                
                qna_main_col.controls = [header, ft.Divider(), ft.Container(content=lv, expand=True)]

            # ==============================================================
            # 2. 작성 화면 (Write) - [에러 수정됨]
            # ==============================================================
            elif mode == 'write':
                tabs_state = [{"name": "기본 내용", "content": ""}]
                if target_data: 
                    tabs_state = []
                    raw_tabs = target_data.get('tabs', [])
                    if isinstance(raw_tabs, list):
                        for t in raw_tabs:
                            if 'name' in t: tabs_state.append(t)
                            elif 'mapValue' in t: 
                                f = t['mapValue']['fields']
                                tabs_state.append({'name': f['name']['stringValue'], 'content': f['content']['stringValue']})
                    if not tabs_state: tabs_state = [{"name": "기본 내용", "content": target_data.get('content', '')}]

                tf_title = ft.TextField(label="제목", value=target_data.get('title') if target_data else "", autofocus=True)
                tf_category = ft.TextField(label="카테고리", value=target_data.get('category') if target_data else "일반", hint_text="예: 매뉴얼, 공지, 트러블슈팅", width=200)
                tf_faq = ft.TextField(label="FAQ (자주 묻는 질문)", value=target_data.get('faq_content') if target_data else "", multiline=True, min_lines=3, max_lines=10, hint_text="이 글과 관련된 FAQ를 입력하세요.")

                tabs_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

                def add_table_template(e, content_field):
                    tpl = "\n| 항목 | 내용 | 비고 |\n|---|---|---|\n| 데이터1 | 값1 | - |\n| 데이터2 | 값2 | - |\n"
                    content_field.value = (content_field.value or "") + tpl
                    content_field.update()
                    content_field.focus()

                def update_tab_state(idx, key, val): tabs_state[idx][key] = val
                def add_new_tab(e): tabs_state.append({"name": "새 탭", "content": ""}); render_tab_inputs()
                def remove_tab(idx): tabs_state.pop(idx); render_tab_inputs()

                def render_tab_inputs():
                    tabs_container.controls.clear()
                    for i, tab in enumerate(tabs_state):
                        tf_t_name = ft.TextField(label=f"탭 {i+1} 이름", value=tab['name'], width=200, height=40, content_padding=10, text_size=13, on_change=lambda e, idx=i: update_tab_state(idx, 'name', e.control.value))
                        tf_t_content = ft.TextField(label="내용 (Markdown & 표 지원)", value=tab['content'], multiline=True, min_lines=5, max_lines=10, expand=True, on_change=lambda e, idx=i: update_tab_state(idx, 'content', e.control.value))
                        
                        btn_table = ft.TextButton("표 삽입 ", icon=ft.Icons.TABLE_CHART, on_click=lambda e, tf=tf_t_content: add_table_template(e, tf))
                        btn_del = ft.IconButton(ft.Icons.DELETE, icon_color=Colors.ERROR, on_click=lambda e, idx=i: remove_tab(idx), visible=(len(tabs_state)>1))

                        tabs_container.controls.append(
                            ft.Container(
                                content=ft.Column([
                                    ft.Row([tf_t_name, btn_table, ft.Container(expand=True), btn_del], alignment="spaceBetween"),
                                    tf_t_content
                                ]),
                                padding=10, border=ft.Border.all(1, Colors.BORDER), border_radius=8, margin=ft.Margin(0,0,0,10)
                            )
                        )
                    
                    tabs_container.controls.append(ft.OutlinedButton("탭 추가 (+)", icon=ft.Icons.ADD, on_click=add_new_tab))
                    
                    # [핵심 수정] 초기 로딩 시 아직 화면에 붙지 않아 에러나는 것을 방지
                    try:
                        tabs_container.update()
                    except:
                        pass 

                def save_action(e):
                    if not tf_title.value: return
                    data = {
                        "title": tf_title.value,
                        "category": tf_category.value,
                        "tabs": tabs_state,
                        "faq_content": tf_faq.value,
                    }
                    
                    if target_data: # 수정
                        new_h = [{"date": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), "editor": tf_id.value, "prev_content": f"제목: {target_data.get('title')}"}]
                        if fs_manager.update_qna(target_data.get('doc_id'), data, new_h):
                            page.snack_bar = ft.SnackBar(ft.Text("수정되었습니다."), bgcolor=Colors.SUCCESS)
                            page.snack_bar.open=True; page.update()
                            render_qna_ui('list')
                    else: # 신규
                        data["writer"] = tf_id.value
                        data["created_at"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        if fs_manager.add_qna(data):
                            page.snack_bar = ft.SnackBar(ft.Text("등록되었습니다."), bgcolor=Colors.SUCCESS)
                            render_qna_ui('list')
                    
                    page.snack_bar.open=True; page.update()

                render_tab_inputs() # 초기 실행

                qna_main_col.controls = [
                    ft.Text("글 작성/수정", size=20, weight="bold"),
                    ft.Row([tf_category, tf_title], spacing=10),
                    ft.Divider(),
                    ft.Text("본문 구성 (탭 별로 내용 입력)", weight="bold"),
                    ft.Container(content=tabs_container, expand=True), 
                    ft.Divider(),
                    ft.Text("FAQ (마지막 탭에 고정 노출)", weight="bold"),
                    tf_faq,
                    ft.Row([
                        ft.TextButton("취소", on_click=lambda e: render_qna_ui('list')),
                        ft.FilledButton("저장", on_click=save_action)
                    ], alignment="end")
                ]

            # ==============================================================
            # 3. 상세 화면 (Detail)
            # ==============================================================
            elif mode == 'detail' and target_data:
                doc_id = target_data.get('doc_id')
                
                parsed_tabs = []
                raw_tabs = target_data.get('tabs', [])
                if isinstance(raw_tabs, list):
                    for t in raw_tabs:
                        if 'name' in t: parsed_tabs.append(t)
                        elif 'mapValue' in t:
                            f = t['mapValue']['fields']
                            parsed_tabs.append({'name': f['name']['stringValue'], 'content': f['content']['stringValue']})
                
                if not parsed_tabs and target_data.get('content'):
                    parsed_tabs.append({"name": "기본 내용", "content": target_data.get('content')})

                faq_txt = target_data.get('faq_content')
                if faq_txt:
                    parsed_tabs.append({"name": "FAQ / 자주 묻는 질문", "content": faq_txt})

                detail_tabs = ft.Tabs(selected_index=0, animation_duration=300, tabs=[], expand=True)

                for t in parsed_tabs:
                    detail_tabs.tabs.append(
                        ft.Tab(
                            text=t['name'],
                            content=ft.Container(
                                content=ft.Markdown(
                                    t['content'], 
                                    selectable=True, 
                                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB 
                                ),
                                padding=20, 
                                scroll=ft.ScrollMode.AUTO
                            )
                        )
                    )

                top_row = ft.Row([
                    ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: render_qna_ui('list')),
                    ft.Column([
                        ft.Row([
                            ft.Container(content=ft.Text(target_data.get('category', '일반'), size=10, color="white"), bgcolor=Colors.PRIMARY, padding=4, border_radius=4),
                            ft.Text(target_data.get('title'), size=18, weight="bold"),
                        ], spacing=5),
                        ft.Text(f"작성자: {target_data.get('writer')} | {target_data.get('created_at')}", size=11, color="grey")
                    ]),
                    ft.Container(expand=True),
                    ft.FilledButton("수정", icon=ft.Icons.EDIT, on_click=lambda e: render_qna_ui('write', target_data)),
                    ft.IconButton(ft.Icons.DELETE, icon_color=Colors.ERROR, on_click=lambda e: (fs_manager.delete_qna(doc_id) and render_qna_ui('list')) or page.update())
                ])
                
                if target_data.get('writer') != tf_id.value and tf_id.value != 'admin':
                    top_row.controls[-1].visible = False
                    top_row.controls[-2].visible = False

                qna_main_col.controls = [top_row, ft.Divider(height=1), detail_tabs]

            qna_layer.update()

        render_qna_ui('list')

    # ---------------------------------------------------
    # [4] PubSub & Logic
    # ---------------------------------------------------
    def update_result_view():
        global current_page
        result_list.controls.clear()
        
        total_items = len(data_store)
        if total_items == 0:
            result_list.controls.append(ft.Text("결과 없음", color=Colors.TEXT_SUB))
            txt_page_info.value = "0 / 0"
            btn_prev_page.disabled = True
            btn_next_page.disabled = True
            page.update()
            return

        total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
        if current_page > total_pages: current_page = total_pages
        if current_page < 1: current_page = 1
        
        start_idx = (current_page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_rows = data_store[start_idx:end_idx]

        new_controls = []
        for r in current_rows:
            internal_id = r.get('internal_id')
            cname = r.get('customer')
            sub_info = r.get('sub_info', '') 
            rnum = r.get('receipt_num')
            status = r.get('status')
            prod = r.get('product')
            
            btn_copy = ft.IconButton(icon=ft.Icons.CONTENT_COPY, icon_size=14, icon_color=Colors.TEXT_SUB, tooltip="복사", data=f"{rnum} {cname}", on_click=lambda e: pyperclip.copy(e.control.data) or page.pubsub.send_all({'topic': 'toast', 'payload': {'msg': '복사됨'}}))
            
            # [추가됨] 상세 버튼: 클릭 시 브라우저로 원본 페이지 열기
            btn_detail = ft.FilledButton(
                content=ft.Text("상세", size=11, color="white"), 
                style=ft.ButtonStyle(padding=0, bgcolor="#455A64", shape=ft.RoundedRectangleBorder(radius=4)), 
                height=26, 
                width=50, 
                on_click=lambda e, i=internal_id: webbrowser.open(f"https://druwaint.co.kr/manager/system_data/edit_form.asp?number={i}", new=2)
            )

            btn_sub = ft.FilledButton(content=ft.Text("청약", size=11, color="white"), style=ft.ButtonStyle(padding=0, bgcolor=Colors.INFO, shape=ft.RoundedRectangleBorder(radius=4)), height=26, width=50, on_click=lambda e, i=internal_id, n=cname: open_bottom_sheet_subscription(i, n))
            btn_memo = ft.FilledButton(content=ft.Text("회신", size=11, color="white"), style=ft.ButtonStyle(padding=0, bgcolor=Colors.PRIMARY, shape=ft.RoundedRectangleBorder(radius=4)), height=26, width=50, on_click=lambda e, i=internal_id, n=cname: open_bottom_sheet_memo(i, n))
            btn_return = ft.FilledButton(content=ft.Text("반송", size=11, color="white"), style=ft.ButtonStyle(padding=0, bgcolor=Colors.ERROR, shape=ft.RoundedRectangleBorder(radius=4)), height=26, width=50, on_click=lambda e, i=internal_id, n=cname: open_bottom_sheet_return(i, n))
            
            # ==================================================================
            # [추가] 스케줄 등록 다이얼로그 및 버튼 정의 (card_content 정의보다 위에 있어야 함)
            # ==================================================================
            def open_schedule_dialog(e, customer, r_num, i_id):
                # 다이얼로그 UI 구성
                tf_todo_title = ft.TextField(label="할 일 내용", value="확인 필요", autofocus=True)
                tf_date_pick = ft.TextField(label="날짜(YYYY-MM-DD)", value=datetime.date.today().strftime("%Y-%m-%d"), width=150)
                tf_time_pick = ft.TextField(label="시간(HH:MM)", value="09:00", width=100)
                
                def save_schedule(e):
                    data = {
                        "owner_id": tf_id.value,
                        "customer_name": customer,
                        "receipt_num": r_num,
                        "internal_id": i_id,
                        "title": tf_todo_title.value,
                        "target_date": tf_date_pick.value,
                        "target_time": tf_time_pick.value,
                        "is_done": False,
                        "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    if fs_manager.add_todo(data):
                        page.snack_bar = ft.SnackBar(ft.Text("📅 스케줄 등록 완료"), bgcolor=Colors.SUCCESS)
                        page.snack_bar.open = True
                        page.update()
                        dlg_schedule.open = False
                        page.update()
                    else:
                        page.snack_bar = ft.SnackBar(ft.Text("등록 실패"), bgcolor=Colors.ERROR)
                        page.snack_bar.open = True
                        page.update()

                dlg_schedule = ft.AlertDialog(
                    title=ft.Text(f"스케줄 등록 - {customer}"),
                    content=ft.Column([tf_todo_title, ft.Row([tf_date_pick, tf_time_pick])], height=150),
                    actions=[ft.TextButton("취소", on_click=lambda e: setattr(dlg_schedule, 'open', False) or page.update()), ft.TextButton("저장", on_click=save_schedule)]
                )
                page.dialog = dlg_schedule
                dlg_schedule.open = True
                page.update()

            # ==================================================================
            # [수정] 스케줄 버튼 (위에서 만든 함수 호출로 단순화)
            # ==================================================================
            btn_schedule = ft.IconButton(
                icon=ft.Icons.CALENDAR_MONTH, 
                icon_color=Colors.ACCENT, 
                tooltip="스케줄 등록",
                # [핵심] 1단계에서 만든 open_schedule_popup 함수를 호출합니다.
                on_click=lambda e, c=cname, r=rnum, i=internal_id: open_schedule_popup(c, r, i)
            )

            # 카드 내용 조립 (버튼 리스트에 btn_schedule 포함)
            action_buttons = ft.Row(
                [btn_copy, btn_detail, btn_sub, btn_memo, btn_return, btn_schedule], 
                spacing=5, 
                alignment="end"
            )

            card_content = ft.Row([
                ft.Column([
                    ft.Row([
                        ft.Text(
                            spans=[
                                ft.TextSpan(cname, ft.TextStyle(weight=ft.FontWeight.BOLD, color=Colors.TEXT_MAIN)), 
                                ft.TextSpan(sub_info, ft.TextStyle(weight=ft.FontWeight.NORMAL, color=Colors.TEXT_SUB, size=12)), 
                            ],
                            size=13,
                            selectable=True
                        ),
                        ft.Container(content=ft.Text(status, color="white", size=9), bgcolor=Colors.PRIMARY, padding=ft.Padding.symmetric(horizontal=4, vertical=1), border_radius=3)
                    ], spacing=5, vertical_alignment="center"),
                    ft.Text(f"{rnum} | {prod}", size=11, color=Colors.TEXT_SUB, no_wrap=True)
                ], spacing=0, expand=True),
                # action_buttons 변수 사용
                action_buttons 
            ], alignment="spaceBetween", vertical_alignment="center")
            # [추가] 스케줄 등록 버튼
            def open_schedule_dialog(e, customer, r_num, i_id):
                # 다이얼로그 UI 구성
                tf_todo_title = ft.TextField(label="할 일 내용", value="확인 필요", autofocus=True)
                tf_date_pick = ft.TextField(label="날짜(YYYY-MM-DD)", value=datetime.date.today().strftime("%Y-%m-%d"), width=150)
                tf_time_pick = ft.TextField(label="시간(HH:MM)", value="09:00", width=100)
                
                def save_schedule(e):
                    data = {
                        "owner_id": tf_id.value,
                        "customer_name": customer,
                        "receipt_num": r_num,
                        "internal_id": i_id,
                        "title": tf_todo_title.value,
                        "target_date": tf_date_pick.value,
                        "target_time": tf_time_pick.value,
                        "is_done": False,
                        "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    if fs_manager.add_todo(data):
                        page.snack_bar = ft.SnackBar(ft.Text("📅 스케줄 등록 완료"), bgcolor=Colors.SUCCESS)
                        page.snack_bar.open = True
                        page.update()
                        dlg_schedule.open = False
                        page.update()
                        # To-Do 탭으로 이동하고 싶다면 아래 주석 해제
                        # rail.selected_index = 6; update_tab(6)
                    else:
                        page.snack_bar = ft.SnackBar(ft.Text("등록 실패"), bgcolor=Colors.ERROR)
                        page.snack_bar.open = True
                        page.update()

                dlg_schedule = ft.AlertDialog(
                    title=ft.Text(f"스케줄 등록 - {customer}"),
                    content=ft.Column([tf_todo_title, ft.Row([tf_date_pick, tf_time_pick])], height=150),
                    actions=[ft.TextButton("취소", on_click=lambda e: setattr(dlg_schedule, 'open', False) or page.update()), ft.TextButton("저장", on_click=save_schedule)]
                )
                page.dialog = dlg_schedule
                dlg_schedule.open = True
                page.update()

            # 버튼 생성
            btn_schedule = ft.IconButton(
                icon=ft.Icons.CALENDAR_MONTH, 
                icon_color=Colors.ACCENT, 
                tooltip="스케줄 등록",
                on_click=lambda e, c=cname, r=rnum, i=internal_id: open_schedule_dialog(e, c, r, i)
            )

            card = ft.Container(content=card_content, bgcolor="white", padding=8, border_radius=6, border=ft.Border.all(1, Colors.BORDER))
            new_controls.append(card)
        
        result_list.controls = new_controls
        
        txt_page_info.value = f"{current_page} / {total_pages}"
        btn_prev_page.disabled = (current_page == 1)
        btn_next_page.disabled = (current_page == total_pages)
        
        result_list.update()
        txt_page_info.update()
        btn_prev_page.update()
        btn_next_page.update()

    def change_page(delta):
        global current_page
        current_page += delta
        update_result_view()

    btn_prev_page.on_click = lambda e: change_page(-1)
    btn_next_page.on_click = lambda e: change_page(1)

    def on_message(msg):
        topic = msg.get("topic")
        payload = msg.get("payload")

        # [추가됨] 뽀모도로 타이머 갱신 신호 처리
        if topic == "pomo_tick":
            # 1. 시간 텍스트 업데이트
            mins, secs = divmod(pomo_state["current_left"], 60)
            txt_pomo_time.value = f"{mins:02d}:{secs:02d}"
            
            # 2. 진행바 업데이트
            if pomo_state["total_time"] > 0:
                prog = 1 - (pomo_state["current_left"] / pomo_state["total_time"])
            else: prog = 0
            bar_pomo_progress.value = prog
            
            # 3. 버튼 텍스트/색상 업데이트
            if pomo_state["is_running"]:
                btn_pomo_action.text = "일시정지"
                btn_pomo_action.style.bgcolor = Colors.TEXT_SUB
            else:
                if pomo_state["mode"] == "focus":
                    btn_pomo_action.text = "업무시작" 
                    btn_pomo_action.style.bgcolor = Colors.PRIMARY
                else:
                    btn_pomo_action.text = "휴식시작"
                    btn_pomo_action.style.bgcolor = Colors.SUCCESS
            
            # 4. 모드별 색상 변경
            txt_pomo_time.color = Colors.PRIMARY if pomo_state["mode"] == "focus" else Colors.SUCCESS
            
            # [핵심] 실제 화면 반영 (메인 쓰레드에서 실행되므로 즉시 반응함)
            txt_pomo_time.update()
            bar_pomo_progress.update()
            btn_pomo_action.update()

        elif topic == "log_search":
            log_area_search.controls.append(ft.Text(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {payload['msg']}", color=payload['color'], size=11))
            log_area_search.update()
        elif topic == "force_refresh":
            bs_bottom_sheet.update()
            page.update()
        elif topic == "log_assign":
            log_area_assign.controls.append(ft.Text(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {payload['msg']}", color=payload['color'], size=12))
            log_area_assign.update()
        elif topic == "log_opening":
            log_area_opening.controls.append(ft.Text(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {payload['msg']}", color=payload['color'], size=12))
            log_area_opening.update()
        elif topic == "log_complete":
            log_area_complete.controls.append(ft.Text(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {payload['msg']}", color=payload['color'], size=12))
            log_area_complete.update()
        elif topic == "dash_update":
            d = payload
            # 1. 오늘의 골든대구 권역별 신청현황 (신청완료 건)
            txt_cnt_apply.value = str(d.get('app_capital', 0)) # 수도권
            txt_cnt_proc.value = str(d.get('app_chung', 0))    # 충청권
            txt_cnt_done.value = str(d.get('app_gb', 0))       # 경북권
            
            # 2. 권역별 접수현황 (접수중 건)
            txt_m_cnt_apply.value = str(d.get('proc_capital', 0)) # 수도권
            txt_m_cnt_proc.value = str(d.get('proc_chung', 0))    # 충청권
            txt_m_cnt_done.value = str(d.get('proc_gb', 0))       # 경북권
            
            # 3. 도윤 현황 (기존 유지)
            txt_dy_return.value = str(d.get('dy_return', txt_dy_return.value))
            txt_dy_proc.value = str(d.get('dy_proc', txt_dy_proc.value))
            txt_dy_check.value = str(d.get('dy_check', txt_dy_check.value))
            txt_dy_apply.value = str(d.get('dy_apply', txt_dy_apply.value))
            txt_dy_unopened.value = str(d.get('dy_unopened', txt_dy_unopened.value))
            
            txt_dash_update.value = f"마지막 갱신: {datetime.datetime.now().strftime('%H:%M:%S')}"
            dashboard_view.update()
        elif topic == "search_result":
            # Modified for Pagination
            global current_page
            if payload['target'] == 'search':
                data_store.clear()
                if payload['rows']: data_store.extend(payload['rows'])
                current_page = 1
                # Must call this on main thread logic, but here inside on_message it is fine
                update_result_view()
                page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'search', 'visible': False}})
            elif payload['target'] == 'complete':
                render_search_list(payload['rows'], payload['target'])
        
        # [NEW] Badge Update Logic
        elif topic == "update_badge":
            count = payload.get('count', 0)
            if count > 0:
                txt_badge_count.value = str(count) if count <= 99 else "99+"
                container_badge.visible = True
                icon_bell.icon = ft.Icons.NOTIFICATIONS_ACTIVE # Active Icon
                icon_bell.icon_color = Colors.ERROR
            else:
                container_badge.visible = False
                icon_bell.icon = ft.Icons.NOTIFICATIONS_NONE
                icon_bell.icon_color = Colors.TEXT_MAIN
            
            icon_bell.update()
            container_badge.update()

        elif topic == "toast":
            page.snack_bar = ft.SnackBar(ft.Text(payload['msg']), bgcolor=payload.get('color', Colors.PRIMARY))
            page.snack_bar.open = True
            page.update()
        elif topic == "set_loading":
            target = payload['target']
            visible = payload['visible']
            if target == 'search': 
                prog_search.visible = visible; prog_search.update()
                btn_extract.disabled = visible; btn_extract.update()
            elif target == 'assign': 
                prog_assign.visible = visible; prog_assign.update()
                btn_assign_start.disabled = visible; btn_assign_start.update()
            elif target == 'opening': 
                prog_opening.visible = visible; prog_opening.update()
                btn_opening_start.disabled = visible; btn_opening_start.update()
            elif target == 'complete': 
                prog_complete.visible = visible; prog_complete.update()
                btn_complete_search.disabled = visible; btn_complete_search.update()
            
            if not visible: page.update()

    page.pubsub.subscribe(on_message)

    # ---------------------------------------------------
    # [5] Modern Dashboard Components
    # ---------------------------------------------------
    doyoon_list_container = ft.Column(spacing=5)
    doyoon_detail_section = ft.Container(
        content=doyoon_list_container,
        visible=False,
        padding=15,
        bgcolor=Colors.BG_CARD,
        border_radius=12,
        border=ft.Border.all(1, Colors.BORDER),
    )
    current_detail_category = [None]

    def toggle_doyoon_list(category):
        if doyoon_detail_section.visible and current_detail_category[0] == category:
            doyoon_detail_section.visible = False
            current_detail_category[0] = None
        else:
            rows = doyoon_details.get(category, [])
            doyoon_list_container.controls.clear()
            
            if not rows:
                doyoon_list_container.controls.append(ft.Text("데이터가 없습니다.", color=Colors.TEXT_SUB, size=12))
            else:
                doyoon_list_container.controls.append(ft.Text(f"상세 목록 ({len(rows)}건)", weight="bold", size=14, color=Colors.TEXT_MAIN))
                for r in rows:
                    cname = r.get('customer')
                    rnum = r.get('receipt_num')
                    status = r.get('status')
                    
                    item = ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(cname, weight="bold", size=13),
                                ft.Text(rnum, size=11, color=Colors.TEXT_SUB)
                            ], spacing=2),
                            ft.Container(content=ft.Text(status, color="white", size=10, weight="bold"), bgcolor=Colors.PRIMARY, padding=ft.Padding.symmetric(horizontal=8, vertical=4), border_radius=4)
                        ], alignment="spaceBetween"),
                        padding=10, bgcolor=Colors.BG_MAIN, border_radius=8
                    )
                    doyoon_list_container.controls.append(item)
            
            doyoon_detail_section.visible = True
            current_detail_category[0] = category
            
        dashboard_view.update()

    def create_stat_card(title, count_txt, color, on_click_action=None):
        return ft.Container(
            content=ft.Column([
                ft.Text(title, size=12, weight="w600", color=Colors.TEXT_SUB), 
                count_txt
            ], spacing=5),
            bgcolor=Colors.BG_CARD,
            padding=20,
            border_radius=12,
            expand=True,
            border=ft.Border.all(1, Colors.BORDER),
            on_click=on_click_action,
            ink=True if on_click_action else False
        )

    # [신규] 갱신 주기 설정 기본값 (15분 = 900초)
    app_state["dashboard_interval"] = 900 

    # [신규] 시간 변경 핸들러
    def on_change_interval(e):
        val = e.control.value
        if val == "OFF":
            app_state["dashboard_interval"] = -1
        else:
            app_state["dashboard_interval"] = int(val) * 60
        
        page.snack_bar = ft.SnackBar(ft.Text(f"갱신 주기가 {val}분으로 변경되었습니다."), bgcolor=Colors.PRIMARY)
        page.snack_bar.open = True
        page.update()

    # [신규] 시간 선택 드롭다운
    dd_interval = ft.Dropdown(
        width=100,
        height=35,
        text_size=12,
        # content_padding=5,  # [수정] 에러 방지를 위해 제거
        value="15", 
        options=[
            ft.dropdown.Option("5", "5분"),
            ft.dropdown.Option("15", "15분"),
            ft.dropdown.Option("30", "30분"),
            ft.dropdown.Option("OFF", "OFF"),
        ],
        # on_change=on_change_interval, # [수정] 생성자에서 제거하고 아래에서 별도 할당
        bgcolor="white",
        border_radius=8,
        border_color=Colors.BORDER,
    )
    # [핵심] 이벤트 핸들러를 별도로 연결 (에러 해결)
    dd_interval.on_change = on_change_interval

    # [수정됨] Dashboard View 정의 (괄호 오류 수정 및 권역별 UI 적용 완료)
    dashboard_view = ft.Container(
        content=ft.Column(
            controls=[
                # 1. 상단 헤더 영역
                ft.Row([
                    ft.Text("Dashboard", size=24, weight="bold", color=Colors.TEXT_MAIN),
                    
                    # 우측 컨트롤 (자동갱신 + 드롭다운 + 새로고침)
                    ft.Row([
                        ft.Text("자동갱신:", size=12, color=Colors.TEXT_SUB),
                        dd_interval, 
                        ft.IconButton(ft.Icons.REFRESH, icon_color=Colors.PRIMARY, tooltip="즉시 갱신", on_click=lambda e: run_all_dashboards())
                    ], vertical_alignment="center", spacing=10)
                ], alignment="spaceBetween"),

                ft.Divider(height=20, color="transparent"),
                
                # 2. 도윤 접수 현황 (상단)
                ft.Text("도윤 접수 현황 (최근 21일)", size=16, weight="bold", color=Colors.TEXT_MAIN),
                ft.Row([
                    create_stat_card("신청완료", txt_dy_apply, Colors.SUCCESS, lambda e: toggle_doyoon_list("apply")), 
                    create_stat_card("실사요청중", txt_dy_return, Colors.ERROR, lambda e: toggle_doyoon_list("return")), 
                    create_stat_card("접수중", txt_dy_proc, Colors.WARNING, lambda e: toggle_doyoon_list("proc")),
                    create_stat_card("미할당", txt_dy_check, Colors.ACCENT, lambda e: toggle_doyoon_list("check")),
                    create_stat_card("미개통", txt_dy_unopened, "#5D4037", lambda e: toggle_doyoon_list("unopened"))
                ], spacing=15),
                
                doyoon_detail_section,
                ft.Divider(height=30, color="transparent"),
                
                # 3. 하단 권역별 현황 (좌/우 분할)
                ft.Row([
                    # 왼쪽 섹션: 오늘의 골든대구 권역별 신청현황 (오늘 신청완료 건)
                    ft.Column([
                        ft.Text("권역별 신청현황", size=16, weight="bold", color=Colors.TEXT_MAIN),
                        ft.Row([
                            create_stat_card("수도권", txt_cnt_apply, Colors.SUCCESS),
                            create_stat_card("충청권", txt_cnt_proc, Colors.WARNING),
                            create_stat_card("경북권", txt_cnt_done, Colors.INFO)
                        ], spacing=15)
                    ], expand=True),
                    
                    ft.Container(width=20),
                    
                    # 오른쪽 섹션: 권역별 접수현황 (오늘 접수중 건)
                    ft.Column([
                        ft.Text("권역별 접수현황", size=16, weight="bold", color=Colors.TEXT_MAIN),
                        ft.Row([
                            create_stat_card("수도권", txt_m_cnt_apply, Colors.ERROR),
                            create_stat_card("충청권", txt_m_cnt_proc, Colors.WARNING),
                            create_stat_card("경북권", txt_m_cnt_done, Colors.INFO)
                        ], spacing=15)
                    ], expand=True)
                ]),

                # 4. 마지막 업데이트 시간
                ft.Container(content=txt_dash_update, alignment=ft.Alignment(1.0, 0.0), padding=ft.Padding.only(top=20))
            ], 
            scroll=ft.ScrollMode.AUTO
        ), 
        padding=30, 
        expand=True, 
        visible=True
    )
    # ---------------------------------------------------
    # [6] Search & Filter Components
    # ---------------------------------------------------
    today = datetime.date.today()
    # [수정] 날짜 입력창 폰트 잘림 방지 (content_padding 축소)
    tf_sdate = ft.TextField(
        value=(today).strftime('%Y-%m-%d'), 
        label="시작일", 
        width=120, 
        height=35, 
        text_size=12, 
        content_padding=3, # 10 -> 5로 수정
        border_color=Colors.BORDER,
        expand=True
    )
    tf_edate = ft.TextField(
        value=today.strftime('%Y-%m-%d'), 
        label="종료일", 
        width=120, 
        height=35, 
        text_size=12, 
        content_padding=3, # 10 -> 5로 수정
        border_color=Colors.BORDER,
        expand=True
    )
    tf_sdate_c = ft.TextField(value=today.replace(day=1).strftime('%Y-%m-%d'), label="시작일", width=130, height=40, text_size=13, content_padding=10, border_color=Colors.BORDER)
    tf_edate_c = ft.TextField(value=today.strftime('%Y-%m-%d'), label="종료일", width=130, height=40, text_size=13, content_padding=10, border_color=Colors.BORDER)
    
    tf_keyword_c = ft.TextField(hint_text="고객명 검색", expand=True, height=40, text_size=13, content_padding=10, border_color=Colors.BORDER, bgcolor="white", border_radius=8)

    def set_date_range(e):
        days = e.control.data
        t = datetime.date.today()
        if days == 0: s, e_d = t, t
        elif days == 1: s, e_d = t-datetime.timedelta(days=1), t-datetime.timedelta(days=1)
        elif days == 3: s, e_d = t-datetime.timedelta(days=3), t
        elif days == 7: s, e_d = t-datetime.timedelta(days=7), t
        elif days == 30: s, e_d = t-datetime.timedelta(days=30), t
        tf_sdate.value, tf_edate.value = s.strftime('%Y-%m-%d'), e_d.strftime('%Y-%m-%d')
        page.update()

    def create_date_chip(text, days):
        return ft.Container(
            content=ft.Text(text, size=11, color=Colors.TEXT_SUB),
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            border=ft.Border.all(1, Colors.BORDER),
            border_radius=20,
            on_click=set_date_range, data=days, ink=True,
            bgcolor=Colors.BG_CARD
        )

    row_date_btns = ft.Row([create_date_chip("오늘", 0), create_date_chip("어제", 1), create_date_chip("3일", 3), create_date_chip("1주", 7), create_date_chip("1달", 30)], spacing=5)

    dd_keyword_mode = ft.Dropdown(
        width=100, options=[ft.dropdown.Option("a.uname", "고객명"), ft.dropdown.Option("aa.customnum", "접수번호")],
        value="a.uname", height=35, text_size=12, content_padding=ft.Padding.symmetric(horizontal=10),
        border_color=Colors.BORDER, bgcolor="white", border_radius=8
    )
    tf_keyword = ft.TextField(hint_text="검색어", expand=True, height=35, text_size=12, content_padding=ft.Padding.symmetric(horizontal=10), border_color=Colors.BORDER, bgcolor="white", border_radius=8)
    
    # [UI 수정] 대리점 필터 디자인 개선 (세로 스크롤 목록 적용)
    
    agency_list = ["000", "레드기업", "레드텔레콤", "골든대구", "골든대전", "대승아이앤씨", "에이케이넷", "새로", "ZD", "두웰", "해빛", "월드", "준유통", "그린파머", "아진정보", "라이크유", "디코비즈", "에스디앤", "에스디앤서울", "K스타", "줌네트워크", "SN"]
    
    agency_checkboxes = []
    
    # 개별 체크박스 생성
    for name in agency_list:
        agency_checkboxes.append(
            ft.Checkbox(
                label=name, 
                value=False, 
                active_color=Colors.PRIMARY, 
                label_style=ft.TextStyle(size=12, color=Colors.TEXT_MAIN) # 글자 크기 조정
            )
        )

    # 전체 선택 로직
    def on_all_change(e):
        for cb in agency_checkboxes:
            cb.value = e.control.value
        page.update()

    # 스크롤 가능한 컨테이너로 구성
    agency_grid = ft.Container(
        content=ft.Column(
            controls=[
                # 전체 선택 체크박스
                ft.Checkbox(
                    label="전체 선택", 
                    value=False, 
                    active_color=Colors.PRIMARY, 
                    on_change=on_all_change,
                    label_style=ft.TextStyle(weight="bold", size=12)
                ),
                ft.Divider(height=1, color=Colors.BORDER),
                # 개별 체크박스 목록 (세로 배치)
                ft.Column(
                    controls=agency_checkboxes,
                    spacing=0, # 체크박스 간 간격 좁힘
                )
            ],
            scroll=ft.ScrollMode.AUTO, # 스크롤 활성화
        ),
        height=150, # 높이 제한 (스크롤 생성을 위해 필수)
        padding=5,
        border=ft.Border.all(1, "#EEEEEE"),
        border_radius=6
    )

    # ---------------------------------------------------
    # [7] Bottom Sheet & Dialogs (청약 전용 커스텀 레이어)
    # ---------------------------------------------------
    
    # [기존 유지] 일반 메모/반송용 바텀시트
    bs_main_column = ft.Column(controls=[ft.Text("초기화 중...", color="grey")], scroll=ft.ScrollMode.AUTO, expand=True)
    bs_content = ft.Container(content=bs_main_column, padding=25, bgcolor="white", border_radius=ft.BorderRadius.vertical(top=20))
    
    def on_bs_dismiss(e): 
        app_state["active_copy_handler"] = None 
        bs_bottom_sheet.open = False
        bs_bottom_sheet.update()

    bs_bottom_sheet = ft.BottomSheet(content=bs_content, on_dismiss=on_bs_dismiss)
    page.overlay.append(bs_bottom_sheet)

    # ==========================================================================
    # [신규] 청약 전용 대형 레이어 (Custom Overlay)
    # ==========================================================================
    # [핵심 수정] scroll=ft.ScrollMode.AUTO 제거! (헤더 고정을 위해)
    bs_sub_column = ft.Column(expand=True) 

    def close_sub_sheet(e=None):
        app_state["active_copy_handler"] = None
        # 닫을 때: 투명하게 만들고 -> 비활성화
        sub_layer.opacity = 0
        sub_layer.update()
        time.sleep(0.2) 
        sub_layer.visible = False
        sub_layer.update()

    # 1. 흰색 팝업창 (패널)
    bs_sub_panel = ft.Container(
        content=bs_sub_column,
        bgcolor="white",
        border_radius=ft.BorderRadius.vertical(top=20),
        padding=25,
        shadow=ft.BoxShadow(blur_radius=20, color="#4D000000"), 
        
        # [중요] 팝업 내부를 클릭했을 때 팝업이 닫히지 않게 하기 위한 설정입니다.
        # 이 설정 때문에 마우스가 손가락 모양으로 보일 수 있으나, 
        # 프로그램 충돌 방지를 위해 mouse_cursor 속성은 제거합니다.
        on_click=lambda e: None,
    )

    # 2. 검은 배경
    sub_layer = ft.Container(
        content=bs_sub_panel,
        bgcolor="#80000000",
        visible=False,
        opacity=0, 
        animate_opacity=500, # 부드러운 효과
        alignment=ft.Alignment(0, 1), 
        padding=ft.padding.only(top=70, left=100),      
        on_click=lambda e: close_sub_sheet(), 
        expand=True 
    )
    
    page.overlay.append(sub_layer)
    
    # --------------------------------------------------------------------------
    # [누락된 함수 복구] 접수 완료(개통) 처리 팝업
    # --------------------------------------------------------------------------
    def open_bottom_sheet_completion(internal_id, customer_name):
        # 1. UI 초기화 (기존 바텀시트 사용)
        bs_content.height = (page.height or 800) * 0.85
        bs_content.width = None # 기본 너비 사용
        bs_content.update()
        
        comp_list_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        btn_all_container = ft.Container(alignment=ft.Alignment(1.0, 0))
        
        # 헤더 설정
        bs_main_column.controls = [
            ft.Text(f"접수완료 처리 - {customer_name}", size=18, weight="bold", color=Colors.INFO), 
            ft.Divider(color=Colors.BORDER), 
            ft.Container(content=comp_list_container, expand=True), 
            ft.Divider(color=Colors.BORDER), 
            btn_all_container
        ]
        bs_bottom_sheet.open = True
        bs_bottom_sheet.update()

        # 2. 데이터 로딩 (비동기)
        def _bg_load():
            time.sleep(0.3)
            try:
                # 상품 정보 가져오기
                products, action_url = engine.fetch_products_for_completion(internal_id)
                
                rows_controls = []
                inputs_refs = [] # 텍스트필드 참조 저장용

                if not products:
                    rows_controls.append(ft.Text("상품 없음", color="grey"))
                else:
                    # 2-1. 입력 필드 생성
                    for p in products:
                        inputs_refs.append(
                            ft.TextField(
                                label=f"{p['goods_name']}", 
                                value=p['current_val'], 
                                height=45, 
                                text_size=13, 
                                content_padding=10, 
                                expand=True, 
                                bgcolor="#F5F5F5", 
                                border_radius=8, 
                                border_width=0
                            )
                        )
                    
                    # 2-2. 각 줄에 버튼 추가
                    for idx, tf_ref in enumerate(inputs_refs):
                        # 클로저 (이벤트 핸들러 고정)
                        def make_click_handler(c_idx, c_refs):
                            def on_click_comp(e):
                                current_vals = [r.value for r in c_refs]
                                e.control.disabled = True
                                e.control.content = ft.Text("...", size=12)
                                e.control.update()
                                
                                # 개별 완료 처리 요청 (status -> 14)
                                if engine.submit_receipt_completion(internal_id, current_vals, target_index=c_idx):
                                    page.snack_bar = ft.SnackBar(ft.Text(f"개별 처리 완료"), bgcolor=Colors.SUCCESS)
                                    e.control.content = ft.Text("완료", size=12)
                                    e.control.bgcolor = "grey"
                                else:
                                    page.snack_bar = ft.SnackBar(ft.Text("실패"), bgcolor=Colors.ERROR)
                                    e.control.disabled = False
                                    e.control.content = ft.Text("완료처리", size=11)
                                
                                page.snack_bar.open = True
                                page.update()
                                e.control.update()
                                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})
                            return on_click_comp

                        btn = ft.FilledButton(
                            content=ft.Text("완료처리", size=11), 
                            bgcolor=Colors.INFO, 
                            color="white", 
                            width=80, 
                            height=45, 
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)), 
                            on_click=make_click_handler(idx, inputs_refs)
                        )
                        rows_controls.append(ft.Row([tf_ref, btn], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER))

                    # 2-3. 일괄 완료 버튼 로직
                    def on_click_all(e):
                        if not inputs_refs: return
                        e.control.disabled = True
                        e.control.text = "처리중..."
                        e.control.update()
                        
                        current_vals = [r.value for r in inputs_refs]
                        success_count = 0
                        
                        # 모든 항목에 대해 순차적으로 완료 처리
                        for i in range(len(inputs_refs)):
                            if engine.submit_receipt_completion(internal_id, current_vals, target_index=i):
                                success_count += 1
                            time.sleep(0.1) # 서버 부하 방지 딜레이

                        if success_count > 0:
                            page.snack_bar = ft.SnackBar(ft.Text(f"일괄 처리 완료 ({success_count}건)"), bgcolor=Colors.SUCCESS)
                            bs_bottom_sheet.open = False # 성공 시 닫기
                        else:
                            page.snack_bar = ft.SnackBar(ft.Text("일괄 처리 실패"), bgcolor=Colors.ERROR)
                            e.control.disabled = False
                            e.control.text = "일괄 완료"
                        
                        page.snack_bar.open = True
                        page.update()
                        page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})

                    btn_all = ft.FilledButton("일괄 완료", width=120, height=40, on_click=on_click_all, bgcolor=Colors.PRIMARY)
                    btn_all_container.content = btn_all

                comp_list_container.controls = rows_controls
                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})

            except Exception as e:
                comp_list_container.controls = [ft.Text(f"오류: {e}", color="red")]
                page.pubsub.send_all({'topic': 'force_refresh', 'payload': None})

        threading.Thread(target=_bg_load, daemon=True).start()

    # --------------------------------------------------------------------------
    # [누락된 함수 복구] 검색 결과 렌더링 (통합조회 & 접수완료 공용)
    # --------------------------------------------------------------------------
    def render_search_list(rows, target):
        # 1. 통합 조회 (Search Tab) 결과 처리
        if target == 'search':
            data_store.clear()
            if rows: 
                data_store.extend(rows)
            
            # 페이지네이션 초기화 및 화면 갱신
            global current_page
            current_page = 1
            update_result_view()
            
            # 로딩바 숨김 신호 전송
            page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'search', 'visible': False}})
        
        # 2. 접수 완료 (Complete Tab) 결과 처리
        elif target == 'complete':
            result_list_complete.controls.clear()
            new_controls = []
            
            if rows:
                for r in rows:
                    internal_id = r.get('internal_id')
                    cname = r.get('customer')
                    rnum = r.get('receipt_num')
                    status = r.get('status')
                    prod = r.get('product')
                    
                    # [상품 불러오기] 버튼 (접수완료 탭 전용)
                    btn_load = ft.FilledButton(
                        "상품 불러오기", 
                        icon=ft.Icons.DOWNLOAD, 
                        color="white", 
                        bgcolor=Colors.ACCENT, 
                        height=35, 
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=lambda e, i=internal_id, n=cname: open_bottom_sheet_completion(i, n)
                    )
                    
                    card = ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(cname, weight="bold", size=14), 
                                ft.Text(status, size=12, color=Colors.PRIMARY)
                            ], alignment="spaceBetween"), 
                            ft.Text(f"{rnum} | {prod}", size=12, color=Colors.TEXT_SUB), 
                            ft.Container(content=btn_load, alignment=ft.Alignment(1.0, 0))
                        ]), 
                        bgcolor="white", 
                        padding=15, 
                        border_radius=10, 
                        border=ft.Border.all(1, Colors.BORDER)
                    )
                    new_controls.append(card)
            else:
                new_controls.append(ft.Text("결과 없음", color=Colors.TEXT_SUB))
            
            result_list_complete.controls = new_controls
            result_list_complete.update()
            
            # 로딩바 숨김 신호 전송
            page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'complete', 'visible': False}})

    # ---------------------------------------------------
    # [8] Background Tasks
    # ---------------------------------------------------
    lv_notifications = ft.ListView(expand=True, spacing=10, padding=20)
    tab_notification = ft.Container(content=ft.Column([ft.Text("Notifications", size=20, weight="bold", color=Colors.TEXT_MAIN), ft.Text("회신 요망 중 '/윤' 고객 목록", size=12, color=Colors.TEXT_SUB), ft.Divider(color=Colors.BORDER), lv_notifications]), padding=20, expand=True, visible=False, bgcolor=Colors.BG_MAIN)
    
    # ==========================================
    # [SKB 요금 계산기] (정렬 오류 수정 & 렌더링 복구)
    # ==========================================
    calc_url = "https://kimkkoongkkoong-beep.github.io/SKB/"

    def on_launch_click(e):
        try:
            # 브라우저 실행 (새 탭)
            webbrowser.open(calc_url, new=2)
        except:
            pass

    tab_calculator = ft.Container(
        content=ft.Column([
            # 1. 헤더 (텍스트만 심플하게 배치)
            ft.Text("SKB 요금 계산기", size=24, weight="bold", color="#1e293b"),
            
            ft.Divider(height=40, color="transparent"),
            
            # 2. 실행 카드 (확실하게 보이도록 고정 크기 및 흰색 배경 지정)
            ft.Container(
                content=ft.Column([
                    ft.Text("웹 계산기 바로가기", size=20, weight="bold", color="#1e293b"),
                    ft.Text("아래 버튼을 누르면 계산기가 열립니다.", size=14, color="#64748b"),
                    
                    ft.Container(height=20),
                    
                    ft.FilledButton(
                        "계산기 열기",
                        icon="open_in_new", # 문자열 아이콘 사용
                        on_click=on_launch_click,
                        style=ft.ButtonStyle(
                            bgcolor="#7c3aed", # 보라색
                            color="white",
                            shape=ft.RoundedRectangleBorder(radius=12)
                        ),
                        width=200,
                        height=50
                    ),
                ], horizontal_alignment="center", alignment="center"),
                
                width=400,          # 너비 고정
                height=300,         # 높이 고정
                padding=30,
                bgcolor="#FFFFFF",  # [중요] 카드 배경 흰색
                border_radius=20,
                # [수정] 테두리 설정 (ft.Border.all 사용)
                border=ft.Border.all(1, "#e2e8f0"),
                # [수정] 그림자 설정 (투명도 포함된 HEX 색상 사용)
                shadow=ft.BoxShadow(blur_radius=20, color="#1A000000"),
                # [핵심 수정] ft.alignment.center -> ft.Alignment(0, 0) 로 변경
                alignment=ft.Alignment(0, 0)
            )
        ], horizontal_alignment="center", alignment="center"),
        
        # 전체 컨테이너 설정
        padding=20,
        expand=True,
        visible=False,      # [중요] 기본은 숨김 (update_tab에서 켜짐)
        bgcolor="#F8FAFC",  # 전체 배경 밝은 회색
        # [핵심 수정] ft.alignment.center -> ft.Alignment(0, 0) 로 변경
        alignment=ft.Alignment(0, 0)
    )
        
    # 1. 알림 뱃지(빨간 동그라미 + 숫자) UI 정의
    txt_badge_count = ft.Text("0", color="white", size=10, weight="bold")
    container_badge = ft.Container(
        content=txt_badge_count,
        bgcolor=Colors.ERROR, 
        width=16, height=16, 
        border_radius=8,
        alignment=ft.Alignment(0, 0),
        visible=False,  # 기본값은 숨김
        animate_opacity=300
    )

    # 2. 종 아이콘 정의
    icon_bell = ft.IconButton(
        icon=ft.Icons.NOTIFICATIONS_NONE, 
        icon_color=Colors.TEXT_MAIN, 
        tooltip="알림",
        on_click=None 
    )

    # 3. 겹치기 (Stack)
    btn_bell_stack = ft.Stack([
        icon_bell,
        ft.Container(content=container_badge, right=0, top=0) 
    ])

    def render_notification_view():
        lv_notifications.controls.clear()
        if not notification_items: lv_notifications.controls.append(ft.Text("새로운 알림이 없습니다.", color=Colors.TEXT_SUB, size=14))
        else:
            for item in notification_items:
                cname = item['customer']; rnum = item['receipt']; internal_id = item['id']
                btn_memo = ft.OutlinedButton(content=ft.Text("메모", size=12, color=Colors.PRIMARY), style=ft.ButtonStyle(side=ft.BorderSide(1, Colors.PRIMARY), padding=10, shape=ft.RoundedRectangleBorder(radius=8)), height=30, on_click=lambda e, i=internal_id, n=cname: open_bottom_sheet_memo(i, n))
                card = ft.Container(content=ft.Row([ft.Row([ft.Icon(ft.Icons.WARNING_ROUNDED, color=Colors.ERROR, size=24), ft.Column([ft.Text(f"[중요] {cname}", weight="bold", size=15), ft.Text(f"접수번호: {rnum}", size=12, color=Colors.TEXT_SUB)], spacing=2)]), btn_memo], alignment="spaceBetween"), bgcolor="white", padding=15, border_radius=12, border=ft.Border.all(1, Colors.BORDER))
                lv_notifications.controls.append(card)
        tab_notification.update()

    def on_bell_click(e):
        nonlocal is_alarm_active
        is_alarm_active = False 
        
        # [수정] 배지 숨기기 및 아이콘 초기화
        container_badge.visible = False
        icon_bell.icon_color = Colors.TEXT_MAIN
        icon_bell.icon = ft.Icons.NOTIFICATIONS_NONE
        
        icon_bell.update()
        container_badge.update()
        
        render_notification_view()
        rail.selected_index = 5; rail.update(); update_tab(5)
    
    # [중요] 위에서 만든 Stack 내부의 IconButton에 클릭 이벤트 연결
    icon_bell.on_click = on_bell_click

    # [전역 변수 위치에 추가 필요] - main 함수 밖에 두거나, main 함수 안쪽 상단에 배치
    # 하지만 _thread_dashboard_update 함수가 접근할 수 있어야 하므로
    # 보통 main 함수 내부, engine 정의 아래쯤에 두는 것이 좋습니다.
    dashboard_lock = threading.Lock() 

    # [주의] dashboard_lock = threading.Lock() 은 main 함수 내부 상단에 정의되어 있어야 합니다.

    # [수정할 함수] _thread_dashboard_update 내부
    
    def _thread_dashboard_update():
        if dashboard_lock.locked():
            print("DEBUG: 대시보드 중복 실행 방지됨")
            return

        with dashboard_lock:
            try:
                # -------------------------------------------------------------
                # 1. 날짜 계산
                # -------------------------------------------------------------
                today_date = datetime.date.today()
                today_str = today_date.strftime('%Y-%m-%d')
                
                yesterday_date = today_date - datetime.timedelta(days=1)
                yesterday_str = yesterday_date.strftime('%Y-%m-%d')

                month_1st_date = today_date.replace(day=1)
                
                days_21_ago_date = today_date - datetime.timedelta(days=21)
                days_21_ago_str = days_21_ago_date.strftime('%Y-%m-%d')
                
                # 쿼리 시작일
                start_query_date = min(month_1st_date, days_21_ago_date).strftime('%Y-%m-%d')
                
                # -------------------------------------------------------------
                # 2. 데이터 가져오기
                # -------------------------------------------------------------
                all_rows = engine.get_data_list(start_query_date, today_str, [], "a.uname", "")
                
                # [변수 초기화] 권역별 카운터
                # Section 1: 신청완료 (수도권, 충청권, 경북권)
                app_capital = 0; app_chung = 0; app_gb = 0
                
                # Section 2: 접수중 (수도권, 충청권, 경북권)
                proc_capital = 0; proc_chung = 0; proc_gb = 0

                # 도윤 통계 변수
                d_ret = 0; d_proc = 0; d_chk = 0; d_apply = 0; d_unopened = 0
                
                # 상세 리스트 초기화
                doyoon_details["return"] = []; doyoon_details["proc"] = []
                doyoon_details["check"] = []; doyoon_details["apply"] = []; doyoon_details["unopened"] = []

                if all_rows:
                    for i, r in enumerate(all_rows):
                        # 데이터 전처리
                        sub_info_clean = r.get('sub_info', '').strip() 
                        row_date = sub_info_clean.split(' ')[0].replace('.', '-')
                        
                        raw_status = r.get('status', '')
                        status_clean = raw_status.replace(" ", "")
                        
                        raw_customer = r.get('customer', '')
                        customer_clean = raw_customer.replace(" ", "")
                        
                        internal_id = r.get('internal_id')
                        
                        # [지역 판별 로직]
                        region_txt = r.get('region', '')
                        region_code = "other"
                        if any(x in region_txt for x in ["서울", "인천", "경기"]): region_code = "capital"
                        elif any(x in region_txt for x in ["충북", "세종", "충남", "대전"]): region_code = "chung"
                        elif any(x in region_txt for x in ["대구", "경북"]): region_code = "gb"

                        is_doyoon = "/윤" in customer_clean or "/윤" in raw_customer

                        # ---------------------------------------------------------
                        # 1 & 2) 권역별 현황 (조건: 오늘 날짜)
                        # ---------------------------------------------------------
                        if row_date == today_str:
                            # 1. 신청완료 상태 (Section 1)
                            if "신청" in status_clean and "완료" in status_clean:
                                if region_code == "capital": app_capital += 1
                                elif region_code == "chung": app_chung += 1
                                elif region_code == "gb": app_gb += 1
                            
                            # 2. 접수중 상태 (Section 2)
                            elif "접수" in status_clean and "완료" not in status_clean:
                                if region_code == "capital": proc_capital += 1
                                elif region_code == "chung": proc_chung += 1
                                elif region_code == "gb": proc_gb += 1
                        
                        # ---------------------------------------------------------
                        # 3) 도윤 접수 현황
                        # ---------------------------------------------------------
                        if row_date >= days_21_ago_str and is_doyoon:
                            if "실사" in status_clean:
                                d_ret += 1
                                doyoon_details["return"].append(r)
                                
                            elif "접수" in status_clean and "완료" not in status_clean:
                                d_proc += 1
                                doyoon_details["proc"].append(r)
                                
                            elif "신청" in status_clean: 
                                d_apply += 1
                                doyoon_details["apply"].append(r)

                            # 미할당 (어제~21일전 & 접수완료 & 할당일 없음)
                            if days_21_ago_str <= row_date <= yesterday_str:
                                if "접수완료" in status_clean:
                                    try:
                                        det = engine.fetch_detail_info(internal_id, verbose=False)
                                        if not det.get('wantdate', '').strip(): 
                                            d_chk += 1
                                            doyoon_details["check"].append(r)
                                    except: pass
                            
                            # 미개통 (접수완료 & 희망일 지남 & 개통일 없음)
                            if "접수완료" in status_clean:
                                try:
                                    det = engine.fetch_detail_info(internal_id, verbose=False)
                                    if det:
                                        w = det.get('wantdate', '').replace('.', '-').strip()
                                        i = det.get('installdate', '').strip()
                                        if w and w < today_str and not i:
                                            d_unopened += 1
                                            doyoon_details["unopened"].append(r)
                                except: pass

                # 디버그 출력 (새 변수명 적용)
                print(f"DEBUG: 집계완료 -> 수도권신청:{app_capital}, 도윤미할당:{d_chk}")

                # UI 업데이트 신호 전송
                page.pubsub.send_all({
                    'topic': 'dash_update', 
                    'payload': {
                        'app_capital': app_capital, 'app_chung': app_chung, 'app_gb': app_gb,
                        'proc_capital': proc_capital, 'proc_chung': proc_chung, 'proc_gb': proc_gb,
                        'dy_return': d_ret, 'dy_proc': d_proc, 'dy_check': d_chk, 
                        'dy_apply': d_apply, 'dy_unopened': d_unopened
                    }
                })
                
            except Exception as e:
                print(f"Dashboard Error: {e}")
                traceback.print_exc()

    def run_all_dashboards(): threading.Thread(target=_thread_dashboard_update, daemon=True).start()

    def _background_loops():
        loop_count = 0
        dash_timer = 0 # 대시보드용 별도 타이머 추가

        while True:
            # 1. 스케줄/알림 체크 (기존 로직 유지 - 약 60초마다)
            if loop_count % 60 == 0: 
                try:
                    # ... (기존 알림 로직 유지) ...
                    found_replays = engine.scan_replay_demand()
                    current_alerts = [item for item in found_replays if "/윤" in item['customer']]
                    
                    if current_alerts:
                        # ... (기존 알림 처리 코드 유지) ...
                        notification_items.clear()
                        notification_items.extend(current_alerts)
                        page.pubsub.send_all({'topic': 'update_badge', 'payload': {'count': len(current_alerts)}})
                        
                        # ... (알림창 띄우는 기존 코드 생략) ...
                    else: 
                        notification_items.clear()
                        page.pubsub.send_all({'topic': 'update_badge', 'payload': {'count': 0}})
                except: pass
            
            # [수정됨] 2. 대시보드 자동 갱신 로직 (가변 시간 적용)
            # app_state에서 현재 설정된 주기를 가져옴 (기본값 900초)
            current_interval = app_state.get("dashboard_interval", 900)
            
            if current_interval != -1: # OFF가 아닐 때만 실행
                if dash_timer >= current_interval:
                    run_all_dashboards()
                    dash_timer = 0 # 타이머 초기화
            
            # [추가] 스케줄 알림 체크 (기존 코드 유지)
            if loop_count % 60 == 0:
                # ... (기존 스케줄 알림 로직 유지) ...
                pass

            # 루프 제어
            time.sleep(0.5)
            loop_count += 0.5
            dash_timer += 0.5 # 대시보드 타이머 증가

    # ---------------------------------------------------
    # [9] Navigation & Layout Layout
    # ---------------------------------------------------
    def on_login_click(e):
        btn_login.disabled = True; prog_login.visible = True; page.update()
        if engine.login(tf_id.value, tf_pw.value):
            page.clean(); page.add(main_layout); page.pubsub.send_all({'topic': 'log_search', 'payload': {'msg': "로그인 성공", 'color': Colors.SUCCESS}})
            threading.Thread(target=_background_loops, daemon=True).start(); run_all_dashboards()
        else:
            page.snack_bar = ft.SnackBar(ft.Text("로그인 실패"), bgcolor=Colors.ERROR); page.snack_bar.open=True; btn_login.disabled = False
        prog_login.visible = False; page.update()

    def on_extract_click(e):
        page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'search', 'visible': True}})
        def _search():
            try:
                selected = [cb.label for cb in agency_checkboxes if cb.value]
                rows = engine.get_data_list(tf_sdate.value, tf_edate.value, selected, dd_keyword_mode.value, tf_keyword.value, lambda m, c="white": page.pubsub.send_all({'topic': 'log_search', 'payload': {'msg': m, 'color': c}}))
                page.pubsub.send_all({'topic': 'search_result', 'payload': {'target': 'search', 'rows': rows}})
            except Exception as e: page.pubsub.send_all({'topic': 'log_search', 'payload': {'msg': f"Error: {e}", 'color': "red"}})
            finally: page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'search', 'visible': False}})
        threading.Thread(target=_search, daemon=True).start()

    def on_complete_search_click(e):
        page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'complete', 'visible': True}})
        def _search():
            try:
                rows = engine.get_data_list(tf_sdate_c.value, tf_edate_c.value, [], "a.uname", tf_keyword_c.value, lambda m, c="white": page.pubsub.send_all({'topic': 'log_complete', 'payload': {'msg': m, 'color': c}}))
                page.pubsub.send_all({'topic': 'search_result', 'payload': {'target': 'complete', 'rows': rows}})
            except Exception as e: page.pubsub.send_all({'topic': 'log_complete', 'payload': {'msg': f"Error: {e}", 'color': "red"}})
            finally: page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'complete', 'visible': False}})
        threading.Thread(target=_search, daemon=True).start()

    def on_save_click(e):
        try:
            filename = f"Doyoon_{datetime.datetime.now().strftime('%m%d_%H%M')}.csv"
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=["date", "receipt_num", "product", "agency", "customer", "status", "internal_id"])
                writer.writeheader(); writer.writerows(data_store)
            page.pubsub.send_all({'topic': 'toast', 'payload': {'msg': f"저장됨: {filename}", 'color': Colors.SUCCESS}})
        except Exception as ex: page.pubsub.send_all({'topic': 'toast', 'payload': {'msg': f"실패: {ex}", 'color': Colors.ERROR}})

    def parse_input(text): return [line.split() for line in text.strip().split('\n') if len(line.split()) >= 2] if text else []

    def on_assign_start(e):
        items = parse_input(tf_input_assign.value)
        if not items: return
        page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'assign', 'visible': True}})
        def _run():
            try:
                for r, d in items: engine.process_assignment(r, d, lambda m, c="white": page.pubsub.send_all({'topic': 'log_assign', 'payload': {'msg': m, 'color': c}})); time.sleep(0.5)
            finally: page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'assign', 'visible': False}})
        threading.Thread(target=_run, daemon=True).start()

    def on_opening_start(e):
        items = parse_input(tf_input_opening.value)
        if not items: return
        page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'opening', 'visible': True}})
        def _run():
            try:
                for r, d in items: engine.process_opening(r, d, lambda m, c="white": page.pubsub.send_all({'topic': 'log_opening', 'payload': {'msg': m, 'color': c}})); time.sleep(0.5)
            finally: page.pubsub.send_all({'topic': 'set_loading', 'payload': {'target': 'opening', 'visible': False}})
        threading.Thread(target=_run, daemon=True).start()
    # 1. 통합조회 엔터키 연결
    tf_keyword.on_submit = on_extract_click
    
    # 2. 접수완료 대상 조회 엔터키 연결 (편의상 같이 추가해 드립니다)
    tf_keyword_c.on_submit = on_complete_search_click

    # Buttons Construction (Updated to FilledButton)
    btn_login = ft.FilledButton("로그인", on_click=on_login_click, width=300, height=45, style=ft.ButtonStyle(bgcolor=Colors.PRIMARY, color="white", shape=ft.RoundedRectangleBorder(radius=8)))
    
    # [수정됨] 버튼 높이 35px로 통일 및 패딩 조정
    btn_extract = ft.FilledButton("조회", icon=ft.Icons.SEARCH, on_click=on_extract_click, bgcolor=Colors.PRIMARY, color="white", height=35, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), padding=ft.Padding.symmetric(horizontal=15)))
    btn_save = ft.OutlinedButton("저장", icon=ft.Icons.SAVE_ALT, on_click=on_save_click, height=35, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), color=Colors.PRIMARY, side=ft.BorderSide(1, Colors.PRIMARY), padding=ft.Padding.symmetric(horizontal=15)))
    
    btn_assign_start = ft.FilledButton("작업 시작", icon=ft.Icons.PLAY_ARROW, on_click=on_assign_start, bgcolor=Colors.PRIMARY, color="white", height=45)
    btn_opening_start = ft.FilledButton("작업 시작", icon=ft.Icons.PLAY_ARROW, on_click=on_opening_start, bgcolor=Colors.PRIMARY, color="white", height=45)
    btn_complete_search = ft.FilledButton("대상 조회", icon=ft.Icons.SEARCH, on_click=on_complete_search_click, bgcolor=Colors.INFO, color="white", height=40)

    # Component Builders
    def create_log_box(log_ctrl):
        # Height Reduced from 200 to 100
        return ft.Container(content=ft.Column([ft.Text("System Logs", size=11, weight="bold", color=Colors.TEXT_SUB), log_ctrl], spacing=2), bgcolor="#263238", padding=10, border_radius=8, height=80)

    # [수정] 높이를 40으로 줄여서 여백 문제 해결
    dd_keyword_mode.width = 100 
    dd_keyword_mode.height = 40   # 80 -> 40으로 수정 (표준 크기)
    dd_keyword_mode.text_size = 13 # 글자 크기 적당히 조정
    dd_keyword_mode.content_padding = 10 # 내부 텍스트 위치 정렬
    dd_keyword_mode.expand = False

   # [UI 수정 v5] 로딩바(prog_search) 위치를 제목 바로 아래로 이동
    
    tab_search = ft.Container(
        content=ft.Row([
            # 1. 좌측 필터 패널 (기존 유지)
            ft.Container(
                content=ft.Column([
                    ft.Text("검색 옵션", weight="bold", size=15, color=Colors.TEXT_MAIN),
                    ft.Divider(height=5, color="transparent"),
                    
                    ft.Text("기간 설정", size=12, color=Colors.TEXT_SUB),
                    ft.Container(content=row_date_btns, padding=ft.Padding(0,0,0,5)), 
                    ft.Row([tf_sdate, ft.Text("~"), tf_edate], alignment="center"),
                    
                    ft.Divider(height=15, color="transparent"), 
                    
                    ft.Text("검색 조건", size=12, color=Colors.TEXT_SUB),
                    dd_keyword_mode, 
                    
                    ft.Container(height=5), 
                    
                    ft.Row([
                        tf_keyword, 
                        btn_extract 
                    ], spacing=5),

                    ft.Divider(height=15, color="transparent"),
                    
                    ft.ExpansionTile(
                        title=ft.Text("대리점 필터", size=13),
                        controls=[agency_grid],
                        collapsed_icon_color=Colors.PRIMARY,
                        tile_padding=0
                    ),
                    
                    ft.Container(expand=True), 
                ], spacing=5),
                width=240, 
                bgcolor="white", 
                padding=15, 
                border_radius=12, 
                border=ft.Border.all(1, Colors.BORDER),
                expand=False 
            ),

            # 2. 우측 데이터 패널 (로딩바 위치 수정됨)
            ft.Container(
                content=ft.Column([
                    # [수정] 상단 헤더: 제목 <-> 저장버튼 (양끝 배치)
                    ft.Row([
                        ft.Text("통합 조회 결과", size=15, weight="bold", color=Colors.TEXT_MAIN),
                        btn_save # 저장 버튼 우측 끝 고정
                    ], alignment="spaceBetween", vertical_alignment="center"),
                    
                    # [수정] 로딩바 위치 이동 (제목 바로 아래)
                    # 평소엔 안 보이다가 조회 시에만 나타나서 가로로 움직입니다.
                    ft.Container(content=prog_search, height=4), 
                    
                    ft.Divider(height=5, color="transparent"),

                    # 데이터 리스트
                    ft.Container(
                        content=result_list, 
                        expand=True, 
                        bgcolor="white", 
                    ),
                    
                    # 페이지네이션 & 로그
                    ft.Row([btn_prev_page, txt_page_info, btn_next_page], alignment="center"),
                    create_log_box(log_area_search)
                ], spacing=5), # 간격 미세 조정
                expand=True, 
                bgcolor="white", 
                padding=15, 
                border_radius=12, 
                border=ft.Border.all(1, Colors.BORDER) 
            )
        ], spacing=15, vertical_alignment=ft.CrossAxisAlignment.STRETCH), 
        padding=15, 
        visible=False, 
        expand=True
    )

    tab_complete = ft.Container(content=ft.Column([
        ft.Text("접수완료 처리", size=24, weight="bold", color=Colors.TEXT_MAIN),
        ft.Text("접수번호 입력 시 자동으로 대상 상품을 찾아 처리합니다.", size=13, color=Colors.TEXT_SUB),
        ft.Divider(height=20, color="transparent"),
        ft.Container(content=ft.Row([tf_sdate_c, ft.Text("~", color=Colors.TEXT_SUB), tf_edate_c, tf_keyword_c], vertical_alignment="center"), bgcolor="white", padding=20, border_radius=12, border=ft.Border.all(1, Colors.BORDER)),
        ft.Row([btn_complete_search]), prog_complete,
        ft.Container(content=result_list_complete, expand=True, bgcolor="white", border_radius=12, border=ft.Border.all(1, Colors.BORDER), padding=10),
        create_log_box(log_area_complete)
    ]), padding=30, visible=False, expand=True)


   # ------------------------------------------------------------------
    # [수정] To-Do 탭 전용: 일반 일정 등록 다이얼로그 (닫기 버그 수정됨)
    # ------------------------------------------------------------------
    def open_general_add_dialog(e):
        try:
            # 입력 필드 구성
            tf_title = ft.TextField(label="할 일 내용", autofocus=True)
            tf_cust = ft.TextField(label="관련 고객명 (선택)", text_size=12, hint_text="입력하지 않으면 '일반'으로 저장됨")
            
            now = datetime.datetime.now()
            tf_date = ft.TextField(label="날짜(YYYY-MM-DD)", value=now.strftime("%Y-%m-%d"), width=130, text_size=13)
            tf_time = ft.TextField(label="시간(HH:MM)", value=now.strftime("%H:%M"), width=100, text_size=13)

            # [수정] 닫기 함수 (오버레이 제거 시도 X, 그냥 닫기만)
            def close_popup(e):
                dlg_general_add.open = False
                page.update()

            def save_action(e):
                if not tf_title.value:
                    tf_title.error_text = "내용을 입력하세요"
                    tf_title.update()
                    return
                
                data = {
                    "owner_id": tf_id.value,
                    "customer_name": tf_cust.value if tf_cust.value.strip() else "일반 메모",
                    "receipt_num": "-",
                    "internal_id": "",
                    "title": tf_title.value,
                    "target_date": tf_date.value,
                    "target_time": tf_time.value,
                    "is_done": False,
                    "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                if fs_manager.add_todo(data):
                    page.snack_bar = ft.SnackBar(ft.Text("✅ 할 일이 등록되었습니다."), bgcolor=Colors.SUCCESS)
                    page.snack_bar.open = True
                    render_todos() # 목록 먼저 갱신
                    close_popup(e) # 그 다음 팝업 닫기
                else:
                    page.snack_bar = ft.SnackBar(ft.Text("❌ 등록 실패"), bgcolor=Colors.ERROR)
                    page.snack_bar.open = True
                    page.update()

            dlg_general_add = ft.AlertDialog(
                title=ft.Text("새 할 일 등록"),
                content=ft.Column([
                    tf_title, 
                    tf_cust, 
                    ft.Container(height=10),
                    ft.Row([tf_date, tf_time])
                ], height=220, tight=True),
                actions=[
                    ft.TextButton("취소", on_click=close_popup),
                    ft.FilledButton("저장", on_click=save_action, style=ft.ButtonStyle(bgcolor=Colors.PRIMARY))
                ]
            )
            
            page.overlay.append(dlg_general_add)
            dlg_general_add.open = True
            page.update()
        except Exception as ex:
            print(f"General Add Error: {ex}")

    # ------------------------------------------------------------------
    # [수정] 스케줄 탭 UI (등록 버튼 추가됨)
    # ------------------------------------------------------------------
    tab_todo = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("할 일 관리", size=24, weight="bold", color=Colors.TEXT_MAIN),
                # 우측 상단 버튼 그룹
                ft.Row([
                    ft.FilledButton("할 일 등록", icon=ft.Icons.ADD, on_click=open_general_add_dialog, style=ft.ButtonStyle(bgcolor=Colors.ACCENT)),
                    ft.IconButton(ft.Icons.REFRESH, tooltip="새로고침", on_click=lambda e: render_todos())
                ])
            ], alignment="spaceBetween"),
            
            ft.Divider(),
            
            # 리스트 영역
            ft.Container(
                content=todo_list_view, 
                expand=True, 
                bgcolor="white", 
                border_radius=12, 
                padding=10, 
                border=ft.Border.all(1, Colors.BORDER)
            )
        ]),
        padding=30, visible=False, expand=True
    )
    
    # ------------------------------------------------------------------
    # [신규] 설정 탭 (요금제 관리) - 에러 수정됨
    # ------------------------------------------------------------------
    def save_rates_to_file(e, editor_tf):
        try:
            new_data = json.loads(editor_tf.value)
            rate_manager.save_rates(new_data)
            page.snack_bar = ft.SnackBar(ft.Text("요금 설정이 저장되었습니다."), bgcolor=Colors.SUCCESS)
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"저장 실패 (JSON 형식 오류): {ex}"), bgcolor=Colors.ERROR)
        page.snack_bar.open = True
        page.update()

    # [수정] font_family 직접 사용 대신 text_style 사용
    tf_rate_json = ft.TextField(
        label="요금 데이터 (JSON)", 
        multiline=True, 
        value=json.dumps(rate_manager.data, indent=4, ensure_ascii=False), 
        min_lines=20, 
        text_size=13, 
        text_style=ft.TextStyle(font_family="Consolas") # 여기가 수정되었습니다
    )
    
    tab_settings = ft.Container(
        content=ft.Column([
            ft.Text("환경 설정", size=24, weight="bold", color=Colors.TEXT_MAIN),
            ft.Divider(),
            ft.Text("상품 요금 설정 (주의: 형식을 유지하며 숫자만 변경하세요)", size=14, color=Colors.ERROR),
            ft.Container(content=tf_rate_json, expand=True, border=ft.Border.all(1, Colors.BORDER), border_radius=8, padding=10),
            ft.Row([
                ft.FilledButton("설정 저장", icon=ft.Icons.SAVE, on_click=lambda e: save_rates_to_file(e, tf_rate_json)),
                ft.OutlinedButton("초기화 (기본값)", on_click=lambda e: setattr(tf_rate_json, 'value', json.dumps(rate_manager.default_rates, indent=4, ensure_ascii=False)) or page.update())
            ], alignment="end")
        ]),
        padding=30, visible=False, expand=True
    )

    def create_work_tab(title, desc, inp, prog, log, btn):
        return ft.Container(content=ft.Column([
            ft.Text(title, size=24, weight="bold", color=Colors.TEXT_MAIN), ft.Text(desc, size=13, color=Colors.TEXT_SUB),
            ft.Divider(height=20, color="transparent"),
            ft.Row([ft.Container(content=inp, expand=True, padding=10, bgcolor="white", border_radius=12, border=ft.Border.all(1, Colors.BORDER)), ft.Container(width=20), ft.Column([btn], alignment="start")], alignment="start", vertical_alignment="start", expand=True),
            prog, create_log_box(log)
        ]), padding=30, visible=False, expand=True)

    tab_assign = create_work_tab("할당일 일괄 등록", "엑셀 등에서 복사한 [접수번호] [날짜] 데이터를 붙여넣으세요.", tf_input_assign, prog_assign, log_area_assign, btn_assign_start)
    tab_opening = create_work_tab("개통일(완료) 일괄 등록", "엑셀 등에서 복사한 [접수번호] [날짜] 데이터를 붙여넣으세요.", tf_input_opening, prog_opening, log_area_opening, btn_opening_start)

    # 10. Navigation Rail (Sidebar) - [수정] 요금계산기 메뉴 추가
    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=100,
        min_extended_width=200,
        group_alignment=-0.9,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD_ROUNDED, selected_icon=ft.Icons.DASHBOARD, label="대시보드"),
            ft.NavigationRailDestination(icon=ft.Icons.SEARCH_ROUNDED, selected_icon=ft.Icons.SEARCH, label="통합조회"),
            ft.NavigationRailDestination(icon=ft.Icons.EDIT_CALENDAR_ROUNDED, selected_icon=ft.Icons.EDIT_CALENDAR, label="할당등록"),
            ft.NavigationRailDestination(icon=ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, selected_icon=ft.Icons.CHECK_CIRCLE, label="개통등록"),
            ft.NavigationRailDestination(icon=ft.Icons.TASK_ALT_ROUNDED, selected_icon=ft.Icons.TASK_ALT, label="접수완료"),
            ft.NavigationRailDestination(icon=ft.Icons.NOTIFICATIONS_NONE, selected_icon=ft.Icons.NOTIFICATIONS, label="알림센터"),
            # [추가됨] 요금계산기 아이콘 (7번째 메뉴, index=6)
            ft.NavigationRailDestination(icon=ft.Icons.CALCULATE_OUTLINED, selected_icon=ft.Icons.CALCULATE, label="요금계산기"),
            ft.NavigationRailDestination(icon=ft.Icons.CALENDAR_TODAY_OUTLINED, selected_icon=ft.Icons.CALENDAR_TODAY, label="할 일"), # Index 7 (요금계산기 다음)
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="설정"), # Index 8
        ],
        
        on_change=lambda e: update_tab(e.control.selected_index),
        bgcolor=Colors.BG_SIDEBAR,
        indicator_color=Colors.PRIMARY_LIGHT,
        indicator_shape=ft.RoundedRectangleBorder(radius=8),
    )

    # [상태 저장용 변수] 현재 보고 있는 탭 번호를 기억함 (기본값: 0번 대시보드)
    current_view_index = [0] 

    def update_tab(idx):
        # ----------------------------------------------------
        # [핵심] 6번(요금계산기) 클릭 시 -> 링크만 열고 끝냄
        # ----------------------------------------------------
        if idx == 6:
            try:
                webbrowser.open("https://kimkkoongkkoong-beep.github.io/SKB/", new=2)
            except Exception as e:
                print(f"링크 오류: {e}")
            
            # [중요] 화면이 바뀌지 않도록, 사이드바 선택을 '원래 보던 것'으로 되돌림
            rail.selected_index = current_view_index[0]
            page.update()
            return  # 함수 즉시 종료 (화면 전환 안 함)

        # ----------------------------------------------------
        # 나머지 메뉴 클릭 시 -> 정상적으로 화면 전환
        # ----------------------------------------------------
        current_view_index[0] = idx  # 현재 보는 탭 번호 저장
        
        dashboard_view.visible = (idx == 0)
        tab_search.visible = (idx == 1)
        tab_assign.visible = (idx == 2)
        tab_opening.visible = (idx == 3)
        tab_complete.visible = (idx == 4)
        tab_notification.visible = (idx == 5)
        # idx == 6 (계산기)은 위에서 처리됨
        tab_todo.visible = (idx == 7)
        
        # [핵심 수정] 설정 탭(8번) 연결 코드 추가!
        tab_settings.visible = (idx == 8) 

        # [추가] 스케줄 탭을 열 때 자동으로 데이터 불러오기
        if idx == 7:
            render_todos()
        
        page.update()
        

    # Layout Assembly (화면 조립)
    main_layout = ft.Row(
        [
            rail,
            ft.VerticalDivider(width=1, color=Colors.BORDER),
            ft.Container(
                content=ft.Stack([
                    dashboard_view,   # 0
                    tab_search,       # 1
                    tab_assign,       # 2
                    tab_opening,      # 3
                    tab_complete,     # 4
                    tab_notification, # 5
                    
                    tab_calculator,   # 6 (실제론 안 보임)
                    tab_todo,         # 7
                    
                    # [핵심 수정] 여기에 tab_settings를 꼭 추가해야 합니다!
                    tab_settings      # 8
                    
                ], expand=True), 
                expand=True, 
                bgcolor=Colors.BG_MAIN
            )
        ],
        expand=True
    )

    # [수정] Header Logo (QnA 버튼 추가됨)
    # ------------------------------------
    # QnA 버튼 정의
    btn_qna = ft.IconButton(
        icon=ft.Icons.QUESTION_ANSWER_OUTLINED, 
        tooltip="QnA 게시판", 
        icon_color=Colors.PRIMARY,
        on_click=open_qna_board # 위에서 만든 함수 연결
    )

    header_logo = ft.WindowDragArea(
        content=ft.Container(
            content=ft.Row([
                # 로고
                ft.Image(src="/logo.png", height=40, fit="contain"),
                
                # 빈 공간
                ft.Container(expand=True),
                
                # 뽀모도로 타이머
                container_pomo,
                
                ft.Container(width=10),
                
                # [추가됨] QnA 버튼
                btn_qna, 
                
                ft.Container(width=5), # 간격

                # 알림 센터 아이콘
                btn_bell_stack
            ], alignment=ft.MainAxisAlignment.START, vertical_alignment="center"),
            
            padding=ft.padding.only(left=20, top=10, right=20, bottom=10),
            bgcolor="white"
        )
    )

    # Main structure update to include header
    main_column = ft.Column([
        header_logo,
        ft.Divider(height=1, color=Colors.BORDER),
        main_layout
    ], expand=True)

    # [수정] Login View (정렬 호환성 패치)
    login_card = ft.Container(
        content=ft.Column([
            ft.Image(src="/logo.png", height=80, fit="contain"),
            
            ft.Text("Login to continue", size=14, color=Colors.TEXT_SUB),
            
            ft.Container(height=20),
            tf_id, 
            tf_pw,
            
            # [핵심 수정] alignment=ft.alignment.center_left 대신 ft.Alignment(-1, 0) 사용
            # (-1, 0)은 왼쪽 중앙을 의미합니다. 이 방식은 에러가 나지 않습니다.
            ft.Container(
                content=chk_save_pw, 
                width=300, 
                alignment=ft.Alignment(-1, 0)
            ),
            
            ft.Container(height=10),
            btn_login, 
            prog_login
        ], horizontal_alignment="center", spacing=10),
        padding=50, bgcolor="white", border_radius=20,
        shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.with_opacity(0.1, Colors.PRIMARY))
    )
    
    page.add(ft.Container(content=login_card, alignment=ft.Alignment(0,0), expand=True))

    # Helper function to switch from Login to Main
    # Since we are using page.clean() in login success, we need to add main_column
    # The original logic used `page.add(main_layout)`, now we use `main_column`
    
    # We need to redefine on_login_click to use main_column because main_layout is just the body
    def on_login_click_override(e):
        btn_login.disabled = True; prog_login.visible = True; page.update()
        
        if engine.login(tf_id.value, tf_pw.value):
            
            # ---------------------------------------------------------
            # [수정] 로그인 성공 시 정보 저장/삭제 (JSON 방식)
            # ---------------------------------------------------------
            CONFIG_FILE = "login_info.json"
            
            if chk_save_pw.value:
                # 파일에 ID/PW 저장
                try:
                    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump({"id": tf_id.value, "pw": tf_pw.value}, f)
                except Exception as ex:
                    print(f"Save Error: {ex}")
            else:
                # 체크 해제 시 파일 삭제
                if os.path.exists(CONFIG_FILE):
                    try: os.remove(CONFIG_FILE)
                    except: pass
            # ---------------------------------------------------------

            page.clean()
            page.add(main_column)
            page.pubsub.send_all({'topic': 'log_search', 'payload': {'msg': "로그인 성공", 'color': Colors.SUCCESS}})
            threading.Thread(target=_background_loops, daemon=True).start()
            
            # [중요] 타이머 쓰레드 시작
            start_pomo_thread()
            
            run_all_dashboards()
        else:
            page.snack_bar = ft.SnackBar(ft.Text("로그인 실패"), bgcolor=Colors.ERROR); page.snack_bar.open=True; btn_login.disabled = False
        
        prog_login.visible = False; page.update()
    
    # Re-assign the click handler
    btn_login.on_click = on_login_click_override

    # [!!!!!!!! 핵심 !!!!!!!!] 
    # UI가 모두 정의된 후, 타이머 쓰레드를 여기서 시작합니다.
    start_pomo_thread()

if __name__ == "__main__":
    # [수정] assets_dir="assets" 추가 (이미지 폴더 연결)
    ft.app(target=main, assets_dir="assets")