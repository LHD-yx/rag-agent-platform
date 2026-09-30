"""生成 200+ 篇演示语料（Markdown / Word / PDF 混合）。

为什么要混合格式：
    真实企业的文档库从来不是单一格式——手册有 PDF、规范有 Word、内部 wiki 是 Markdown。
    所以这里刻意产出三种格式，用来验证解析流水线（PyMuPDF / python-docx / 标题树）都能扛住。

内容组织（模拟真实文档库的目录结构）：
    data/raw/星澜产品文档/{系列}/{型号}/{文档类型}.{md|docx|pdf}
    data/raw/星澜通用文档/{文档类型}.md

用法：
    python scripts/gen_demo_corpus.py                 # 默认生成约 240 篇
    python scripts/gen_demo_corpus.py --target 300    # 指定总篇数上限
    python scripts/gen_demo_corpus.py --dry-run       # 只统计不写文件
    python scripts/gen_demo_corpus.py --clean         # 先删除本脚本生成过的目录再生成
"""
from __future__ import annotations

import argparse
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BRAND = "星澜"
COMPANY = "星澜智能科技有限公司"
SUPPORT = "400-826-1068"
DOC_VERSION = "V2.1"
RELEASE_DATE = "2026-04-10"
PRODUCT_ROOT = "星澜产品文档"
COMMON_ROOT = "星澜通用文档"

# ------------------------------------------------------------------ 产品体系
SERIES_DEF = {
    "X3": {
        "name": "星澜电视 X3 系列",
        "position": "旗舰 4K 智能电视",
        "sizes": [55, 65, 75, 85],
        "panel": "VA 直下式背光（多分区）",
        "refresh": "120Hz",
        "memory": "4GB + 64GB",
        "power": "220V~ 50Hz",
        "audio": "2×15W 全频 + 30W 低音",
    },
    "A5": {
        "name": "星澜电视 A5 系列",
        "position": "家用主流智能电视",
        "sizes": [32, 43, 50, 55, 65],
        "panel": "IPS / VA 直下式",
        "refresh": "60Hz",
        "memory": "2GB + 32GB",
        "power": "220V~ 50Hz",
        "audio": "2×10W 全频",
    },
    "C7": {
        "name": "星澜商用显示 C7 系列",
        "position": "商用显示与会议平板",
        "sizes": [55, 65, 75, 86],
        "panel": "工业级 VA 面板",
        "refresh": "60Hz",
        "memory": "4GB + 128GB",
        "power": "220V~ 50Hz",
        "audio": "2×12W 全频",
    },
    "P1": {
        "name": "星澜智能投影 P1 系列",
        "position": "便携式智能投影",
        "sizes": [0],
        "panel": "DLP 光机 + LED 光源",
        "refresh": "60Hz",
        "memory": "2GB + 32GB",
        "power": "19V ⎓ 3.42A（适配器）",
        "audio": "2×5W 全频",
    },
    "S": {
        "name": "星澜智能盒子 S 系列",
        "position": "4K 智能网络机顶盒",
        "sizes": [0],
        "panel": "—",
        "refresh": "60Hz",
        "memory": "2GB + 16GB",
        "power": "12V ⎓ 1.5A（适配器）",
        "audio": "—",
    },
    "SB": {
        "name": "星澜回音壁 SB 系列",
        "position": "家庭影院回音壁音响",
        "sizes": [0],
        "panel": "—",
        "refresh": "—",
        "memory": "—",
        "power": "100–240V~ 50/60Hz",
        "audio": "2.1 声道",
    },
}

P1_MODELS = ["P1-Air", "P1-Standard", "P1-Pro"]
S_MODELS = ["S1", "S1-Pro"]
SB_MODELS = ["SB-200", "SB-300", "SB-500"]

DOC_TYPES = [
    "技术规格书", "用户手册", "快速入门指南", "安装与调试指南", "维护保养手册",
    "常见问题", "包装与开箱清单", "能效与环保说明", "配件兼容清单",
]


def build_models() -> list[dict]:
    """展开成每个型号一份参数字典。"""
    models: list[dict] = []
    for series, cfg in SERIES_DEF.items():
        codes = P1_MODELS if series == "P1" else S_MODELS if series == "S" else SB_MODELS if series == "SB" else []
        if codes:
            for i, code in enumerate(codes):
                models.append({
                    "code": code, "series": series, "series_name": cfg["name"],
                    "position": cfg["position"],
                    "screen": "—" if series in {"S", "SB"} else f"最大投射 {80 + i * 40} 英寸",
                    "resolution": "3840×2160（4K）" if series != "S" else "3840×2160（4K 解码）",
                    "panel": cfg["panel"], "refresh": cfg["refresh"],
                    "memory": cfg["memory"], "power": cfg["power"],
                    "audio": cfg["audio"],
                    "tier": "标准版" if i == 0 else ("进阶版" if i == 1 else "旗舰版"),
                })
        else:
            for size in cfg["sizes"]:
                models.append({
                    "code": f"{series}-{size}", "series": series, "series_name": cfg["name"],
                    "position": cfg["position"], "screen": f"{size} 英寸",
                    "resolution": "3840×2160（4K）" if size >= 43 else "1920×1080（全高清）",
                    "panel": cfg["panel"], "refresh": cfg["refresh"],
                    "memory": cfg["memory"], "power": cfg["power"], "audio": cfg["audio"],
                    "tier": "旗舰版" if series == "X3" else "标准版",
                })
    return models


# ------------------------------------------------------------------ 渲染辅助
def H1(t): return ("h1", t)
def H2(t): return ("h2", t)
def H3(t): return ("h3", t)
def P(t): return ("p", t)
def LI(t): return ("li", t)
def TB(rows): return ("table", rows)
def QT(t): return ("quote", t)


def doc_header(no: str, title: str, models: str, blocks: list) -> list:
    return [
        H1(title),
        P(f"文档编号：{no}　｜　版本：{DOC_VERSION}　｜　更新日期：{RELEASE_DATE}"),
        P(f"适用型号：{models}　｜　发布单位：{COMPANY}"),
        *blocks,
        H2("附：联系与支持"),
        P(f"客服热线 {SUPPORT}（09:00–21:00）｜「星澜服务」App 可提交工单与查询进度。"),
    ]


