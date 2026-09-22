import fitz

pdf_path = "syllabus.pdf"

document = fitz.open(pdf_path)

for page_number, page in enumerate(document):
    text = page.get_text()

    print(f"\n--- Page {page_number + 1} ---\n")
    print(text)

document.close()