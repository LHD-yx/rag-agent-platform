"""统一入口：在 PyCharm 里右键运行本文件，或使用命令行子命令。

用法：
    python main.py chunk               # 解析 + 清洗 + 切片
    python main.py index               # 构建 FAISS + BM25 索引
    python main.py query "你的问题"     # 只做检索（不调用大模型）
    python main.py rewrite "你的问题"   # 只看查询改写结果
    python main.py ask "你的问题"       # 端到端问答（检索 + 生成）
    python main.py agent "你的问题"     # 多跳 Agent
    python main.py eval                # 跑评测并生成消融表
    python main.py serve               # 启动 FastAPI 服务
"""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAG 项目统一入口")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("chunk", help="解析 + 清洗 + 切片")
    sub.add_parser("index", help="构建 FAISS + BM25 索引")

    doctor = sub.add_parser("doctor", help="环境自检（卡住了就跑这个）")
    doctor.add_argument("--skip-api", action="store_true", help="不联网，只检查本地")

    query = sub.add_parser("query", help="检索单条问题")
    query.add_argument("question", help="要检索的问题")
    query.add_argument("-k", type=int, default=5, help="返回条数，默认 5")

    rewrite = sub.add_parser("rewrite", help="查看查询改写结果")
    rewrite.add_argument("question")

    ask = sub.add_parser("ask", help="端到端问答")
    ask.add_argument("question")

    agent = sub.add_parser("agent", help="多跳检索 Agent")
    agent.add_argument("question")

    sub.add_parser("eval", help="跑评测并生成消融表")

    serve = sub.add_parser("serve", help="启动 FastAPI 服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "chunk":
        from rag_agent.chunking import build_chunks

        build_chunks()
    elif args.command == "doctor":
        from rag_agent.doctor import main as doctor_main

        doctor_main(skip_api=args.skip_api)
    elif args.command == "index":
        from rag_agent.build_index import build_index

        build_index()
    elif args.command == "query":
        from rag_agent.hybrid import main as query_main

        query_main(args.question, args.k)
    elif args.command == "eval":
        from rag_agent.evaluate import main as eval_main

        eval_main()
    elif args.command == "rewrite":
        from rag_agent.rewrite import QueryRewriter

        rewriter = QueryRewriter()
        print("原始 :", args.question)
        print("改写后:", rewriter.normalize(args.question))
    elif args.command == "ask":
        from rag_agent.pipeline import main as ask_main

        ask_main(args.question)
    elif args.command == "agent":
        from rag_agent.agent import main as agent_main

        agent_main(args.question)
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("rag_agent.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