# ------------------------------------------------------------------ 各类型文档
def doc_spec(m: dict, i: int) -> list:
    rows = [["项目", "参数"], ["产品型号", m["code"]], ["产品定位", m["position"]],
            ["屏幕/投射", m["screen"]], ["分辨率", m["resolution"]], ["面板/光源", m["panel"]],
            ["刷新率", m["refresh"]], ["内存", m["memory"]], ["音频", m["audio"]],
            ["电源", m["power"]], ["工作温度", "0℃~40℃"], ["存储温度", "-20℃~60℃"],
            ["整机功耗", f"{60 + i * 7}W（典型值）"], ["待机功耗", "≤0.5W"]]
    return doc_header(f"XL-SP-{m['code']}", f"{m['code']} 技术规格书", m["code"], [
        H2("一、基本参数"), TB(rows),
        H2("二、接口配置"),
        LI("HDMI 输入 × 3（支持 HDMI 2.1 与 eARC）"),
        LI("USB 3.0 × 1、USB 2.0 × 1"),
        LI("光纤音频输出 × 1、有线网口 × 1（10/100M）"),
        LI("天线输入 × 1、AV 输入 × 1"),
        H2("三、执行标准"),
        P("本产品符合 GB 8898《音频、视频及类似电子设备安全要求》与 GB 9254 电磁兼容标准。"),
        H2("四、注意事项"),
        LI("请使用原厂电源线与适配器。"),
        LI("避免与大功率电器共用插排。"),
        LI("搬运时请勿按压屏幕或光机镜头。"),
    ])


def doc_manual(m: dict, i: int) -> list:
    return doc_header(f"XL-MN-{m['code']}", f"{m['code']} 用户手册", m["code"], [
        H2("一、开箱清单"),
        LI(f"{m['code']} 主机 × 1"), LI("遥控器 × 1"), LI("电源线/适配器 × 1"),
        LI("底座或安装支架 × 1 套"), LI("快速入门指南 × 1"), LI("保修卡 × 1"),
        H2("二、安装与摆放"),
        H3("2.1 台面放置"),
        P("选择水平稳固的台面，机身四周预留 10cm 以上散热空间，避免阳光直射。"),
        H3("2.2 壁挂安装"),
        P(f"确认墙体为承重墙；{m['screen']} 机型建议预约免费上门安装服务，由工程师确认墙体承重与走线方案。"),
        H2("三、首次开机"),
        P(f"接入电源（{m['power']}）后按下电源键，首次开机约需 30 秒，请勿中途断电。"),
        LI("按提示选择语言与时区"),
        LI("连接无线网络（支持 2.4GHz / 5GHz）或插入网线"),
        LI("登录账号后可同步应用与观看记录"),
        H2("四、日常操作"),
        TB([["操作", "方法"],
            ["切换信号源", "按遥控器「信号源」键选择 HDMI 或内置应用"],
            ["调整画质", "设置 › 显示 › 画质模式（标准/电影/游戏/自定义）"],
            ["调整声音", "设置 › 声音 › 音效模式与音频输出"],
            ["语音控制", "长按遥控器语音键后说出指令"],
            ["投屏", "手机端选择「投屏」并连接同一网络"]]),
        H2("五、维护保养"),
        LI("屏幕使用干燥超细纤维布清洁，禁用酒精类溶剂。"),
        LI("每月检查散热孔积尘，可用软毛刷轻扫。"),
        LI("长期不用请拔掉电源并加防尘罩。"),
        H2("六、安全提示"),
        QT("请勿自行拆机，私自拆机会导致保修失效；雷雨天气建议拔掉电源与信号线。"),
    ])


def doc_quickstart(m: dict, i: int) -> list:
    return doc_header(f"XL-QS-{m['code']}", f"{m['code']} 快速入门指南", m["code"], [
        H2("三步开机"),
        H3("第一步：接电"),
        P(f"使用随机电源线连接机身与插座（{m['power']}），确认插座通电。"),
        H3("第二步：开机"),
        P("按下机身电源键或遥控器电源键，等待约 30 秒完成启动。"),
        H3("第三步：联网"),
        P("按屏幕提示选择 WiFi 并输入密码；也可直接插入网线自动联网。"),
        H2("常用快捷键"),
        TB([["按键", "功能"], ["信号源", "切换 HDMI / AV / 内置应用"],
            ["主页", "返回主界面"], ["返回", "返回上一级"],
            ["语音", "长按启动语音助手"]]),
        H2("遇到问题？"),
        LI(f"无法开机：检查电源线是否插紧，更换插座测试。"),
        LI(f"连不上网络：核对密码，重启路由器后重试。"),
        LI(f"以上无效请拨打 {SUPPORT} 申请上门服务。"),
    ])


def doc_install(m: dict, i: int) -> list:
    return doc_header(f"XL-IN-{m['code']}", f"{m['code']} 安装与调试指南", m["code"], [
        H2("一、安装环境确认"),
        LI("确认安装位置具备电源插座与信号接口。"),
        LI("避免阳光直射、潮湿与强磁场环境。"),
        LI("墙面安装需为承重墙，轻质隔墙请加装背板。"),
        H2("二、安装步骤"),
        H3("2.1 底座安装"),
        P("将主机平放在包装泡沫上，用 4 颗随机螺丝固定底座支架并拧紧。"),
        H3("2.2 壁挂安装"),
        P("按 VESA 孔位安装挂架，建议两人协作抬装，避免受力不均。"),
        H3("2.3 信号连接"),
        TB([["外设", "推荐接口", "说明"],
            ["机顶盒", "HDMI 1", "支持 4K 60Hz"],
            ["游戏主机", "HDMI 2", "建议开启游戏模式降低延迟"],
            ["回音壁", "HDMI eARC", "由回音壁解码杜比音轨"],
            ["U 盘", "USB 3.0", "支持 FAT32 / exFAT 格式"]]),
        H2("三、调试要点"),
        LI("开机后进入「画质向导」按房间光线选择模式。"),
        LI("使用网络测速确认带宽，4K 在线播放建议 ≥50Mbps。"),
        LI("首次使用建议执行一次系统升级。"),
        H2("四、验收检查"),
        TB([["检查项", "标准"], ["画面", "纯色画面无亮点、竖线"],
            ["声音", "左右声道均有输出"], ["网络", "WiFi 与有线均可连通"],
            ["遥控", "各按键响应正常"]]),
    ])


