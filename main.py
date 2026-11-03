"""Smart Scheduler entry point.  Run:  python main.py"""
from ui.scheduler_app import SchedulerApp


def main() -> None:
    SchedulerApp().mainloop()


if __name__ == "__main__":
    main()
