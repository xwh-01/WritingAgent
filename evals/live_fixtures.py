"""Frozen chapter contracts for repeatable real-provider quality evaluation.

The six live cases are scenario specifications, not a planner benchmark.  A
randomly regenerated contract changes the thing being measured on every run,
so this module converts each existing premise/rubric into one explicit,
author-editable chapter contract.  Planner behaviour is covered separately by
the deterministic workflow tests; the live suite measures execution of a
known hard contract.
"""

from __future__ import annotations

from novelforge.domain import ChapterContract, ChapterOutline

_FIXTURES: dict[str, tuple[dict, dict]] = {
    "cost_of_truth": (
        {
            "chapter_index": 1,
            "title": "雨夜的原始证词",
            "summary": "林砚在午夜封存前决定公开能牵连父亲的原始证词，并承担立刻可见的程序代价。",
            "conflict": "维护父亲名誉与公开真相不可兼得。",
            "pov_character": "林砚",
        },
        {
            "chapter_index": 1,
            "pov_character": "林砚",
            "location": "暴雨中的市档案馆阅览室与封存窗口",
            "time_context": "午夜封存前最后十五分钟",
            "must_happen": [
                "林砚找到能证明父亲参与旧案栽赃的原始证词",
                "苏遥提醒林砚午夜一到全部档案将被封存",
                "林砚亲手把原始证词递交给监察登记窗口",
                "登记员记录林砚违反封存程序的姓名和时间",
            ],
            "must_not_happen": [
                "苏遥替林砚决定是否公开证词",
                "父亲旧案在本章内被洗清",
                "林砚在递交后撤回原始证词",
            ],
            "character_goals": {"林砚": "在封存前决定证词去向", "苏遥": "推动程序但不替林砚选择"},
            "knowledge_boundaries": {"林砚": {"不应知道": ["父亲当年参与栽赃的全部动机"]}},
            "active_threads": ["旧案证词", "午夜封存", "父亲名誉"],
            "ending_hook": "雨水打在档案馆玻璃上，林砚攥着登记回执，封存门在他身后落锁。",
            "style_requirements": ["用档案、雨声和动作呈现两难，避免道德总结"],
        },
    ),
    "glass_wound": (
        {
            "chapter_index": 1,
            "title": "裂缝里的温度",
            "summary": "沈砚用一段私人记忆修补城门玻璃，保住城门却失去妹妹影像之外的重要记忆。",
            "conflict": "守城需要修补，修补会抹去私人记忆。",
            "pov_character": "沈砚",
        },
        {
            "chapter_index": 1,
            "pov_character": "沈砚",
            "location": "北境城门内侧的魔法玻璃前",
            "time_context": "敌军抵达前三日的午后",
            "must_happen": [
                "沈砚触碰玻璃裂缝并感到妹妹影像留下的温度",
                "罗禾催促沈砚尽快修补城门玻璃但不替他选择",
                "沈砚用自己关于母亲面容的一段记忆修补玻璃",
                "玻璃裂缝合拢后沈砚发现自己记不起母亲的脸",
            ],
            "must_not_happen": [
                "玻璃完全碎裂或彻底失效",
                "沈菱失踪原因在本章内被揭示",
                "罗禾替沈砚作出修补决定",
            ],
            "character_goals": {"沈砚": "守住城门并承担记忆代价", "罗禾": "催促防御修复"},
            "knowledge_boundaries": {"沈砚": {"不应知道": ["沈菱失踪的原因"]}},
            "active_threads": ["城门裂缝", "沈菱失踪", "敌军逼近"],
            "ending_hook": "修好的玻璃映出城门外的阴影，沈砚摸向记忆中的母亲却只摸到一片空白。",
            "style_requirements": ["以裂缝、工具和身体反应呈现规则与代价，不写设定说明"],
        },
    ),
    "last_train": (
        {
            "chapter_index": 1,
            "title": "末班车的调解书",
            "summary": "许知夏在信号中断前决定暂不归还前任遗落的调解书，并承担信息与关系上的风险。",
            "conflict": "归还文件的即时冲动与父亲旧债真相相冲突。",
            "pov_character": "许知夏",
        },
        {
            "chapter_index": 1,
            "pov_character": "许知夏",
            "location": "深夜末班列车车厢",
            "time_context": "列车即将进隧道失去信号，陆川下一站下车",
            "must_happen": [
                "许知夏在座位下发现陆川遗落的调解书",
                "调解书提到她父亲未还清的旧债",
                "陆川在下一站下车离开",
                "许知夏决定暂时带走文件而没有追下车归还",
                "许知夏想起拍卖过陆川不愿公开的照片但没有解释原因",
            ],
            "must_not_happen": [
                "许知夏与陆川在本章内直接对话",
                "陆川发现许知夏捡到文件",
                "许知夏通过手机联系陆川",
                "许知夏解释拍卖照片的原因",
            ],
            "character_goals": {"许知夏": "在隧道前决定文件去向"},
            "knowledge_boundaries": {"许知夏": {"不应知道": ["陆川遗落文件的真实意图"]}},
            "active_threads": ["父亲旧债", "拍卖照片", "隧道断信号"],
            "ending_hook": "隧道黑暗吞没信号，许知夏把调解书压在掌心，列车已越过陆川下车的站台。",
            "style_requirements": ["以车厢动作、物件和潜台词写前任关系，避免告白式总结"],
        },
    ),
    "oxygen_debt": (
        {
            "chapter_index": 1,
            "title": "八小时氧债",
            "summary": "阿洛在沙暴前决定修复被篡改的阀门，以八小时氧气储备换取基地继续运转。",
            "conflict": "等待弟弟返航的程序要求与不断泄漏的氧气冲突。",
            "pov_character": "阿洛",
        },
        {
            "chapter_index": 1,
            "pov_character": "阿洛",
            "location": "火星温室基地氧循环主控室",
            "time_context": "沙暴将在两小时后切断备用管线，弟弟正在外勤舱",
            "must_happen": [
                "阿洛发现氧循环主阀门被人为篡改",
                "阿洛计算出修复阀门后基地储氧只够八小时",
                "阿洛向魏衡报告篡改和八小时读数",
                "魏衡要求等待外勤舱返航但不替阿洛按下开关",
                "阿洛亲手启动阀门修复并看见氧气倒计时落到八小时",
            ],
            "must_not_happen": [
                "弟弟在本章内返回基地或与阿洛直接通话",
                "魏衡替阿洛作出是否修复的最终决定",
                "篡改者身份或动机在本章内被揭示",
            ],
            "character_goals": {"阿洛": "在弟弟返航前承担修复的资源代价", "魏衡": "保留程序性反对"},
            "knowledge_boundaries": {"阿洛": {"不应知道": ["篡改者身份或动机"]}},
            "active_threads": ["八小时氧气", "沙暴窗口", "外勤弟弟"],
            "ending_hook": "修复程序亮起绿灯，氧表从08:00开始递减，窗外沙暴撞上基地外壳。",
            "style_requirements": ["用读数、警报和阀门操作表达冲突，避免技术说明书"],
        },
    ),
    "sealed_signal": (
        {
            "chapter_index": 1,
            "title": "黎明前的频率",
            "summary": "周岚违抗封存命令播出姐姐的求救录音，并立刻承担职业处分风险。",
            "conflict": "遵守电台规程会错过货轮离港窗口。",
            "pov_character": "周岚",
        },
        {
            "chapter_index": 1,
            "pov_character": "周岚",
            "location": "台风夜的海港电台值班室",
            "time_context": "货轮将在黎明前离港",
            "must_happen": [
                "周岚播放磁带并听到失踪姐姐的求救声音",
                "顾宁通过电话要求周岚按规程封存磁带",
                "窗外货轮汽笛提示黎明前离港期限",
                "周岚亲手按下播出键发送求救信号",
                "系统记录周岚的违规播出并触发值班报警",
            ],
            "must_not_happen": [
                "顾宁替周岚决定是否播出",
                "走私集团成员直接出现在值班室",
                "姐姐被找到或货轮被拦下",
            ],
            "character_goals": {"周岚": "在离港前让求救信号离开电台", "顾宁": "指出规程风险"},
            "knowledge_boundaries": {"周岚": {"不应知道": ["走私集团的完整身份名单"]}},
            "active_threads": ["姐姐求救录音", "货轮离港", "违规代价"],
            "ending_hook": "播出灯转红，值班报警压过汽笛声，周岚看见处分编号跳上屏幕。",
            "style_requirements": ["让磁带、按键、风雨和声音承担叙事，不宣讲亲情或正义"],
        },
    ),
    "silent_verdict": (
        {
            "chapter_index": 1,
            "title": "无字幕的证据",
            "summary": "程默在仲裁时限内提交打码视频，保护证人住址并承担当庭证据不完整的代价。",
            "conflict": "公开视频可赢案但会暴露证人住址。",
            "pov_character": "程默",
        },
        {
            "chapter_index": 1,
            "pov_character": "程默",
            "location": "劳动仲裁庭休庭走廊",
            "time_context": "仲裁员要求十五分钟内提交证据",
            "must_happen": [
                "程默从无字幕视频中看见公司伪造加班记录的证据",
                "程默发现视频画面会暴露证人家庭住址",
                "江绮主张先公开视频以争取仲裁",
                "程默亲手给住址打码后提交视频",
                "仲裁员因视频被打码要求程默承担证据不完整的风险",
            ],
            "must_not_happen": [
                "证人的家庭住址被公开",
                "江绮替程默决定是否提交视频",
                "仲裁结果在本章内完全揭晓",
            ],
            "character_goals": {"程默": "保护证人并在期限内提交可用证据", "江绮": "争取最大胜诉机会"},
            "knowledge_boundaries": {"程默": {"不应知道": ["证人家属的其他隐私"]}},
            "active_threads": ["伪造工时", "证人住址", "十五分钟期限"],
            "ending_hook": "提交倒计时归零，打码视频停在屏幕上，仲裁员抬手要求程默解释缺失的画面。",
            "style_requirements": ["让手语、字幕和屏幕动作自然参与冲突，避免励志或道德说教"],
        },
    ),
}


def fixed_case_plan(case_id: str) -> tuple[ChapterOutline, ChapterContract] | None:
    """Return independent model copies so a trial cannot mutate the fixture."""
    payload = _FIXTURES.get(case_id)
    if payload is None:
        return None
    outline, contract = payload
    return ChapterOutline.model_validate(outline), ChapterContract.model_validate(contract)


__all__ = ["fixed_case_plan"]
