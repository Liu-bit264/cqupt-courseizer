import requests
import logging
import time


class Queryer:
    def __init__(self):
        self.courses = []
        self.matched_courses = []

    def _fetch(self, query_str, cookie):
        # 添加错误处理和重试机制
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                url = f"http://xk1.cqupt.edu.cn/json-data-yxk.php?type={query_str}"
                
                headers = {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                    "Cache-Control": "max-age=0",
                    "Connection": "keep-alive",
                    "Cookie": cookie,
                    "Upgrade-Insecure-Requests": "1",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.54 Safari/537.36 Edg/101.0.1210.39"
                }

                logging.info(f"尝试请求: {url}")
                response = requests.get(url, headers=headers, timeout=10)  # 添加超时设置
                
                if response.status_code != 200:
                    logging.error(f"Bad StatusCode: {response.status_code}, body: {response.text}")
                    retry_count += 1
                    if retry_count < max_retries:
                        logging.info(f"重试请求 ({retry_count}/{max_retries})...")
                        time.sleep(1)  # 等待1秒后重试
                        continue
                    return None
                
                # 检查响应内容是否为空或非预期内容
                if not response.text or len(response.text) < 10:
                    logging.error(f"响应内容异常: {response.text}")
                    retry_count += 1
                    if retry_count < max_retries:
                        logging.info(f"重试请求 ({retry_count}/{max_retries})...")
                        time.sleep(1)
                        continue
                    return None
                
                try:
                    return response.json()
                except Exception as e:
                    logging.error(f"JSON解析失败: {e}, 响应内容: {response.text}")
                    retry_count += 1
                    if retry_count < max_retries:
                        logging.info(f"重试请求 ({retry_count}/{max_retries})...")
                        time.sleep(1)
                        continue
                    return None
                    
            except requests.exceptions.RequestException as e:
                logging.error(f"请求异常: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    logging.info(f"重试请求 ({retry_count}/{max_retries})...")
                    time.sleep(1)
                    continue
                return None
        
        return None

    def fetch_humanities(self, cookie):
        body_data = self._fetch("jctsRw", cookie)
        if body_data:
            class_info = CourseListResponse.from_dict(body_data)
            for item in class_info.data:
                load = self._build_post_data(item)
                # self.write2file("./output_renwen.txt", load)
                self._add_course(load)

    def fetch_sciences(self, cookie):
        body_data = self._fetch("jctsZr", cookie)
        if body_data:
            class_info = CourseListResponse.from_dict(body_data)
            for item in class_info.data:
                load = self._build_post_data(item)
                # self.write2file("./output_ziran.txt", load)
                self._add_course(load)

    def fetch_class_courses(self, cookie):
        body_data = self._fetch("bj", cookie)
        if body_data:
            class_info = CourseListResponse.from_dict(body_data)
            for item in class_info.data:
                load = self._build_post_data(item)
                # self.write2file("./output_banji.txt", load)
                self._add_course(load)

    def _build_post_data(self, item):
        # POST 参数名来自教务系统 API，与 Python 属性名不对齐是故意的（如 kchb→course_code, teaname→teacher 等）
        load_string = f"xnxq={item.semester}&jxb={item.class_id}&kchb={item.course_code}&kcmc={item.course_name}&xf={item.credits}&teaname={item.teacher}&rslimit={item.enrollment_limit}&kclb={item.kclb}&kchtye={item.kch_type}&memo={item.memo}"
        return load_string

    def write2file(self, file_path, content):
        with open(file_path, "a", encoding="utf-8") as file:
            file.write(content + "\n")

    def _add_course(self, content):
        self.courses.append(content)
    
    def filter_by_keywords(self, search_str_ls):
        for j in range(len(search_str_ls)):
            for i in self.courses:
                if search_str_ls[j] in i:
                    self.matched_courses.append(i)

class CourseListResponse:
    def __init__(self, code, info, data):
        self.code = code
        self.info = info
        self.data = data  # List of ClassInfoItem objects

    @classmethod
    def from_dict(cls, data):
        # Parsing the API response into a CourseListResponse object
        data_items = [ClassInfoItem.from_dict(item) for item in data['data']]
        return cls(code=data['code'], info=data['info'], data=data_items)


class ClassInfoItem:
    def __init__(self, semester, class_id, course_code, course_name, credits, teacher, enrollment_limit,
                 kclb,  # TODO: 确认字段含义，暂用拼音缩写
                 kch_type,  # TODO: 确认字段含义，暂用拼音缩写
                 memo):  # 备注
        self.semester = semester
        self.class_id = class_id
        self.course_code = course_code
        self.course_name = course_name
        self.credits = credits
        self.teacher = teacher
        self.enrollment_limit = enrollment_limit
        self.kclb = kclb
        self.kch_type = kch_type
        self.memo = memo

    @classmethod
    def from_dict(cls, item):
        return cls(
            semester=item['xnxq'],
            class_id=item['jxb'],
            course_code=item['kcbh'],
            course_name=item['kcmc'],
            credits=item['xf'],
            teacher=item['teaName'],
            enrollment_limit=item['rsLimit'],
            kclb=item['kclb'],
            kch_type=item['kchType'],
            memo=item['memo']
        )
