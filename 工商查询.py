# -*- coding: utf-8 -*-
"""工商查询：经 OpenCLI 在 Edge 页面上下文直连中注协知识库，取企业、详情、股东。

改编自 nigo/nigo-skills 的 cicpa-company-query（MIT，作者 nigo）与
jackwener/OpenCLI（Apache-2.0），本地精简改造：只保留"搜索→详情→股东"
最短链路，去掉批量导出、文件上传、缓存与配额队列。许可证与来源见 NOTICE。

只读查询，不改任何本地数据；凭据不进程序，登录态由 Edge 浏览器自带。
"""
import base64
import json as jsonlib
import os
import random
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

注协域名 = "zsk-cmis.cicpa.org.cn"
注协基址 = "https://" + 注协域名
浏览器会话名 = "name-matching"


class 工商查询错误(RuntimeError):
    """工商查询失败（通道不通、未登录、返回异常等），消息为中文。"""


def 域名守卫(地址):
    """取数请求只允许发往注协知识库域名。"""
    if not 地址.startswith(注协基址 + "/") and 地址 != 注协基址:
        raise 工商查询错误("取数请求只允许发往注协知识库域名：" + 注协域名)
    return 地址


def 定位命令行工具(查找=shutil.which):
    found = 查找("opencli")
    if not found:
        raise 工商查询错误(
            "未找到 opencli 命令。请先安装 OpenCLI 命令行工具"
            "（npm install -g @jackwener/opencli），并在 Edge 中启用 OpenCLI 扩展，这是一次性动作。"
        )
    return found


def 构造命令行(cli路径):
    """Windows 下 .cmd 包装会吞掉参数里的 & 和超长内容，改用 node 直接执行入口脚本。"""
    if os.name == "nt" and cli路径.lower().endswith((".cmd", ".bat")):
        入口 = (Path(cli路径).resolve().parent / "node_modules" / "@jackwener"
              / "opencli" / "dist" / "src" / "main.js")
        node = os.environ.get("RPI_OPENCLI_NODE") or shutil.which("node")
        if node and 入口.is_file():
            return [node, str(入口)]
    return [cli路径]


def 解析连接配置(输出):
    配置们 = []
    for 行 in str(输出).splitlines():
        文本 = 行.strip()
        if "— connected" in 文本 or "- connected" in 文本:
            名称 = 文本.split("—")[0].split("- connected")[0].strip()
            if 名称 and " " not in 名称:
                配置们.append(名称)
    return 配置们


