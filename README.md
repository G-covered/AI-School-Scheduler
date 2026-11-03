# Smart Scheduler

A desktop scheduler (Python + Tkinter) that builds an organised agenda from manually
entered events plus links and documents that contain schedule information.

## Run

```bash
pip install -r requirements.txt      # optional extras (PDF support, SSL certs)
python main.py
```

Requires Python 3.9+. Tkinter ships with Python (Linux: `sudo apt install python3-tk`).

## Supported sources

- Web links: HTML pages, `.ics` calendar feeds, PDFs
- Files: `.txt .md .csv .ics .docx .html .pdf` (PDF needs `pypdf`)

Your schedule is stored in `~/.smart_scheduler/schedule.json` by default
(same format as the previous single-file version, so existing data loads as-is).

## Project layout

```
Scheduler/
├── main.py                     entry point
├── models/
│   ├── event.py                Event dataclass (+ time helpers, search, (de)serialising)
│   └── source.py               Source dataclass (a link or a file)
├── services/                   no Tkinter in here
│   ├── text_parser.py          TextParser (free text) and ICalParser (.ics text)
│   ├── document_reader.py      DocumentReader: fetch/read a Source -> events
│   ├── conflict_detector.py    ConflictDetector: finds overlapping events
│   ├── calendar_exporter.py    CalendarExporter: .ics / .csv output
│   ├── event_storage.py        EventStorage: JSON load/save
│   └── event_manager.py        EventManager: owns events + sources, ties services together
└── ui/
    ├── scheduler_app.py        SchedulerApp: main window, menu, toolbar, wiring
    ├── calendar_view.py        CalendarView (month grid) and EventListView
    ├── event_dialog.py         EventDialog: add/edit form
    └── source_panel.py         SourcePanel: list of links/documents + Compile
```

Dependencies point one way: `ui -> services -> models`. The UI only talks to
`EventManager`; everything in `models/` and `services/` can be tested without a display.

## Planned Features

- **Interactive Calendar:** View events in a monthly calendar.
- **Event Management:** Add, edit, and delete individual events.
- **Schedule Customization:** Organize academic and personal commitments.
- **Recurring Events:** Create repeating schedules for classes, work, and other activities.
- **Local Storage:** Save schedules so they remain available after closing the application.
- **Improved Interface:** Develop a cleaner and more user-friendly desktop experience.
- **AI Integration (Future Goal):** Automatically identify assignments, exams, and due dates from uploaded syllabi.

## Project Goal

Our goal is to create a functional desktop scheduling application that helps students manage their time more effectively by combining academic deadlines and personal commitments into an organized calendar.

The project emphasizes modular programming, object-oriented design, and an intuitive user experience.