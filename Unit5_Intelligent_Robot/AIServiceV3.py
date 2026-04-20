import requests
import base64
import json


def get_baidu_access_token(AK,SK):
    # client_id 为官网获取的AK， client_secret 为官网获取的SK
    url='https://openapi.baidu.com/oauth/2.0/token?grant_type=client_credentials&client_id={}&client_secret={}'.format(AK,SK)
    response=requests.get(url)
    access_token = response.json()['access_token']
    # print(access_token)
    return access_token


#def Answer(access_token, service_id,skill_ids, Ask):
def Answer(access_token, service_id, Ask):

    # Updated URL for v3 API
    url = 'https://aip.baidubce.com/rpc/2.0/unit/service/v3/chat?access_token=' + access_token

    # Updated request format for v3 API
    post_data = {
        "version": "3.0",
        "service_id": service_id,
#        "skill_ids": skill_ids,
        "session_id": "",
        "log_id": "7758521",
        "request": {
            "terminal_id": "88888",
            "query": Ask
        }
    }
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, json=post_data, headers=headers)
    # print(response.json())
    return response.json()['result']['context']['SYS_PRESUMED_HIST'][1]


#def JsonAnswer(access_token, service_id,skill_ids, Ask):
def JsonAnswer(access_token, service_id, Ask):
    # Updated URL for v3 API
    url = 'https://aip.baidubce.com/rpc/2.0/unit/service/v3/chat?access_token=' + access_token

    # Updated request format for v3 API
    post_data = {
        "version": "3.0",
        "service_id": service_id,
#        "skill_ids": skill_ids,
        "session_id": "",
        "log_id": "7758521",
        "request": {
            "terminal_id": "88888",
            "query": Ask
        }
    }
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, json=post_data, headers=headers)
    return json.dumps(response.json(), ensure_ascii=False)


def useMyModel(access_token,ModelName,Img):
    Img = {'image': base64.b64encode(Img).decode()}
    request_url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/classification/{}?access_token={}".format(ModelName,access_token)
    response = requests.post(request_url, data=json.dumps(Img))
    content = response.json()
    return content


# Excecise/ AIServiceV3.py
# 在文件 AIServiceV3.py中定义Student类
class Student():
    def __init__(self,id,name ):   	# __init__()方法相当于构造函数，在这里用于定义形参
        self.id = id;      			# 初始化学生对象的学号为传入的id
        self.name = name;      		# 初始化学生对象的名称为传入的name
        self.result = {
          'words_result': [
             {'words': '您好'},
             {'words': '人工智能'}
          ],
          'words_result_num': 2
        }

    def get_baidu_access_token(self,id,name):
        return id + name

    def speak(self,text):
        return self.name  + text

    def getResult(self,text):
        self.result['words_result'][0]['words'] = text
        return self.result