class 网页通道:
    """把请求编译进 Edge 页面上下文发送，浏览器自动携带注协登录态。"""

    def __init__(self, 配置=None, 执行器=None, 命令行路径=None):
        self.配置 = 配置
        self._执行器 = 执行器 or self._默认执行
        self._命令行路径 = 命令行路径
        self._已定配置 = None

    @staticmethod
    def _默认执行(参数, 超时=None):
        try:
            return subprocess.run(参数, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=超时)
        except subprocess.TimeoutExpired as exc:
            raise 工商查询错误("opencli 调用超时") from exc

    @property
    def 命令行(self):
        if self._命令行路径 is None:
            self._命令行路径 = 定位命令行工具()
        return self._命令行路径

    def _连接配置(self):
        if self._已定配置:
            return self._已定配置
        if self.配置:
            self._已定配置 = self.配置
            return self._已定配置
        输出 = self._运行(["profile", "list"], 超时=30).stdout
        配置们 = 解析连接配置(输出 or "")
        if not 配置们:
            raise 工商查询错误("OpenCLI 扩展未连接。请确认 Edge 已打开且 OpenCLI 扩展已启用。")
        if len(配置们) > 1:
            raise 工商查询错误("检测到多个 OpenCLI 连接配置（{}），请把环境变量 RPI_OPENCLI_PROFILE 设为其中一个。"
                          .format("、".join(配置们)))
        self._已定配置 = 配置们[0]
        return self._已定配置

    def _运行(self, 参数, 超时=None):
        return self._执行器([*构造命令行(self.命令行), *参数], 超时=超时)

    def _求值(self, 脚本, 超时=60.0):
        结果 = self._运行(["--profile", self._连接配置(), "browser", 浏览器会话名, "eval", 脚本], 超时=超时)
        if getattr(结果, "returncode", 0) != 0:
            raise 工商查询错误("opencli 调用失败：" + (getattr(结果, "stderr", "") or ""))
        文本 = (结果.stdout or "").strip()
        if 文本.startswith('"') and 文本.endswith('"'):
            try:
                return jsonlib.loads(文本)
            except jsonlib.JSONDecodeError:
                return 文本
        return 文本

    def 打开页面(self, 地址):
        self._运行(["--profile", self._连接配置(), "browser", 浏览器会话名, "open", 地址], 超时=60.0)

    def 当前地址(self):
        结果 = self._运行(["--profile", self._连接配置(), "browser", 浏览器会话名, "get", "url"], 超时=30.0)
        return str(结果.stdout or "").strip()

    def 验证登录(self):
        try:
            结果 = self._求值(
                "(async()=>{try{const r=await fetch('/open/industry_chain_api/v1/search/get_user_index',"
                "{credentials:'include'});return await r.text();}catch(e){return 'ERR '+e.message;}})()"
            )
            return jsonlib.loads(结果).get("status_code") == 0
        except (jsonlib.JSONDecodeError, 工商查询错误):
            return False

    def 等待登录(self, 超时=600.0, 间隔=5.0):
        if not self.当前地址().startswith(注协基址):
            self.打开页面(注协基址 + "/#/home_local")
        起点 = time.monotonic()
        while time.monotonic() - 起点 < 超时:
            if self.验证登录():
                return
            time.sleep(间隔)
        raise 工商查询错误("登录等待超时：请在 Edge 里的注协页面完成登录后重试。")

    def 请求(self, 方法, 路径, 参数=None, 正文=None, 超时=60, _导航重试=0):
        地址 = 域名守卫(注协基址 + 路径 + ("?" + urlencode(参数) if 参数 else ""))
        相对路径 = 地址[len(注协基址):]
        正文脚本 = "undefined"
        类型头 = ""
        if 正文 is not None:
            正文脚本 = "JSON.stringify(" + jsonlib.dumps(正文, ensure_ascii=False) + ")"
            类型头 = ',"Content-Type":"application/json"'
        脚本 = (
            "(async()=>{if(location.hostname!=='" + 注协域名 + "')return JSON.stringify({nav:true});"
            "const m=document.cookie.match(/XSRF-TOKEN=([^;]+)/);"
            "const h={'X-XSRF-TOKEN':(m?m[1]:'')" + 类型头 + "};"
            "try{const r=await fetch('" + 相对路径 + "',{method:'" + 方法.upper() + "',credentials:'include',"
            "headers:h,body:" + 正文脚本 + "});"
            "const b=new Uint8Array(await r.arrayBuffer());let t='';"
            "for(let i=0;i<b.length;i+=32768)t+=String.fromCharCode.apply(null,b.subarray(i,i+32768));"
            "return JSON.stringify({s:r.status,b:btoa(t)});"
            "}catch(e){return JSON.stringify({s:0,b:'',e:String(e)});}})()"
        )
        输出 = self._求值(脚本, 超时=max(超时, 60.0))
        try:
            负载 = jsonlib.loads(输出)
        except jsonlib.JSONDecodeError as exc:
            raise 工商查询错误("页面取数返回内容无法解析") from exc
        if 负载.get("nav"):
            if _导航重试 >= 2:
                raise 工商查询错误("页面连续偏离注协域名，重开 2 次仍未恢复")
            self.打开页面(注协基址 + "/#/home_local")
            return self.请求(方法, 路径, 参数, 正文, 超时, _导航重试 + 1)
        if 负载.get("s") in (0, None):
            raise 工商查询错误("取数失败：" + str(负载.get("e") or "未知错误"))
        内容 = base64.b64decode(负载.get("b") or "")
        try:
            return jsonlib.loads(内容.decode("utf-8"))
        except (UnicodeDecodeError, jsonlib.JSONDecodeError) as exc:
            raise 工商查询错误("接口返回的不是有效内容") from exc


