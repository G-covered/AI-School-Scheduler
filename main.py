import tkinter as tk
from tkinter import filedialog, messagebox
import re
import os
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from docx import Document
from urllib.parse import urlparse


class SchedulerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Scheduler")
        self.root.geometry("700x650")

        self.links = []
        self.documents = []

        # Title
        title_label = tk.Label(
            root,
            text="Smart Scheduler",
            font=("Helvetica", 24, "bold")
        )
        title_label.pack(pady=20)

        # Link section
        link_frame = tk.Frame(root)
        link_frame.pack(fill=tk.X, padx=20, pady=10)

        tk.Label(
            link_frame,
            text="Add a link:",
            font=("Arial", 12, "bold")
        ).pack(side=tk.LEFT, padx=5)

        self.link_entry = tk.Entry(link_frame)
        self.link_entry.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )

        tk.Button(
            link_frame,
            text="Add Link",
            command=self.add_link
        ).pack(side=tk.LEFT, padx=5)

        # Document section
        document_frame = tk.Frame(root)
        document_frame.pack(fill=tk.X, padx=20, pady=10)

        tk.Label(
            document_frame,
            text="Add a document:",
            font=("Arial", 12, "bold")
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            document_frame,
            text="Choose File",
            command=self.add_document
        ).pack(side=tk.LEFT, padx=5)

        self.document_label = tk.Label(
            document_frame,
            text="No documents selected"
        )
        self.document_label.pack(side=tk.LEFT, padx=5)

        # Manual schedule section
        tk.Label(
            root,
            text="Enter your schedule:",
            font=("Arial", 12, "bold")
        ).pack(anchor="w", padx=25, pady=(15, 5))

        self.manual_entry = tk.Text(
            root,
            height=12,
            width=75,
            font=("Arial", 11),
            wrap=tk.WORD
        )
        self.manual_entry.pack(
            fill=tk.BOTH, expand=True, padx=25, pady=5
        )

        # View schedule button
        tk.Button(
            root,
            text="VIEW SCHEDULE",
            font=("Arial", 14, "bold"),
            command=self.view_schedule
        ).pack(pady=20)

    # Add a link
    def add_link(self):
        link = self.link_entry.get().strip()

        if link:
            self.links.append(link)
            self.link_entry.delete(0, tk.END)

            messagebox.showinfo(
                "Success",
                "Your link has been added."
            )
        else:
            messagebox.showwarning(
                "Missing Link",
                "Please enter a link first."
            )

    # Select a document
    def add_document(self):
        file_path = filedialog.askopenfilename(
            title="Select a document",
            filetypes=[
                ("Supported documents", "*.pdf *.docx *.txt"),
                ("All files", "*.*")
            ]
        )

        if file_path:
            extension = os.path.splitext(file_path)[1].lower()

            if extension not in (".pdf", ".docx", ".txt"):
                messagebox.showwarning(
                    "Unsupported File",
                    "Please choose a PDF, DOCX, or TXT file."
                )
                return

            self.documents.append(file_path)
            self.document_label.config(
                text=f"{len(self.documents)} document(s) selected"
            )

    # Read uploaded documents
    def read_document(self, file_path):
        extension = os.path.splitext(file_path)[1].lower()

        if extension == ".txt":
            with open(
                file_path, "r", encoding="utf-8"
            ) as file:
                return file.read()

        elif extension == ".pdf":
            reader = PdfReader(file_path)
            return "\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )

        elif extension == ".docx":
            document = Document(file_path)
            return "\n".join(
                paragraph.text
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            )

        else:
            raise ValueError("Unsupported document type.")

    # Read a public webpage
    def read_webpage(self, url):
        url = url.strip()

        if not url.startswith(("https://", "http://")):
            url = "https://" + url

        parsed_url = urlparse(url)

        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.hostname
            or parsed_url.username
            or parsed_url.password
        ):
            raise ValueError("Please enter a valid public website URL.")

        # Avoid requests to local or private network addresses.
        hostname = parsed_url.hostname.lower()
        if (
            hostname == "localhost"
            or hostname.endswith(".localhost")
            or hostname.endswith(".local")
            or hostname in ("0.0.0.0", "::", "::1")
            or hostname.startswith("127.")
            or hostname.startswith("10.")
            or hostname.startswith("192.168.")
            or hostname.startswith("169.254.")
            or hostname == "metadata.google.internal"
        ):
            raise ValueError("Local and private network URLs are not supported.")

        response = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "SmartScheduler/1.0"},
            allow_redirects=False
        )
        response.raise_for_status()

        if not response.headers.get(
            "Content-Type", ""
        ).lower().startswith("text/html"):
            raise ValueError(
                "This link does not point to an HTML webpage."
            )

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove unnecessary webpage elements
        for element in soup(
            ["script", "style", "nav", "footer", "header"]
        ):
            element.decompose()

        return soup.get_text(separator="\n", strip=True)

    # Extract and organize schedule information
    def view_schedule(self):
        manual_schedule = self.manual_entry.get(
            "1.0", tk.END
        ).strip()

        # This must be a list because we use append().
        extracted_text = []
        read_errors = []

        # Read documents
        for file_path in self.documents:
            try:
                text = self.read_document(file_path)

                if text.strip():
                    extracted_text.append(
                        f"\nSource: {os.path.basename(file_path)}\n{text}"
                    )
                else:
                    read_errors.append(
                        f"{os.path.basename(file_path)}: "
                        "No readable text was found."
                    )

            except Exception as error:
                read_errors.append(
                    f"{os.path.basename(file_path)}: {error}"
                )

        # Read website links
        for url in self.links:
            try:
                text = self.read_webpage(url)

                if text.strip():
                    extracted_text.append(
                        f"\nSource: {url}\n{text}"
                    )
                else:
                    read_errors.append(
                        f"{url}: No readable text was found."
                    )

            except Exception as error:
                read_errors.append(f"{url}: {error}")

        # Combine manual entries with extracted text
        schedule = "\n".join(
            [manual_schedule] + extracted_text
        ).strip()

        if not schedule:
            messagebox.showwarning(
                "Empty Schedule",
                "Please enter a schedule, add a link, "
                "or select a document."
            )

            if read_errors:
                messagebox.showwarning(
                    "Read Errors",
                    "\n".join(read_errors)
                )
            return

        # Prepare weekday categories
        days = [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"
        ]

        organized = {day: [] for day in days}
        other_events = []
        current_day = None

        # Recognize times such as 9:00 AM and 2:30 PM
        time_pattern = re.compile(
            r"(\d{1,2}):(\d{2})\s*(AM|PM)",
            re.IGNORECASE
        )

        # Process each line of the combined text
        for line in schedule.splitlines():
            line = line.strip()

            if not line:
                continue

            # Recognize a weekday heading
            matched_day = next(
                (
                    day for day in days
                    if line.lower().rstrip(":") == day.lower()
                ),
                None
            )

            if matched_day:
                current_day = matched_day
                continue

            # Ignore source labels when organizing events
            if line.startswith("Source:"):
                current_day = None
                continue

            match = time_pattern.search(line)

            if match:
                hour = int(match.group(1))
                minute = int(match.group(2))
                meridiem = match.group(3).upper()

                if not (1 <= hour <= 12 and 0 <= minute <= 59):
                    other_events.append(line)
                    continue

                # Convert to minutes after midnight
                sort_hour = hour % 12
                if meridiem == "PM":
                    sort_hour += 12

                total_minutes = sort_hour * 60 + minute

                event = {
                    "time": total_minutes,
                    "description": line
                }

                if current_day:
                    organized[current_day].append(event)
                else:
                    other_events.append(line)
            else:
                other_events.append(line)

        # Create results window
        window = tk.Toplevel(self.root)
        window.title("Organized Schedule")
        window.geometry("700x600")

        tk.Label(
            window,
            text="My Organized Schedule",
            font=("Arial", 20, "bold")
        ).pack(pady=15)

        output = tk.Text(
            window,
            font=("Arial", 11),
            wrap=tk.WORD
        )
        output.pack(
            fill=tk.BOTH, expand=True, padx=20, pady=10
        )

        # Display events by weekday and time
        for day in days:
            events = organized[day]

            if events:
                output.insert(tk.END, f"\n{day.upper()}\n")
                output.insert(tk.END, "-" * 35 + "\n")

                events.sort(key=lambda event: event["time"])

                for event in events:
                    output.insert(
                        tk.END,
                        event["description"] + "\n"
                    )

        # Display unclassified text
        if other_events:
            output.insert(tk.END, "\nOTHER ENTRIES\n")
            output.insert(tk.END, "-" * 35 + "\n")

            for event in other_events:
                output.insert(tk.END, event + "\n")

        # Display saved links
        if self.links:
            output.insert(tk.END, "\nLINKS\n")
            for link in self.links:
                output.insert(tk.END, link + "\n")

        # Display selected documents
        if self.documents:
            output.insert(tk.END, "\nDOCUMENTS\n")
            for file_path in self.documents:
                output.insert(tk.END, file_path + "\n")

        output.config(state=tk.DISABLED)

        # Show any reading errors
        if read_errors:
            messagebox.showwarning(
                "Read Errors",
                "\n".join(read_errors),
                parent=window
            )

# Start the application
if __name__ == "__main__":
    root = tk.Tk()
    app = SchedulerApp(root)
    root.mainloop()