def doc_maintenance(m: dict, i: int) -> list:
    return doc_header(f"XL-MT-{m['code']}", f"{m['code']} 维护保养手册", m["code"], [
        H2("一、清洁规范"),
        LI("屏幕：断电后用干燥超细纤维布沿同一方向轻拭。"),
        LI("机身：软布蘸少量清水擦拭，避免液体流入散热孔。"),
        LI("禁止使用酒精、丙酮、含氨清洁剂。"),
        H2("二、散热与通风"),
        LI("机身四周预留 ≥10cm 空间，勿置于密闭柜体。"),
        LI("每季度清理一次散热孔积尘。"),
        H2("三、防潮防雷"),
        LI("梅雨季节建议每日开机运行 30 分钟驱潮。"),
        LI("雷雨天气拔掉电源与天线/网线。"),
        H2("四、长期存放"),
        LI("断电后待机身冷却，套上防尘罩置于干燥环境。"),
        LI("建议每 3 个月通电运行一次，保持电容活性。"),
        H2("五、耗材与更换周期"),
        TB([["部件", "建议周期", "说明"], ["遥控器电池", "6~12 个月", "两节 AAA 碱性电池"],
            ["防尘罩", "按需更换", "破损后及时更换"], ["投影光源（P1 系列）", "约 20000 小时", "亮度明显衰减时联系售后"]]),
    ])


def doc_faq(m: dict, i: int) -> list:
    return doc_header(f"XL-FQ-{m['code']}", f"{m['code']} 常见问题", m["code"], [
        H2("1. 首次开机需要注意什么？"),
        P("保持供电稳定，30 秒内不要断电；建议先完成系统升级再安装应用。"),
        H2("2. 找不到遥控器配对怎么办？"),
        P("同时长按「主页」+「返回」键 5 秒进入配对模式，靠近机身 1 米内等待提示。"),
        H2("3. 播放 4K 内容卡顿？"),
        P("确认带宽是否达到 50Mbps 以上，建议改用 5GHz WiFi 或网线连接。"),
        H2("4. 可以连接蓝牙耳机吗？"),
        P("支持，同一时间仅允许一路蓝牙音频输出；连接后电视扬声器会自动静音。"),
        H2("5. 如何恢复出厂设置？"),
        P("进入 设置 › 系统 › 恢复出厂设置，操作前请备份账号信息，过程约需 3 分钟。"),
        H2("6. 保修期内屏幕出现亮线怎么处理？"),
        P(f"拍照记录后拨打 {SUPPORT} 申请检测，属于质量问题可免费更换屏幕模组。"),
    ])


def doc_package(m: dict, i: int) -> list:
    return doc_header(f"XL-PK-{m['code']}", f"{m['code']} 包装与开箱清单", m["code"], [
        H2("一、包装清单"),
        TB([["序号", "物品", "数量"], ["1", f"{m['code']} 主机", "1"],
            ["2", "遥控器", "1"], ["3", "电源线 / 适配器", "1"],
            ["4", "底座组件", "1 套"], ["5", "快速入门指南", "1"],
            ["6", "保修卡", "1"]]),
        H2("二、开箱检查"),
        LI("检查外包装是否有明显破损或进水痕迹。"),
        LI("核对机身序列号与保修卡一致。"),
        LI("通电确认能正常开机后再拆除保护膜。"),
        H2("三、包装回收"),
        P("纸箱与缓冲泡沫可回收，请按当地垃圾分类要求投放。"),
        H2("四、异常处理"),
        P(f"若发现配件缺失或外观破损，请在签收后 48 小时内联系 {SUPPORT} 处理。"),
    ])


def doc_energy(m: dict, i: int) -> list:
    return doc_header(f"XL-EN-{m['code']}", f"{m['code']} 能效与环保说明", m["code"], [
        H2("一、能效信息"),
        TB([["项目", "数值"], ["能效等级", "二级" if m["series"] != "X3" else "一级"],
            ["典型功耗", f"{60 + i * 7}W"], ["待机功耗", "≤0.5W"],
            ["年耗电量（按每天 4 小时估算）", f"{int((60 + i * 7) * 4 * 365 / 1000)} kWh"]]),
        H2("二、节能建议"),
        LI("开启「自动亮度」按环境光调节背光。"),
        LI("长时间不看请关机或使用「节能模式」。"),
        LI("启用「无操作自动待机」可减少待机耗电。"),
        H2("三、环保与回收"),
        P("本产品符合《电器电子产品有害物质限制使用管理办法》要求，"
          "废弃时请交由具备资质的回收机构处理，勿随生活垃圾丢弃。"),
        H2("四、RoHS 声明"),
        P("产品所含有害物质均低于限量要求，详见随机环保声明卡。"),
    ])


def doc_accessories(m: dict, i: int) -> list:
    return doc_header(f"XL-AC-{m['code']}", f"{m['code']} 配件兼容清单", m["code"], [
        H2("一、推荐配件"),
        TB([["配件", "型号", "说明"],
            ["无线遥控器", "RC-20", "蓝牙+红外双模，支持语音"],
            ["回音壁", "SB-300", "HDMI eARC 连接，2.1 声道"],
            ["壁挂支架", "WM-400", "适配 55~75 英寸，承重 60kg"],
            ["智能盒子", "S1", "老款设备升级智能系统"]]),
        H2("二、连接说明"),
        LI("回音壁优先使用 HDMI eARC 接口，可获得无损音轨。"),
        LI("蓝牙配件首次连接需进入配对模式。"),
        LI("U 盘建议使用 FAT32 或 exFAT 格式。"),
        H2("三、兼容性提示"),
        QT("第三方配件可能存在协议差异；若出现无法识别，请先用官方配件交叉验证。"),
    ])


