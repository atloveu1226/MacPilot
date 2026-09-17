import argparse
import uuid

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from macpilot.core.checkpoint import make_sqlite_checkpointer
from macpilot.core.config import Settings
from macpilot.core.storage import SQLiteStore
from macpilot.phase2.workflow import build_agent_workflow


def main() -> None:
    # Prefer the project's .env over a stale variable inherited by the shell.
    load_dotenv(override=True)
    parser = argparse.ArgumentParser(description="Run the MacPilot file agent")
    parser.add_argument("--thread-id", default=None, help="Conversation/checkpoint id")
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.api_key:
        raise SystemExit(
            "Missing DASHSCOPE_API_KEY. Copy .env.example to .env and configure it."
        )

    store = SQLiteStore(settings.database_path)
    task_id = args.thread_id or str(uuid.uuid4())
    if store.get_task(task_id) is None:
        store.create_task("Interactive MacPilot session", task_id=task_id)
    store.update_task_status(task_id, "running")
    store.append_event("task_started", {"thread_id": task_id}, task_id=task_id)
    checkpointer, _checkpoint_connection = make_sqlite_checkpointer(
        settings.database_path
    )
    workflow = build_agent_workflow(
        settings,
        audit_store=store,
        task_id=task_id,
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": task_id}}
    print("MacPilot 已启动。输入 exit 退出。")
    while True:
        try:
            query = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query.lower() in {"exit", "quit", "q"}:
            break
        if not query:
            continue

        step_id = store.create_step(task_id, "MacPilot", input_data={"query": query})
        store.append_event(
            "user_message", {"content": query}, task_id=task_id, step_id=step_id
        )
        try:
            result = workflow.invoke(
                {"messages": [HumanMessage(content=query)]}, config=config
            )
        except Exception as error:
            store.finish_step(step_id, "failed", {"error": str(error)})
            store.append_event(
                "error", {"message": str(error)}, task_id=task_id, step_id=step_id
            )
            store.update_task_status(task_id, "failed")
            raise
        response = result["messages"][-1].content
        store.finish_step(step_id, "completed", {"response": response})
        store.append_event(
            "assistant_message", {"content": response}, task_id=task_id, step_id=step_id
        )
        print(f"Agent> {response}\n")

    store.update_task_status(task_id, "completed")
    store.append_event("task_completed", {}, task_id=task_id)


if __name__ == "__main__":
    main()
