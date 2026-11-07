"""Reproduce the synthetic example; this is a curated fixture, not an AI call."""
import argparse
import json
from pathlib import Path

from qunhuibao.cli import prepare, render, read_json, json_text
from qunhuibao.validation import source_digest


def example_report(messages):
    def item(title, body, kind, refs, **extra):
        return dict(title=title, body=body, kind=kind, evidence_refs=refs, **extra)
    return {
        "schema_version": 1, "source_digest": source_digest(messages),
        "title": "从群聊到下一步 · 合成演示",
        "summary": "本示例由虚构聊天整理：先让 3 位熟悉群主试用固定模板报告，检查行动依据与修改负担；公开分享、撤回机制和旧桶清理范围仍待确认。",
        "conversation": messages["conversation"], "period": "2026-11-06 09:00—09:18（合成材料）",
        "sections": [
            {"key": "topics", "title": "讨论主题", "items": [
                item("先验证小范围使用价值", "面向 3 位熟悉群主试用；重点观察行动是否有依据，以及群主还要修改多少内容。", "fact", ["demo-01", "demo-06"])]},
            {"key": "decisions", "title": "已经决定", "items": [
                item("本次使用固定模板，在本机生成", "当前不接收用户 HTML，不开放匿名上传。公开分享待试用后再决定；此前的开放上传提议并未采纳。", "decision", ["demo-01", "demo-02", "demo-03"])]},
            {"key": "actions", "title": "下一步行动", "items": [
                item("准备脱敏聊天样本", "交给参与者测试报告的引用和可读性。", "action", ["demo-04"], owner="陈一（虚构）", due="2026-11-08 前", status="待完成")]},
            {"key": "assets", "title": "可复用资产", "items": [
                item("群主整理清单.pdf", "群里提到已发清单。本演示仅保留附件索引，未读取 PDF 内容，也不据此总结文件细节。", "asset", ["demo-07"])]},
            {"key": "questions", "title": "仍待确认", "items": [
                item("分享链接如何到期和撤回", "负责人和日期尚未确定；不能把这条讨论当成已承诺开发的任务。", "question", ["demo-05"]),
                item("旧存储桶的身份与清理范围", "桶名及共享关系未核实。", "question", ["demo-08"]),
                item("试用时记录群主修改量", "建议保留修改前后版本，辅助判断报告是否减轻整理工作。这是演示整理者建议。", "suggestion", [])]},
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("演示输出目录已存在，请使用新目录")
    prepared = args.out / "prepared"
    prepare(Path(__file__).with_name("chat.json"), prepared)
    messages = read_json(prepared / "messages.json")
    (prepared / "report.json").write_text(json_text(example_report(messages)), encoding="utf-8")
    print(json.dumps(render(prepared / "messages.json", prepared / "report.json", args.out / "report"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