MODEL_DOC_BUILDERS = {
    "技术规格书": doc_spec,
    "用户手册": doc_manual,
    "快速入门指南": doc_quickstart,
    "安装与调试指南": doc_install,
    "维护保养手册": doc_maintenance,
    "常见问题": doc_faq,
    "包装与开箱清单": doc_package,
    "能效与环保说明": doc_energy,
    "配件兼容清单": doc_accessories,
}


# ------------------------------------------------------------------ 通用文档
FAULT_CASES = [
    ("无法开机", ["指示灯不亮", "遥控器开机无反应"], [
        ("检查电源连接", "确认电源线牢固插入机身与插座，插座开关处于开启状态。"),
        ("更换插座测试", "换一个已验证通电的插座，排除插座问题。"),
        ("更换遥控器电池", "更换两节全新 AAA 电池后靠近机身重试。"),
        ("观察指示灯", "不亮多为供电问题；亮起但黑屏多为主板或背光问题。")]),
    ("画面花屏或闪烁", ["彩色噪点", "间歇黑屏", "横向条纹"], [
        ("切换信号源", "改用内置应用播放，若正常则问题在外接设备或线材。"),
        ("更换 HDMI 线", "使用符合 HDMI 2.1 规范且长度 ≤3 米的线材。"),
        ("降低刷新率", "由 120Hz 改为 60Hz 观察是否恢复。"),
        ("检查供电环境", "避免与大功率电器共用插排。")]),
    ("电视无声音", ["画面正常无声音", "声音断续", "单侧无声"], [
        ("确认静音状态", "按音量键确认未处于静音。"),
        ("检查音频输出", "设置 › 声音 › 音频输出，选择「电视扬声器」。"),
        ("检查外接设备", "将外设音频格式改为 PCM 后重试。"),
        ("断电重启", "断电 30 秒后重新上电。")]),
    ("无法连接无线网络", ["搜不到 WiFi", "密码正确仍失败", "已连接无法上网"], [
        ("确认频段与 SSID", "支持 2.4GHz/5GHz；隐藏网络需手动添加。"),
        ("核对密码", "注意大小写与特殊字符。"),
        ("重启路由器", "断电 30 秒后重启，等待 2 分钟再连接。"),
        ("检查路由器限制", "确认未开启 MAC 白名单或设备数上限。")]),
    ("遥控器失灵", ["按键无反应", "需贴近才有效", "语音无法唤醒"], [
        ("更换电池", "使用全新 AAA 电池并注意正负极。"),
        ("重新配对", "长按「主页」+「返回」5 秒进入配对。"),
        ("排除遮挡", "清理红外接收窗前遮挡物。"),
        ("摄像头自检", "用手机摄像头对准红外发射头，按键无紫光说明已损坏。")]),
    ("HDMI 无信号", ["提示无信号", "电脑无画面", "画面闪断"], [
        ("确认输入源", "按「信号源」选择与实际接入一致的通道。"),
        ("重插线材", "拔插两端并确认插到底。"),
        ("交叉验证", "更换端口或线材测试。"),
        ("降低输出规格", "将分辨率降至 1080P、刷新率 60Hz 再试。")]),
    ("系统卡顿或自动重启", ["菜单延迟", "应用无响应", "开机后自动重启"], [
        ("清理后台", "关闭不使用的应用释放内存。"),
        ("清理存储", "保证可用空间大于 2GB。"),
        ("恢复出厂设置", "设置 › 系统 › 恢复出厂设置。"),
        ("检查供电", "电压不稳会导致重启，建议使用独立插座。")]),
    ("固件升级失败", ["进度卡住", "校验失败", "升级后无法开机"], [
        ("保持供电与网络", "升级过程请勿断电或断网。"),
        ("重新下载", "删除已下载包后重新下载。"),
        ("U 盘离线升级", "FAT32 格式 U 盘根目录放入对应型号固件。"),
        ("申请售后", "升级后无法开机请勿反复断电，直接申请上门服务。")]),
    ("蓝牙设备配对失败", ["搜不到设备", "频繁断开", "声音延迟"], [
        ("进入配对模式", "长按设备蓝牙键 3 秒至指示灯快闪。"),
        ("清除历史记录", "在蓝牙设置中删除旧配对后重试。"),
        ("缩短距离", "配对时保持 3 米内且无遮挡。"),
        ("减少干扰", "避开微波炉与路由器等 2.4GHz 干扰源。")]),
    ("屏幕出现竖线或暗斑", ["固定位置竖线", "局部发暗", "亮线随时间增加"], [
        ("切换信号源确认", "内置界面同样出现说明为屏幕侧问题。"),
        ("拍照留存", "记录亮线位置与出现时间便于售后判断。"),
        ("勿按压屏幕", "按压可能扩大损坏范围。"),
        ("申请检测", "保修期内属质量问题可免费检测更换。")]),
    ("投屏失败", ["手机搜不到设备", "投屏后黑屏", "画面卡顿"], [
        ("确认同一网络", "手机与设备需连接同一 WiFi。"),
        ("重启投屏服务", "设置 › 网络 › 投屏服务 关闭后重新开启。"),
        ("关闭 VPN", "部分 VPN 会拦截局域网发现。"),
        ("更换投屏协议", "可尝试 DLNA 或 HDMI 有线连接。")]),
    ("投影画面模糊", ["对焦不清", "边缘虚化", "亮度不足"], [
        ("自动对焦", "进入设置执行一次自动对焦。"),
        ("调整投射距离", "按推荐距离 1.5~3 米摆放。"),
        ("清洁镜头", "使用镜头纸轻拭，禁用酒精。"),
        ("检查环境光", "强光环境建议拉窗帘或提高亮度模式。")]),
]


