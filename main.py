# Import PyMuPDF, which allows Python to open and extract
# text from PDF files.
import pymupdf


# Name of the PDF file we want to process.
pdf_path = "syllabus.pdf"

# Name of the text file where we will save the
# extracted syllabus text.
text_path = "syllabus_text.txt"


# Open the PDF file.
# The returned 'document' object contains all the pages
# of the syllabus.
document = pymupdf.open(pdf_path)


# Create an empty list to store the text from each page.
page_texts = []


# Loop through every page in the PDF.
#
# enumerate() gives us:
#   page_number = the page's number (starting at 0)
#   page = the actual page object
for page_number, page in enumerate(document):

    # Extract all readable text from the current page.
    text = page.get_text()

    # Add the extracted text to our list.
    page_texts.append(text)

    # Print a heading showing which page we are currently displaying.
    #
    # page_number starts at 0, so we add 1 to display
    # normal page numbering (Page 1, Page 2, etc.).
    print(f"\n--- Page {page_number + 1} ---\n")

    # Print the extracted text from the current page.
    print(text)


# Close the PDF after we are finished reading it.
# This releases the file resources used by PyMuPDF.
document.close()


# Open (or create) the text file where we will save
# the extracted syllabus information.
#
# "w" means write mode:
#   - Creates the file if it doesn't exist.
#   - Replaces the existing contents if it does exist.
#
# encoding="utf-8" allows the file to correctly store
# a wide range of characters.
with open(text_path, "w", encoding="utf-8") as output_file:

    # Join the text from all pages together.
    #
    # "\n" places a blank line between each page's text.
    #
    # Then write the combined text into syllabus_text.txt.
    output_file.write("\n".join(page_texts))