class 工商查询客户端:
    """最短链路：查企业 → 查详情 → 查股东。"""

    def __init__(self, 通道=None, 限速秒=2.5):
        self.通道 = 通道 or 网页通道()
        self.限速秒 = 限速秒

    def _取数(self, 方法, 路径, 参数=None, 正文=None):
        if self.限速秒:
            time.sleep(random.uniform(self.限速秒 * 0.8, self.限速秒 * 1.6))
        负载 = self.通道.请求(方法, 路径, 参数, 正文)
        if not isinstance(负载, dict):
            raise 工商查询错误("接口返回结构无效")
        if 负载.get("status_code") != 0:
            raise 工商查询错误("查询失败：" + str(负载.get("status_msg") or 负载.get("msg") or "未知业务错误"))
        return 负载.get("data") or {}

    def 查企业(self, 名称):
        """按名称搜索，返回 [{名称, 企业标识, 法定代表人}]。"""
        if not str(名称).strip():
            raise 工商查询错误("企业名称不能为空")
        数据 = self._取数("POST", "/open/industry_chain_api/v1/search/home_search",
                       正文={"condition": [], "query": str(名称).strip(), "from": 0, "page": 1,
                             "page_size": 10, "size": 10, "type": "company", "ranges": []})
        条目 = 数据.get("list") or 数据.get("searchResultList") or 数据.get("items") or []
        结果 = []
        for 项 in 条目:
            if not isinstance(项, dict):
                continue
            名字 = 项.get("name") or 项.get("entName") or ""
            if 名字:
                结果.append({"名称": 名字,
                             "企业标识": 项.get("org_id") or 项.get("orgId") or 项.get("orgid") or "",
                             "法定代表人": 项.get("legal_person") or 项.get("legalRepresentative") or ""})
        return 结果

    def 查详情(self, 企业标识):
        """查登记详情（真实全名、信用代码、法定代表人、登记状态、注册地址、成立日期）。"""
        数据 = self._取数("GET", "/open/enterprise_info_api/v3/find_company_basic_info",
                       参数={"orgid": 企业标识})
        return {"名称": 数据.get("name"),
                "信用代码": 数据.get("unified_social_credit_code"),
                "法定代表人": 数据.get("legal_representative"),
                "登记状态": 数据.get("operating_status"),
                "注册地址": 数据.get("corp_address"),
                "成立日期": 数据.get("established_date")}

    def 查股东(self, 企业标识):
        """查最新公示股东，返回 [{股东, 持股比例}]。"""
        数据 = self._取数("GET", "/open/enterprise_info_api/v4/stock_holder_newest",
                       参数={"orgid": 企业标识, "page": 1, "pagesize": 50, "pageSize": 50})
        结果 = []
        for 项 in 数据.get("list") or []:
            if isinstance(项, dict) and 项.get("holder_name"):
                结果.append({"股东": 项.get("holder_name"), "持股比例": 项.get("held_ratio")})
        return 结果

    def 一次查全(self, 名称):
        """查企业 + 首个匹配的详情与股东，供归一判定用。"""
        匹配 = self.查企业(名称)
        if not 匹配:
            return {"查询名称": 名称, "匹配列表": [], "详情": {}, "股东": []}
        目标 = next((项 for 项 in 匹配 if 项["名称"] == 名称), 匹配[0])
        return {"查询名称": 名称, "匹配列表": 匹配,
                "详情": self.查详情(目标["企业标识"]),
                "股东": self.查股东(目标["企业标识"])}