def doc_fault(case, idx: int) -> list:
    title, symptoms, checks = case
    blocks = [H1(f"{title}排查指南"),
              P(f"文档编号：XL-FT-{idx:03d}　｜　版本：{DOC_VERSION}　｜　更新日期：{RELEASE_DATE}"),
              P(f"适用产品：星澜电视 / 投影 / 智能盒子　｜　发布单位：{COMPANY}"),
              H2("一、现象描述")]
    blocks += [LI(s) for s in symptoms]
    blocks += [H2("二、排查步骤")]
    for i, (name, detail) in enumerate(checks, start=1):
        blocks += [H3(f"{i}. {name}"), P(detail)]
    blocks += [H2("三、可能原因"),
               TB([["可能原因", "处理方式"],
                   ["线缆或接口接触不良", "更换线缆或接口，重新插紧"],
                   ["设置项配置错误", "按本文步骤逐项核对设置"],
                   ["硬件模块异常", "需返厂或上门检测更换"]]),
               H2("四、何时需要报修"),
               P(f"完成以上排查仍无法解决时，请拨打 {SUPPORT} 或通过「星澜服务」App 提交工单，"
                 "城区将在 48 小时内安排上门检测。"),
               QT("请勿自行拆机，私自拆机会导致保修失效。")]
    return blocks


GLOBAL_POLICIES = [
    ("整机与主要部件保修政策", [
        ("保修期限", ["整机保修 12 个月，自购机发票开具之日起计算。",
                      "屏幕、主板、电源板等主要部件保修 24 个月。",
                      "遥控器、电源线等附件保修 6 个月。"]),
        ("保修范围", ["非人为因素导致的质量问题免费维修或更换。",
                      "保修期内质量问题产生的往返物流费由我方承担。"]),
        ("不属于保修", ["人为磕碰、进水、私自拆机。", "使用非原厂配件导致的故障。", "超出保修期限。"]),
        ("办理方式", [f"拨打 {SUPPORT} 或通过「星澜服务」App 提交工单，需提供发票或订单号。"]),
    ]),
    ("退换货规则", [
        ("七天无理由退货", ["签收后 7 天内，商品与配件完好可申请退货。", "非质量问题运费由消费者承担。"]),
        ("十五天换货", ["签收后 15 天内出现性能故障可选换货或维修。"]),
        ("不予退换", ["屏幕已有明显人为划痕。", "缺少主要配件或发票。"]),
    ]),
    ("上门安装与调试服务规范", [
        ("服务范围", ["55 英寸及以上机型提供免费上门安装，挂架另计。", "乡镇地区按距离收取上门费。"]),
        ("服务流程", ["预约后 24 小时内电话确认。", "工程师上门确认墙体承重并出具方案。", "安装后现场通电调试并填写服务单。"]),
        ("用户准备", ["确认安装位置具备电源与信号接口。", "提前告知墙体材质。"]),
    ]),
    ("维修收费标准", [
        ("上门费", ["保修期内质量问题免收；保外上门费 80 元。", "超过 30 公里需协商交通费。"]),
        ("主要部件参考价", ["55 英寸屏幕模组 1280 元起；65 英寸 1980 元起；75 英寸 2680 元起。",
                            "电源板 260 元；主板 420 元；遥控器 69 元。"]),
        ("检测费", ["保外检测费 50 元，同意维修可抵扣。"]),
    ]),
    ("延保服务说明", [
        ("延保时长", ["可在标准保修基础上延长 12 或 24 个月，需购机后 90 天内购买。"]),
        ("延保范围", ["覆盖原保修范围内质量问题，不含人为损坏与外观件。", "延保期内免上门费与检测费。"]),
        ("购买方式", ["「星澜服务」App 内选择订单购买。"]),
    ]),
    ("售后服务响应时效承诺", [
        ("响应时效", ["客服热线 7×12 小时，平均接通小于 40 秒。", "在线工单 2 小时内响应，24 小时内给出方案。"]),
        ("上门时效", ["城区 48 小时内上门；偏远地区 72 小时。", "需调拨备件时，备件到货后 24 小时内预约。"]),
        ("升级机制", ["超时未解决可申请升级处理，由区域主管跟进回访。"]),
    ]),
]

GLOBAL_FAQS = [
    ("安装与开箱常见问题", [
        ("需要自己安装底座吗？", "随机附赠底座与螺丝，按说明书安装即可；也可购买挂架并使用上门安装服务。"),
        ("遥控器没电怎么办？", "首次使用请撕掉电池仓绝缘片；仍无反应请更换两节全新 AAA 电池。"),
        ("壁挂对墙体有什么要求？", "建议承重墙或实心墙；轻质隔墙需加装背板。"),
        ("首次开机必须联网吗？", "可以跳过，但语音、在线影视与系统升级需要联网。"),
    ]),
    ("日常使用常见问题", [
        ("长期不用要拔电源吗？", "建议拔掉，既省电也降低雷击风险。"),
        ("屏幕能用酒精擦吗？", "不建议，请使用干燥超细纤维布。"),
        ("如何查看应用占用空间？", "设置 › 应用 › 应用管理。"),
        ("能同时连蓝牙耳机和回音壁吗？", "同一时间仅支持一路蓝牙音频输出。"),
    ]),
    ("售后与保修常见问题", [
        ("没有发票还能保修吗？", "可提供电子订单号或机身序列号核对购机时间。"),
        ("搬家后还能上门吗？", "可以，跨区域需重新预约，部分地区可能产生交通费。"),
        ("换机后保修期怎么算？", "整机保修期自换机之日起重新计算 12 个月。"),
    ]),
    ("画质与音效常见问题", [
        ("画面偏暗怎么办？", "关闭「自动亮度」或切换到「电影/自定义」模式手动提高背光。"),
        ("玩游戏有延迟？", "开启游戏模式并关闭运动补偿。"),
        ("外接回音壁没有声音？", "确认音频输出设为 HDMI eARC，并检查线缆。"),
    ]),
    ("网络与投屏常见问题", [
        ("5GHz 搜不到？", "确认路由器已开启 5GHz 频段且与设备距离不过远。"),
        ("投屏卡顿？", "改用 5GHz 或有线连接，关闭占用带宽的下载任务。"),
        ("能接有线网络吗？", "支持，使用超五类以上网线接入网口。"),
    ]),
    ("配件与耗材常见问题", [
        ("可以用第三方挂架吗？", "可以，但需满足 VESA 孔距与承重要求。"),
        ("遥控器能配几个？", "最多可同时配对 3 个遥控器。"),
        ("投影光源多久更换？", "P1 系列光源寿命约 20000 小时，亮度明显衰减时联系售后。"),
    ]),
]

