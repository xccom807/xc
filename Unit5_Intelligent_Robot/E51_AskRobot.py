# Excecise/E51_AskRobot.py
# 1  调用模块
import AIServiceV3 as AIService

# 2 根据AK，SK 生成 access_token ，并附上自己的 机器人技能ID 88833
AK     = 
SK     = 
access_token  = AIService.get_baidu_access_token(AK, SK)

#  service_id为S开头的机器人ID
#  skill_ids 为你的bot_id ,
# 另：skill_ids=['88833','1634268']可列表
# 另：百度停用Unit文档问答，后续可用AppBuilder智能体来替代
service_id='S23833'  #  机器人ID， S开头
service_id='S23833'  #  机器人ID， S开头

#skill_ids=['88833']  # 原 bot_id

# 3 准备问题 预置百科问题   中国面积有多大  珠穆朗玛峰有多高？　王小明的职业？　帕萨特的价格多少？
AskText =  "王小明的职业？"
AskText =  "中国面积有多大？"

# 4调用机器人应答接口
Answer = AIService.Answer(access_token, service_id, AskText)

# 5 输出问答
print("问：" + AskText)
print("答：" + Answer)
