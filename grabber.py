import time
import logging
import requests
import threading


class Grabber:
    def __init__(self):
        self.lock = threading.Lock()  # 预留，当前由调用方管理线程

    def _post_course(self, cookie, load):
        url = "http://xk1.cqupt.edu.cn/post.php"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": cookie,
            "Origin": "http://xk1.cqupt.edu.cn",
            "Referer": "http://xk1.cqupt.edu.cn/yxk.php",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
            "X-Requested-With": "XMLHttpRequest"
        }

        try:
            response = requests.post(url, data=load, headers=headers, timeout=10)
            if response.status_code != 200:
                logging.error(f"Bad StatusCode: {response.status_code}, body: {response.text}")
                return "Error"
            response_data = response.json()
            res = GrabResponse.from_dict(response_data)
            return res.info
        except (requests.RequestException, ValueError) as e:
            logging.error(f"POST 请求异常: {e}")
            return "Error"

    def grab_with_info(self, cookie, load):
        logging.info(self._post_course(cookie, load))

    def grab_loop(self, cookie, load, idx, mode=1, stop_event=None, max_attempts=0):
        '''mode\n1 - speed, 2 - slow, 3 - 捡漏, else - interval=mode
        stop_event: threading.Event to signal stop
        max_attempts: 0 = unlimited, >0 = max retries'''
        attempt = 1
        interval = 0.25
        if mode == 2:
            interval = 5
        elif mode == 3:
            interval = 100
        elif mode != 1:
            interval = mode
        logging.info(f"Course {idx} started")
        while True:
            if stop_event and stop_event.is_set():
                logging.info(f"Course {idx} stopped by user")
                return
            if max_attempts > 0 and attempt > max_attempts:
                logging.info(f"Course {idx} reached max attempts ({max_attempts})")
                return
            info = self._post_course(cookie, load)
            if info == "ok":  # 教务系统选课成功的返回标识
                logging.info(f"\033[31mCourse {idx} 抢课成功\033[0m")
                return
            else:
                logging.info(f"Attempt {idx}-{attempt}: {info}")
            time.sleep(interval)
            attempt += 1

    def _grab_worker(self, cookie, load, idx, stop_event=None):
        logging.info(f"Thread {idx + 1} started")
        while True:
            if stop_event and stop_event.is_set():
                return
            info = self._post_course(cookie, load)
            if info == "ok":  # 教务系统选课成功的返回标识
                logging.info(info)
                return
            else:
                logging.info(f"Course {idx + 1}: {info}")
            time.sleep(0.25)

    def grab_concurrent(self, cookie, loads, stop_event=None):
        threads = []
        for idx, load in enumerate(loads):
            thread = threading.Thread(target=self._grab_worker, args=(cookie, load, idx, stop_event))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        logging.info("\033[31m抢课成功\033[0m")

class GrabResponse:
    def __init__(self, code, info):
        self.code = code
        self.info = info

    @classmethod
    def from_dict(cls, data):
        return cls(code=data.get("code"), info=data.get("info"))