QUALITY_DOCS = [
    ("整机出厂检验规范", [
        ("检验项目", ["外观：外壳无划伤，缝隙均匀度 ≤0.3mm。",
                      "电气安全：耐压 1500V/60s 无击穿，绝缘电阻 ≥100MΩ。",
                      "功能：开机时间 ≤8s，各接口插拔 3 次识别正常。",
                      "画质：纯色画面亮点不超过 2 个，无暗斑与竖线。"]),
        ("抽检规则", ["按批次 5% 抽检，AQL 0.65。", "出现致命缺陷时整批返工。"]),
        ("追溯要求", ["记录序列号、检验员编号与测试数据，保存 3 年。"]),
    ]),
    ("关键元器件来料检验标准", [
        ("屏幕模组", ["抽检 3 片点亮测试，不允许竖线与大面积暗斑。"]),
        ("电源板", ["输出电压偏差需在 ±3% 以内。"]),
        ("主控芯片", ["抽检 5 片进行烧录与启动测试。"]),
        ("不合格处理", ["整批退回并记录供应商异常，连续两次进入观察名单。"]),
    ]),
    ("生产线静电防护与环境要求", [
        ("静电防护", ["作业人员佩戴防静电手环并每日点检。", "工作台面表面电阻 10^6–10^9 Ω。"]),
        ("环境要求", ["温度 22±3℃，湿度 45%–65%。", "每立方米 ≥0.5μm 尘粒不超过 350000 个。"]),
        ("记录", ["环境数据每 4 小时记录一次，异常立即上报。"]),
    ]),
    ("老化试验与可靠性验证", [
        ("高温老化", ["45℃ 环境下连续运行 48 小时，无死机与画面异常。"]),
        ("开关机循环", ["连续开关机 2000 次，功能保持正常。"]),
        ("跌落与振动", ["包装状态 1 米跌落 3 次，外观与功能无异常。"]),
    ]),
    ("产线异常处理流程", [
        ("异常分级", ["A 类：安全隐患，立即停线。", "B 类：功能不良率 >2%，2 小时内定位。", "C 类：外观不良，当班处理。"]),
        ("处理步骤", ["隔离不良品 → 记录批次 → 通知工艺与质量 → 出具纠正措施。"]),
        ("复盘要求", ["A/B 类异常需在 3 个工作日内提交 8D 报告。"]),
    ]),
]

TRAINING_DOCS = [
    ("新员工产品知识培训提纲", [
        ("产品线概览", ["电视 X3（旗舰）/ A5（主流）/ C7（商用）/ 投影 P1 / 盒子 S / 回音壁 SB。"]),
        ("核心卖点", ["X3 系列：多分区背光、120Hz、4GB+64GB。", "P1 系列：便携投射、自动对焦。"]),
        ("常见客户问题", ["如何选尺寸？一般建议观看距离（米）× 20 ≈ 推荐英寸数。"]),
    ]),
    ("售后服务话术规范", [
        ("开场", ["确认客户机型与购买时间，复述问题确认理解一致。"]),
        ("过程", ["先给可自助的排查步骤，再给上门选项。", "避免使用「不可能」「肯定是你操作问题」等表述。"]),
        ("收尾", ["确认问题是否解决，告知后续跟进方式与时限。"]),
    ]),
    ("导购选型指南", [
        ("按观看距离选尺寸", ["2.5 米：50~55 英寸", "3 米：55~65 英寸", "3.5 米以上：65~85 英寸"]),
        ("按需求选系列", ["观影为主：X3 系列", "预算优先：A5 系列", "会议办公：C7 系列", "移动场景：P1 投影"]),
        ("常见搭配", ["X3-65 + SB-300 回音壁为家庭影院推荐组合。"]),
    ]),
    ("客服工单处理规范", [
        ("工单分级", ["紧急：无法开机、安全隐患，2 小时内响应。", "一般：功能异常，24 小时内响应。"]),
        ("必填信息", ["机型、序列号、购买渠道、故障现象、已尝试步骤。"]),
        ("闭环要求", ["工单完成后 48 小时内回访确认。"]),
    ]),
]

COMPARISON_DOCS = [
    ("X3 与 A5 系列对比选型指南", [
        ("核心差异", TB([["对比项", "X3 系列", "A5 系列"],
                          ["定位", "旗舰 4K", "家用主流"],
                          ["刷新率", "120Hz", "60Hz"],
                          ["背光", "多分区", "直下式"],
                          ["内存", "4GB + 64GB", "2GB + 32GB"],
                          ["音响", "2×15W + 30W 低音", "2×10W"]])),
        ("如何选择", ["观看体育赛事或玩游戏优先选 X3；日常追剧 A5 已足够。"]),
    ]),
    ("C7 商用系列与家用系列差异说明", [
        ("主要差异", TB([["对比项", "C7 商用", "X3/A5 家用"],
                          ["开机广告", "无", "有（可关闭）"],
                          ["连续运行", "支持 7×24 小时", "建议每日 ≤16 小时"],
                          ["接口", "含 RS232 中控接口", "无"],
                          ["系统", "商用精简系统", "家用智能系统"]])),
        ("适用场景", ["会议室、展厅、门店信息发布选 C7；家庭娱乐选 X3/A5。"]),
    ]),
    ("回音壁 SB 系列对比", [
        ("规格对比", TB([["型号", "声道", "功率", "低音炮"],
                          ["SB-200", "2.0", "60W", "无"],
                          ["SB-300", "2.1", "120W", "有（无线）"],
                          ["SB-500", "3.1.2", "260W", "有（无线）"]])),
        ("选购建议", ["小客厅选 SB-300；追求环绕效果选 SB-500。"]),
    ]),
    ("智能盒子 S 系列与内置系统对比", [
        ("对比", TB([["对比项", "S1", "S1-Pro", "电视内置系统"],
                      ["内存", "2GB+16GB", "4GB+32GB", "视机型而定"],
                      ["4K 解码", "支持", "支持", "支持"],
                      ["适合场景", "老电视升级", "游戏与高频使用", "新机"]])),
    ]),
]

