# import tkinter as tk
# from tkinter import messagebox 

# #window icon
# root = tk.Tk()
# root.title("AI School Scheduler")
# root.geometry("800x500")
# #root.configure(bg="white")

# #calls button
# def button_action():
#     print("button works!")

# #loading icon
# try:
#     icon = tk.PhotoImage(file="icon.png")

#     floating_button = tk.Button(
#         root,
#         image=icon,
#         command=button_action,
#         relief = "flat",
#         boderwidth = 0,
#         cursor = "hand2",
#         bg = "white",
#         activebackground = "white" 
#     )
# # button pos
# floating_button.place(
#     relx = 1.0,
#     rely = 1.0,
#     x = -20,
#     y = -20,
#     anchor = "se"
# )

# except tk.TclError:
#     messagebox.showerror(
#         "Error",
#         "Couldn't load icon.png"
#     )

# # keeps window running
# root.mainloop()


import tkinter as tk

root = tk.Tk()
root.geometry("800x500")
root.configure(bg="white")

# load icon from folder
icon = tk.PhotoImage(file="icon.png")

#calling image when clicked
def button_action():
    print("Works!")

#image button
button = tk.Button(
    root,
    image=icon,
    command=button_action,
    borderwidth=0,
    bg="white",
    cursor="hand2"
)

#put in corner
button.place(
    relx=1.0,
    rely=1.0,
    x=-20,
    y=-20,
    anchor="se"
)

root.mainloop()