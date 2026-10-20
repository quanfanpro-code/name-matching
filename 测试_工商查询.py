# -*- coding: utf-8 -*-
"""工商查询的测试：全部走假通道，不联网。"""
import unittest

from 工商查询 import 工商查询客户端, 工商查询错误, 域名守卫


class 假通道:
    """按路径返回预置返回值的假取数通道。"""

    def __init__(self, 返回表):
        self.返回表 = 返回表
        self.请求记录 = []

    def 请求(self, 方法, 路径, 参数=None, 正文=None, 超时=60):
        self.请求记录.append((方法, 路径, 参数, 正文))
        for 片段, 返回 in self.返回表.items():
            if 片段 in 路径:
                return 返回
        raise 工商查询错误("假通道没有为这个路径准备数据：" + 路径)


def 搜索返回(名称, org_id, 法人):
    return {"status_code": 0, "data": {"list": [
        {"org_id": org_id, "name": 名称, "legal_person": 法人, "credit_code": "", "status": ""}]}}


def 详情返回(名称):
    return {"status_code": 0, "data": {
        "name": 名称, "unified_social_credit_code": "91510116MACGT7414B",
        "legal_representative": "焦绘民", "operating_status": "存续",
        "corp_address": "浙江省嘉兴市海宁市", "established_date": "2021-08-03"}}


def 股东返回():
    return {"status_code": 0, "data": {"total": 1, "list": [
        {"holder_name": "上海语荻光电有限公司", "held_ratio": "100.0"}]}}


class 测试工商查询(unittest.TestCase):
    def test_查企业返回匹配列表(self):
        通道 = 假通道({"home_search": 搜索返回("海宁绘志光电有限公司", "Q11FF5CB88", "焦绘民")})
        客户端 = 工商查询客户端(通道=通道, 限速秒=0)
        结果 = 客户端.查企业("绘志光电")
        self.assertEqual(结果[0]["名称"], "海宁绘志光电有限公司")
        self.assertEqual(结果[0]["企业标识"], "Q11FF5CB88")
        self.assertEqual(结果[0]["法定代表人"], "焦绘民")

    def test_查详情给出真实全名(self):
        通道 = 假通道({"find_company_basic_info": 详情返回("海宁绘志光电有限公司")})
        客户端 = 工商查询客户端(通道=通道, 限速秒=0)
        详情 = 客户端.查详情("Q11FF5CB88")
        self.assertEqual(详情["名称"], "海宁绘志光电有限公司")
        self.assertEqual(详情["信用代码"], "91510116MACGT7414B")
        self.assertEqual(详情["法定代表人"], "焦绘民")
        self.assertEqual(详情["登记状态"], "存续")

    def test_查股东(self):
        通道 = 假通道({"stock_holder_newest": 股东返回()})
        客户端 = 工商查询客户端(通道=通道, 限速秒=0)
        股东 = 客户端.查股东("Q11FF5CB88")
        self.assertEqual(股东, [{"股东": "上海语荻光电有限公司", "持股比例": "100.0"}])

    def test_业务错误给中文提示(self):
        通道 = 假通道({"home_search": {"status_code": 1001, "status_msg": "查询过于频繁"}})
        客户端 = 工商查询客户端(通道=通道, 限速秒=0)
        with self.assertRaises(工商查询错误) as 上下文:
            客户端.查企业("任何名字")
        self.assertIn("查询过于频繁", str(上下文.exception))

    def test_域名守卫拒绝非注协地址(self):
        with self.assertRaises(工商查询错误) as 上下文:
            域名守卫("https://example.com/api")
        self.assertIn("注协", str(上下文.exception))


if __name__ == "__main__":
    unittest.main()