SERVICE_DOCS = [
    ("全国服务网点与寄修流程", [
        ("网点覆盖", ["全国 286 个地级市设有授权服务网点，可在 App 内查询最近网点。"]),
        ("寄修流程", ["提交工单 → 客服确认 → 顺丰上门取件 → 检测报价 → 维修 → 寄回。"]),
        ("时效", ["寄修全程一般 5~7 个工作日，需调拨备件时不超过 12 个工作日。"]),
    ]),
    ("备件供应与更换政策", [
        ("备件供应年限", ["整机停产后提供不少于 5 年的备件供应。"]),
        ("更换原则", ["优先维修；维修成本超过新机 60% 时建议换新并给出优惠方案。"]),
        ("旧件处理", ["更换下的旧件由服务网点统一回收，如需保留请提前说明。"]),
    ]),
    ("客户满意度回访规范", [
        ("回访时机", ["服务完成后 48 小时内电话或短信回访。"]),
        ("回访内容", ["是否解决、工程师服务态度、是否二次收费。"]),
        ("闭环", ["不满意工单 24 小时内升级处理并由主管致电。"]),
    ]),
    ("投诉与升级处理流程", [
        ("一级", ["客服一线记录并给出方案，24 小时内闭环。"]),
        ("二级", ["区域主管介入，48 小时内出具处理意见。"]),
        ("三级", ["涉及质量安全问题的，提交总部质量委员会评审。"]),
    ]),
]


def policy_blocks(title, sections, no) -> list:
    blocks = [H1(title),
              P(f"文档编号：XL-PL-{no:03d}　｜　版本：{DOC_VERSION}　｜　更新日期：{RELEASE_DATE}"),
              P(f"适用范围：全系列产品　｜　发布单位：{COMPANY}")]
    for i, (sec, items) in enumerate(sections, start=1):
        blocks.append(H2(f"{i}. {sec}"))
        blocks += [LI(x) for x in items]
    return blocks


def faq_blocks(title, items, no) -> list:
    blocks = [H1(title),
              P(f"文档编号：XL-FQ-{no:03d}　｜　版本：{DOC_VERSION}　｜　更新日期：{RELEASE_DATE}")]
    for i, (q, a) in enumerate(items, start=1):
        blocks += [H2(f"{i}. {q}"), P(a)]
    return blocks


def section_blocks(title, sections, no, prefix) -> list:
    blocks = [H1(title),
              P(f"文档编号：{prefix}-{no:03d}　｜　版本：{DOC_VERSION}　｜　更新日期：{RELEASE_DATE}"),
              P(f"发布单位：{COMPANY}")]
    for i, (sec, items) in enumerate(sections, start=1):
        if isinstance(items, list) and items and isinstance(items[0], list):
            blocks += [H2(f"{i}. {sec}"), TB(items)]
            continue
        blocks.append(H2(f"{i}. {sec}"))
        blocks += [LI(x) for x in items]
    return blocks


# ------------------------------------------------------------------ 渲染器
def render_markdown(blocks: list) -> str:
    lines: list[str] = []
    for kind, content in blocks:
        if kind == "h1":
            lines += [f"# {content}", ""]
        elif kind == "h2":
            lines += [f"## {content}", ""]
        elif kind == "h3":
            lines += [f"### {content}", ""]
        elif kind == "p":
            lines += [content, ""]
        elif kind == "li":
            lines.append(f"- {content}")
        elif kind == "quote":
            lines += [f"> {content}", ""]
        elif kind == "table":
            rows = content
            lines.append("| " + " | ".join(str(c) for c in rows[0]) + " |")
            lines.append("|" + "---|" * len(rows[0]))
            for row in rows[1:]:
                lines.append("| " + " | ".join(str(c) for c in row) + " |")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_docx(blocks: list, path: Path) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    for kind, content in blocks:
        if kind == "h1":
            doc.add_heading(content, level=1)
        elif kind == "h2":
            doc.add_heading(content, level=2)
        elif kind == "h3":
            doc.add_heading(content, level=3)
        elif kind == "p":
            doc.add_paragraph(content)
        elif kind == "li":
            doc.add_paragraph(content, style="List Bullet")
        elif kind == "quote":
            doc.add_paragraph(content, style="Intense Quote")
        elif kind == "table":
            rows = content
            table = doc.add_table(rows=len(rows), cols=len(rows[0]))
            table.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    cell = table.cell(r, c)
                    cell.text = str(value)
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.size = Pt(9)
    doc.save(str(path))


def render_pdf(blocks: list, path: Path) -> None:
    """用 PyMuPDF 直接生成 PDF（内置中文字体，无需 Office）。

    ⚠️ 踩坑记录：不要用 page.insert_textbox()——它的矩形高度必须精确估算，
    只要差 0.2pt 就整块不渲染（且不报错），结果是 PDF 打开一片空白、解析出来 0 字符。
    这里改成「自己按字符宽度折行 + insert_text 逐行写入」，稳定可控。
    """
    import fitz

    page_w, page_h = 595, 842  # A4
    margin, bottom = 50, 62
    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)
    y = margin
    usable = page_w - 2 * margin

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=page_w, height=page_h)
        y = margin

    def wrap(text: str, size: float, indent: float = 0.0) -> list[str]:
        """按字符宽度折行：中文字符按 1em、ASCII 按 0.55em 估算。"""
        limit = (usable - indent) / size
        lines: list[str] = []
        current, used = "", 0.0
        for ch in text:
            width = 1.0 if ord(ch) > 0x2E80 else 0.55
            if used + width > limit and current:
                lines.append(current)
                current, used = "", 0.0
            current += ch
            used += width
        if current:
            lines.append(current)
        return lines or [""]

    def put(text: str, size: float, font: str = "china-s", indent: float = 0.0):
        nonlocal y
        line_height = size * 1.62
        for line in wrap(text, size, indent):
            if y + line_height > page_h - bottom:
                new_page()
            page.insert_text((margin + indent, y + size), line, fontname=font, fontsize=size)
            y += line_height
        y += 3

    for kind, content in blocks:
        if kind == "h1":
            put(content, 19, "china-ss")
            y += 6
        elif kind == "h2":
            y += 6
            put(content, 14, "china-ss")
            y += 2
        elif kind == "h3":
            put(content, 11.5, "china-ss")
        elif kind == "p":
            put(content, 10)
        elif kind == "li":
            put("· " + content, 10, indent=14)
        elif kind == "quote":
            put("【提示】" + content, 9.5, indent=14)
        elif kind == "table":
            for row in content:
                put(" ｜ ".join(str(c) for c in row), 9, indent=8)
            y += 4
    doc.save(str(path))
    doc.close()


# ------------------------------------------------------------------ 主流程
def format_for(index: int) -> str:
    """按比例分配格式：约 60% Markdown、20% Word、20% PDF。"""
    slot = index % 10
    if slot in (0, 1, 2, 3, 4, 5):
        return "md"
    if slot in (6, 7):
        return "docx"
    return "pdf"


def build_corpus() -> list[tuple[Path, list]]:
    """返回 [(相对路径, 文档块)]。"""
    out: list[tuple[Path, list]] = []
    models = build_models()

    idx = 0
    for model in models:
        for doc_type, builder in MODEL_DOC_BUILDERS.items():
            blocks = builder(model, idx)
            ext = format_for(idx)
            out.append((Path(PRODUCT_ROOT) / model["series"] / model["code"] / f"{doc_type}.{ext}", blocks))
            idx += 1

    for i, (title, symptoms, checks) in enumerate(FAULT_CASES, start=1):
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "故障排查" / f"{title}.{ext}", doc_fault((title, symptoms, checks), i)))

    for i, (title, sections) in enumerate(GLOBAL_POLICIES, start=1):
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "售后政策" / f"{title}.{ext}", policy_blocks(title, sections, i)))

    for i, (title, items) in enumerate(GLOBAL_FAQS, start=1):
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "常见问题" / f"{title}.{ext}", faq_blocks(title, items, i)))

    for i, (title, sections) in enumerate(QUALITY_DOCS, start=1):
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "生产质量" / f"{title}.{ext}",
                    section_blocks(title, sections, i, "XL-QC")))

    for i, (title, sections) in enumerate(TRAINING_DOCS, start=1):
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "培训资料" / f"{title}.{ext}",
                    section_blocks(title, sections, i, "XL-TR")))

    for i, (title, sections) in enumerate(COMPARISON_DOCS, start=1):
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "选型对比" / f"{title}.{ext}",
                    section_blocks(title, sections, i, "XL-CP")))

    for i, (title, sections) in enumerate(SERVICE_DOCS, start=1):
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "服务流程" / f"{title}.{ext}",
                    section_blocks(title, sections, i, "XL-SV")))

    for series, cfg in SERIES_DEF.items():
        title = f"{series} 系列固件更新日志"
        sections = [
            ("V3.2.0（2026-04-10）", ["新增多设备互联与画质档案保存功能。", "首页加载速度提升约 30%。"]),
            ("V3.1.2（2026-02-26）", ["修复 120Hz 下偶发闪屏问题。", "语音唤醒响应平均缩短 200ms。"]),
            ("V3.0.8（2026-01-15）", ["提升 5GHz 频段连接稳定性。", "修复升级后偶发无法识别 U 盘的问题。"]),
        ]
        ext = format_for(idx); idx += 1
        out.append((Path(COMMON_ROOT) / "版本发布" / f"{title}.{ext}",
                    section_blocks(title, sections, len(out) % 90 + 1, "XL-RL")))

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="生成多格式演示语料")
    parser.add_argument("--out", default="data/raw")
    parser.add_argument("--target", type=int, default=0, help="最多生成多少篇（0 = 全部）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clean", action="store_true", help="先删除本脚本生成的两个目录")
    args = parser.parse_args()

    out_dir = ROOT / args.out
    docs = build_corpus()
    if args.target:
        docs = docs[: args.target]

    stats = {"md": 0, "docx": 0, "pdf": 0}
    for path, _ in docs:
        stats[path.suffix.lstrip(".")] += 1

    print(f"计划生成 {len(docs)} 篇：Markdown {stats['md']} / Word {stats['docx']} / PDF {stats['pdf']}")
    print(f"目录结构：{out_dir / PRODUCT_ROOT}/<系列>/<型号>/<文档类型>.<格式>")
    print(f"          {out_dir / COMMON_ROOT}/<文档类别>/<标题>.<格式>")

    if args.dry_run:
        for path, _ in docs[:8]:
            print("  ·", path)
        print("  ...")
        return

    if args.clean:
        for name in (PRODUCT_ROOT, COMMON_ROOT):
            target = out_dir / name
            if target.exists():
                shutil.rmtree(target)
                print(f"已清理 {target}")

    created = 0
    for path, blocks in docs:
        full = out_dir / path
        if full.exists():
            continue
        full.parent.mkdir(parents=True, exist_ok=True)
        ext = full.suffix.lstrip(".")
        if ext == "md":
            full.write_text(render_markdown(blocks), encoding="utf-8")
        elif ext == "docx":
            render_docx(blocks, full)
        else:
            render_pdf(blocks, full)
        created += 1

    print(f"已生成 {created} 篇（跳过已存在 {len(docs) - created} 篇）")
    print("下一步：")
    print("  python main.py chunk     # 解析 + 切片")
    print("  python main.py index     # 重建索引")


if __name__ == "__main__":
    main()
